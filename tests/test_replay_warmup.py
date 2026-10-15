"""Replay settling and prepared-recording boundaries; no game is launched."""
from copy import deepcopy
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock, patch

from dolly.path import Keyframe, Project
from dolly.replay_warmup import ReplayWarmupMixin, seek_game_tick_offset


class SimulatedWarmup(ReplayWarmupMixin):
    def __init__(self):
        self._session = object()
        self._demo = Path("example.dem")
        self._last_seek_details = dict(target_tick=500, verified=True, game_tick_offset=2835)
        self._camera_calibration = {"verified": True}
        self._stop_event = threading.Event()
        self.events = []
        self.tick = 500
        self.paused = True
        self.goal = None
        self.changed_replay = False
        self.unavailable = False
        self.active_recorder = False
        self.stalled = False
        self.cancel_after_resume = False
        self.bad_clock = False
        self.bridge = Mock()
        self.bridge.status.side_effect = self.status
        self.bridge.prepare.side_effect = lambda *args: self.events.append(("prepare", args))
    def _supports_native_flight(self): return True
    def _console_command_available(self, name): return not self.unavailable
    def _native_bridge(self): return self.bridge
    def _recorder_active(self): return self.active_recorder
    def _check_position_cancelled(self):
        if self._stop_event.is_set(): raise RuntimeError("Cancelled")
    def _snapshot(self, project): self.events.append("snapshot")
    def _position_direct_frame(self, frame, tick): self.events.append("calibrate")
    def _release_native_camera(self): self.events.append("release")
    def _seek_tick(self, tick):
        self.events.append(("seek", tick));self.tick = tick
        self._last_seek_details = dict(target_tick=tick, verified=True,
                                      game_tick_offset=999 if self.bad_clock else 2835)
        return {"tick": tick}
    def _detach_spectator_view(self): self.events.append("detach")
    def _require_native_demo(self, status):
        if self.changed_replay: raise RuntimeError("Different replay")
    def _message(self, *args, **kw): pass
    def _request(self, command):
        self.events.append(command)
        if "demo_pauseatservertick" in command:
            self.goal = int(command.rsplit(" ", 1)[1]) - 2835
            self.paused = False
            if self.cancel_after_resume: self._stop_event.set()
        elif command == "demo_resume; demo_pause": self.goal = None;self.paused = True
    def status(self):
        if not self.paused and not self.stalled:
            self.tick = min(self.goal, self.tick + 64)
            self.paused = self.tick == self.goal
        return {"tick": self.tick, "paused": self.paused, "frame_count": 100}
    def _wait_paused_native_view(self, bridge, before, *, expected_tick):
        status = self.status()
        if status["tick"] != expected_tick: raise RuntimeError("Wrong tick")
        return status
    def _require_demo(self, **kw):
        if self.changed_replay: raise RuntimeError("Different replay")
        return {"tick": self.tick}
    def _alive(self): return True


class WarmupTests(unittest.TestCase):
    def setUp(self):
        self.c = SimulatedWarmup()
        self.project = Project(start_tick=500, keyframes=[
            Keyframe(0, 0, 0, 100, 0, 0, 0), Keyframe(1, 10, 0, 100, 0, 0, 0)])
        self.index = patch("dolly.replay_warmup.packet_index", return_value=None)
        self.index.start();self.addCleanup(self.index.stop)
    def warm(self, **kw):
        return self.c._warm_replay_for_shot(self.project, 0, {"tick": 500}, **kw)
    def test_fresh_clock_mapping_accepts_forward_and_rejects_wrong_or_ambiguous_target(self):
        text = "Demo Skipping: skipping to demo tick 500 (game tick 3335) from full packet 1"
        self.assertEqual(seek_game_tick_offset(text, 500), 2835)
        self.assertEqual(seek_game_tick_offset(text.replace("skipping to", "skipping forward to"), 500), 2835)
        self.assertIsNone(seek_game_tick_offset(text, 501))
        self.assertIsNone(seek_game_tick_offset(text + text.replace("3335", "3336"), 500))
        self.assertIsNone(seek_game_tick_offset("No clock", 500))
    def test_settling_ages_before_exact_start_without_final_seek_or_project_changes(self):
        original = self.project.to_dict()
        result = self.warm(calibrate=True)
        self.assertTrue(result["replay_warmup"]["verified"])
        self.assertEqual(result["tick"], 500)
        self.assertEqual(result["replay_warmup"]["simulated_seconds"], 2)
        self.assertEqual([e for e in self.c.events if isinstance(e, tuple) and e[0] == "seek"], [("seek", 372)])
        self.assertIn("demo_timescale 1; demo_resume; demo_pauseatservertick 3335", self.c.events)
        self.assertLess(self.c.events.index("calibrate"), self.c.events.index(("seek", 372)))
        self.assertEqual(self.project.to_dict(), original)
        args = self.c.bridge.prepare.call_args.args
        self.assertEqual(args[1:4], (0, 1.0, True))
    def test_active_recorder_is_rejected_before_seek_or_camera_write(self):
        self.c.active_recorder = True
        with self.assertRaisesRegex(RuntimeError, "before recording"): self.warm()
        self.assertEqual(self.c.events, [])
    def test_camera_hold_does_not_start_authored_effects_before_the_shot(self):
        from dolly.path import CvarTrack, TrackKey
        self.project.setup_values = {"r_dof_override": 1}
        self.project.tracks = [CvarTrack("r_citadel_depthoffield_focus_distance",
                                       [TrackKey(0, 600), TrackKey(1, 1200)])]
        self.project.confetti_enabled = True
        original = self.project.to_dict()
        self.warm()
        held = self.c.bridge.prepare.call_args.args[0]
        self.assertEqual(held.tracks, [])
        self.assertEqual(held.setup_values, {})
        self.assertFalse(held.confetti_enabled)
        self.assertEqual(held.keyframes, self.project.keyframes)
        self.assertEqual(self.project.to_dict(), original)
    def test_missing_mapping_command_or_history_preserves_existing_start(self):
        for reason in ("seek_clock_unavailable", "pause_command_unavailable", "insufficient_replay_history"):
            with self.subTest(reason=reason):
                self.c = SimulatedWarmup()
                if reason == "seek_clock_unavailable": self.c._last_seek_details.pop("game_tick_offset")
                if reason == "pause_command_unavailable": self.c.unavailable = True
                target = 100 if reason == "insufficient_replay_history" else 500
                if target == 100: self.c._last_seek_details["target_tick"] = target
                result = self.c._warm_replay_for_shot(self.project, 0, {"tick": target})
                self.assertEqual(result["replay_warmup"]["reason"], reason)
                self.assertEqual(self.c.events, [])
    def test_cancel_before_preparation_has_no_writes(self):
        self.c._stop_event.set()
        with self.assertRaisesRegex(RuntimeError, "Cancelled"): self.warm()
        self.assertEqual(self.c.events, [])
    def test_cancel_after_resume_disarms_owned_goal(self):
        self.c.cancel_after_resume = True
        with self.assertRaisesRegex(RuntimeError, "Cancelled"): self.warm()
        self.assertEqual(self.c.events[-1], "demo_resume; demo_pause")
        self.assertIsNone(self.c.goal)
        self.assertFalse(self.c._replay_warmup_active)
    def test_stop_button_cancels_the_active_settling_worker(self):
        from dolly.controller import Controller
        controller = Controller()
        controller._replay_warmup_active = True
        self.assertTrue(controller.cancel_replay_recovery())
        self.assertTrue(controller._stop_event.is_set())
    def test_clock_change_aborts_before_arming_goal(self):
        self.c.bad_clock = True
        with self.assertRaisesRegex(RuntimeError, "clock changed"): self.warm()
        self.assertIsNone(self.c.goal)
        self.c.bridge.prepare.assert_not_called()
    def test_timeout_disarms_goal_without_seek_retry(self):
        self.c.stalled = True
        with patch("dolly.replay_warmup.time.perf_counter", side_effect=[0, 9]):
            with self.assertRaisesRegex(RuntimeError, "did not pause"): self.warm()
        self.assertEqual(self.c.events[-1], "demo_resume; demo_pause")
    def test_changed_replay_never_receives_cleanup_control_commands(self):
        request = self.c._request
        def changed(command): request(command);self.c.changed_replay = True
        self.c._request = changed
        with self.assertRaisesRegex(RuntimeError, "Different replay"): self.warm()
        self.assertNotIn("demo_resume; demo_pause", self.c.events)
    def test_native_first_view_rejects_moved_tick_pose_or_nonfinite_readback(self):
        frame = self.project.evaluate(0)
        fields = ("x", "y", "z", "pitch", "yaw", "roll", "aspect_ratio")
        native = dict(paused=True, tick=500, applied_pose=[frame[n] for n in fields])
        self.c._check_warmed_native_view(native, frame, 500)
        for changed in (dict(native, tick=501), dict(native, paused=False),
                        dict(native, applied_pose=[float("nan")] + native["applied_pose"][1:])):
            with self.assertRaises(RuntimeError): self.c._check_warmed_native_view(changed, frame, 500)


class WarmRecordingHandoffTests(unittest.TestCase):
    def setUp(self):
        from test_native_controller import NativeControllerTests
        NativeControllerTests.setUp(self)
        self.bridge.video_status = Mock(return_value={"state": "recording"})
        self.controller.mark_recording_pending(True)
        self.controller._recording_replay = (self.controller._session, str(self.controller._demo), 100)
        self.controller._recording_warmup = {"project": self.project.to_dict(), "start": 0,
            "positioned": {"tick": 100, "replay_warmup": {"performed": True,
                "verified": True, "calibration": {"verified": True}}}}
    def test_recording_reuses_prepared_start_without_reseek_calibration_or_more_warmup(self):
        with patch.object(self.controller, "_seek", side_effect=AssertionError("No second seek")), \
             patch.object(self.controller, "_position_direct_frame", side_effect=AssertionError("No recalibration")), \
             patch.object(self.controller, "_warm_replay_for_shot", side_effect=AssertionError("No recording warmup")):
            self.controller.play(self.project, speed=.5)
        self.controller._thread = None
        self.assertEqual(self.controller._playback_details["initial_tick"], 100)
        self.assertTrue(self.controller._playback_details["replay_warmup"]["performed"])
        self.assertIsNone(self.controller._recording_warmup)
        self.recovery.assert_not_called()
    def test_changed_path_or_start_rejects_one_use_reservation_before_dispatch(self):
        self.project.keyframes[0].x += 1
        with self.assertRaisesRegex(RuntimeError, "path changed"):
            self.controller.play(self.project)
        self.controller._thread = None
        self.assertNotIn("native.prepare", self.bridge.events)
        self.assertIsNone(self.controller._recording_replay)
        self.assertIsNone(self.controller._recording_warmup)

    def test_internal_stop_does_not_lose_verified_camera_offset(self):
        expected = {"x": 3.0, "y": -2.0, "z": 56.0}
        self.controller._recording_warmup["positioned"]["replay_warmup"]["calibration"]["offset"] = expected
        with patch.object(self.controller, "_seek", side_effect=AssertionError("No second seek")), \
             patch.object(self.controller, "_position_direct_frame", side_effect=AssertionError("No recalibration")):
            self.controller.play(self.project)
        self.controller._thread = None
        self.assertEqual(self.controller._camera_offset, expected)
