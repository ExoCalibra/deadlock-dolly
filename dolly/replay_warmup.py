"""Age replay effects through normal simulation before an authored shot starts."""
from copy import deepcopy
import math
import re
import time

from .demo_packets import packet_index

WARMUP_SECONDS = 2.0
_SEEK_CLOCK = re.compile(
    r"Demo Skipping:\s*skipping(?: forward)? to demo tick (\d+)\s+\(game tick (\d+)\)")


def seek_game_tick_offset(output, target):
    """Use the engine's fresh seek response, never a guessed clock offset."""
    offsets = {int(game) - int(demo) for demo, game in _SEEK_CLOCK.findall(output)
               if int(demo) == target and 0 <= int(game) <= 0x7fffffff}
    return offsets.pop() if len(offsets) == 1 else None


class ReplayWarmupMixin:
    def _warm_replay_for_shot(self, project, start, positioned, *, calibrate=False):
        """Seek earlier, simulate normally, and let the engine pause exactly.

        A paused render-frame wait cannot age game particles. The native HOLD
        keeps the opening camera visible while the replay runs; no warm-up frames
        are recorded. Once the target is reached, never issue a correcting seek.
        """
        details = {"performed": False, "seconds": WARMUP_SECONDS,
                   "target_tick": positioned["tick"]}
        result = dict(positioned, replay_warmup=details)
        target = int(positioned["tick"])
        target_seek = deepcopy(self._last_seek_details)
        offset = target_seek.get("game_tick_offset")
        if not self._supports_native_flight():
            details["reason"] = "native_editor_unavailable"
            return result
        if (offset is None or not target_seek.get("verified") or
                target_seek.get("actual_tick", target_seek.get("target_tick")) != target):
            details["reason"] = "seek_clock_unavailable"
            return result
        lead = target - int(round(WARMUP_SECONDS * project.tick_rate))
        if lead < 2:
            details["reason"] = "insufficient_replay_history"
            return result
        if self._console_command_available("demo_pauseatservertick") is not True:
            details["reason"] = "pause_command_unavailable"
            return result
        if self._recorder_active():
            raise RuntimeError("Replay effect settling must finish before recording starts.")
        self._replay_warmup_active = True
        try:
            self._check_position_cancelled()
            session, demo = self._session, self._demo
            bridge = self._native_bridge()
            frame = project.evaluate(start)
            frame["cvars"] = {}
            if calibrate:
                # Keep the existing camera displacement/return guard, and snapshot
                # its lens before it writes. Calibration recovery precedes settling.
                self._snapshot(project)
                self._position_direct_frame(frame, target)
            index = packet_index(demo, check_cancelled=self._check_position_cancelled)
            if index is not None:
                following = index.following(lead)
                if following is None or following >= target:
                    details["reason"] = "no_lead_in_packet"
                    return result
                lead = following
            self._check_position_cancelled()
            self._release_native_camera()
            beginning = self._seek_tick(lead)
            if (beginning["tick"] >= target or
                    self._last_seek_details.get("game_tick_offset") != offset):
                raise RuntimeError("The replay clock changed while preparing effect settling.")
            server_target = target + offset
            if not 0 < server_target <= 0x7fffffff:
                raise RuntimeError("The replay did not expose a valid effect-settling pause tick.")
            self._check_position_cancelled()
            self._native_active = True
            self._native_manual = False
            # ARMED frozen paths hold their first authored camera/lens. They do not
            # advance the path while the game simulates the preceding replay time.
            # Warm only the game's replay effects. Authored DOF/weather and
            # other Dolly effects must begin with the actual shot, not early.
            view_project = type(project).from_dict(project.to_dict())
            view_project.tracks = []
            view_project.setup_values = {}
            view_project.confetti_enabled = False
            bridge.prepare(view_project, start, 1.0, True, demo.name)
            self._detach_spectator_view()
            before = bridge.status()
            self._require_native_demo(before)
            self._message("Letting replay effects settle before the shot…", playing=False)
            goal_owned = False
            try:
                self._check_position_cancelled()
                self._demo_speed_changed = True
                goal_owned = True
                # resume CLEARS a previous goal. Arm the stock one-shot command last.
                self._request(f"demo_timescale 1; demo_resume; demo_pauseatservertick {server_target}")
                deadline = time.perf_counter() + 8.0
                while True:
                    self._check_position_cancelled()
                    if self._session is not session or self._demo != demo:
                        raise RuntimeError("The game session changed during effect settling.")
                    current = bridge.status()
                    self._require_native_demo(current)
                    if current["paused"] and current["tick"] > beginning["tick"]:
                        break
                    if current["tick"] > target or time.perf_counter() >= deadline:
                        raise RuntimeError("The replay did not pause at the shot start during effect settling.")
                    self._stop_event.wait(.01)
                paused = self._wait_paused_native_view(bridge, before["frame_count"], expected_tick=target)
                checked = self._require_demo()
                if checked["tick"] != target or paused["tick"] != target:
                    raise RuntimeError("The replay missed the shot start during effect settling.")
                self._check_position_cancelled()
                goal_owned = False  # The one-shot goal reached its paused endpoint.
                details.update(performed=True, verified=True, lead_tick=beginning["tick"],
                               simulated_seconds=(target - beginning["tick"]) / project.tick_rate,
                               paused_tick=target, server_pause_tick=server_target,
                               no_final_seek=True, calibration=deepcopy(self._camera_calibration))
                self._last_seek_details = dict(target_seek, replay_warmup=deepcopy(details))
                return result
            finally:
                if goal_owned and self._session is session and self._demo == demo and self._alive():
                    # Cancellation/timeout must not leave a future goal armed. Never
                    # send cleanup commands into a different replay or session.
                    self._require_demo(require_tick=False)
                    self._request("demo_resume; demo_pause")
        finally:
            self._replay_warmup_active = False

    @staticmethod
    def _check_warmed_native_view(native, frame, tick, *, attached=False):
        if not native.get("paused") or native.get("tick") != tick:
            raise RuntimeError("The replay moved after preparing the settled shot start.")
        pose = native.get("applied_pose")
        if not isinstance(pose, (tuple, list)) or len(pose) != 7:
            raise RuntimeError("The settled shot camera has no valid native readback.")
        # Attached paths resolve their world pose in the native target callback.
        # Their normal typed attachment gates remain responsible for that pose.
        if not attached:
            fields = ("x", "y", "z", "pitch", "yaw", "roll", "aspect_ratio")
            for i, name in enumerate(fields):
                delta = abs(pose[i] - frame[name])
                if name in ("pitch", "yaw", "roll"):
                    delta = abs((pose[i] - frame[name] + 180) % 360 - 180)
                if not math.isfinite(delta) or delta > (.001 if name == "aspect_ratio" else 1.0):
                    raise RuntimeError("The native camera did not match the settled shot start.")
