"""Owned pause clocks use pre-command console provenance, not render ticks."""
from collections import deque
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_native_controller as fixture


class NativeOwnedPauseTests(unittest.TestCase):
    setUp = fixture.NativeControllerTests.setUp
    prepare = fixture.NativeControllerTests.prepare
    run_native = fixture.NativeControllerTests.run_native

    def install_owned_pause(self, *, ticks=(1981, 1979, 1979), changed=None, trigger_sample=3):
        self.prepare()
        self.controller._thread = self.thread
        self.controller._stop_event.wait = self.clock.advance
        original_status = self.bridge.status
        original_request = self.console.request
        state = {"samples": 0, "nested": False, "pause_sent": False}

        def request(command, **kwargs):
            result = original_request(command, **kwargs)
            if command == "demo_pause" and not state["pause_sent"]:
                state["pause_sent"] = True
                self.console.goto_outputs = deque(ticks)
                if changed == "session":
                    self.controller._session = SimpleNamespace(**vars(self.controller._session))
                elif changed == "replay":
                    self.console.demo_name = "another.dem"
                elif changed == "cancel":
                    self.controller._stop_event.set()
            return result

        def status():
            if state["nested"]:
                result = original_status()
                self.bridge.phase = .13541412353515625
                result.update(phase=self.bridge.phase, tick=1979, state="playing")
                self.console.tick = 1979
                return result
            state["samples"] += 1
            if state["samples"] == trigger_sample:
                self.console.tick = 1979
                state["nested"] = True
                try:
                    self.controller.toggle_replay()
                    # LIVE-02's harness queried once after toggle returned.
                    # On the old path this consumes transient 1981, leaving
                    # stable 1979 for the monitor's first pause-edge query.
                    if not self.controller._stop_event.is_set():
                        self.controller._require_demo()
                    state["intent"] = getattr(self.controller, "_native_pause_intent", None)
                finally:
                    state["nested"] = False
            result = original_status()
            phase = .1 if state["samples"] == 1 else .13541412353515625
            self.bridge.phase = phase
            result.update(phase=phase, state="playing",
                          tick=1981 if state["samples"] == 2 else 1979)
            self.console.tick = 1979
            return result

        def wait(delay, event):
            self.clock.advance(delay)
            if len(self.controller._playback_samples) >= 3:
                event.set()

        self.console.request = request
        self.bridge.status = status
        self.stack.enter_context(patch("dolly.controller.FrameWait", return_value=SimpleNamespace(wait=wait, close=lambda: None)))
        self.stack.enter_context(patch.object(self.controller, "_finish_native_playback", return_value=None))
        return state

    def test_owned_pause_uses_1979_baseline_after_transient_1981_then_stable_1979(self):
        original = deepcopy(self.project.to_dict())
        self.install_owned_pause()
        self.run_native()
        self.assertNotIn("error", self.controller._playback_details)
        self.assertEqual(self.project.to_dict(), original)
        samples = self.controller._playback_samples
        self.assertEqual(samples[-2]["monitor_tick"], 1981)
        self.assertEqual(samples[-1]["monitor_tick"], 1979)
        check = self.controller._playback_details["pause_clock_checks"][-1]
        self.assertEqual(check["source"], "owned_pause")
        self.assertEqual(check["before_replay_tick"], 1979)
        self.assertEqual(check["replay_tick"], 1979)
        self.assertEqual(check["post_pause_ticks"], [1981, 1979, 1979])
        frames = [check["before_frame"], *check["post_pause_frames"]]
        self.assertTrue(all(after > before for before, after in zip(frames, frames[1:])))
        self.assertIsNone(self.controller._native_pause_intent)

    def test_owned_pause_can_anchor_the_first_already_paused_monitor_sample(self):
        self.install_owned_pause(trigger_sample=1)
        self.run_native()
        self.assertNotIn("error", self.controller._playback_details)
        first = self.controller._playback_samples[0]
        self.assertTrue(first["paused"])
        self.assertEqual(first["monitor_tick"], 1979)
        check = self.controller._playback_details["pause_clock_checks"][0]
        self.assertEqual(check["source"], "owned_pause")
        self.assertIsNone(check["previous_tick"])

    def test_owned_pause_still_rejects_a_real_backward_console_clock(self):
        self.install_owned_pause(ticks=(1981, 1978, 1978))
        self.run_native()
        self.assertIn("replay jumped", self.controller._playback_details.get("error", "").lower())
        self.assertEqual(len(self.controller._playback_samples), 2)

    def test_owned_pause_still_rejects_a_large_forward_console_clock(self):
        self.install_owned_pause(ticks=(2500, 2500, 2500))
        self.run_native()
        self.assertIn("replay jumped", self.controller._playback_details.get("error", "").lower())
        self.assertEqual(len(self.controller._playback_samples), 2)

    def test_changed_session_cannot_confirm_an_owned_pause(self):
        self.install_owned_pause(changed="session")
        self.run_native()
        self.assertIn("pause ownership changed", self.controller._playback_details.get("error", "").lower())
        self.assertEqual(len(self.controller._playback_samples), 2)

    def test_changed_replay_cannot_confirm_an_owned_pause(self):
        self.install_owned_pause(changed="replay")
        self.run_native()
        self.assertIn("identity changed", self.controller._playback_details.get("error", "").lower())
        self.assertEqual(len(self.controller._playback_samples), 2)

    def test_cancelled_owned_pause_does_not_become_a_playback_failure(self):
        self.install_owned_pause(changed="cancel")
        self.run_native()
        self.assertNotIn("error", self.controller._playback_details)
        self.assertIsNone(self.controller._native_pause_intent)

    def confirmed_intent(self):
        state = self.install_owned_pause()
        self.run_native()
        self.controller._stop_event.clear()
        intent = state["intent"]
        intent.update(state="pending", deadline=self.clock.now + .1)
        self.controller._native_pause_intent = intent
        return intent

    def test_monitor_waits_read_only_for_the_pause_worker_to_confirm(self):
        intent = self.confirmed_intent()
        commands = list(self.console.requests)
        waits = []

        def wait(delay):
            waits.append(delay)
            self.clock.advance(delay)
            if len(waits) == 2:
                intent["state"] = "confirmed"

        self.controller._stop_event.wait = wait
        result = self.controller._owned_native_pause_clock()
        self.assertEqual(result["tick"], 1979)
        self.assertEqual(len(waits), 2)
        self.assertIsNone(self.controller._native_pause_intent)
        self.assertEqual(self.console.requests, commands)

    def test_monitor_wait_is_cancelled_without_consuming_a_clock(self):
        self.confirmed_intent()
        self.controller._stop_event.wait = lambda _delay: self.controller._stop_event.set()
        self.assertIsNone(self.controller._owned_native_pause_clock())
        self.assertIsNone(self.controller._native_pause_intent)

    def test_missing_acknowledgment_and_expired_confirmation_cannot_rebase(self):
        intent = self.confirmed_intent()
        intent["deadline"] = self.clock.now + .03
        with self.assertRaisesRegex(RuntimeError, "confirmation deadline"):
            self.controller._owned_native_pause_clock()
        self.assertIsNone(self.controller._native_pause_intent)
        intent.update(state="confirmed", deadline=self.clock.now - .01)
        self.controller._native_pause_intent = intent
        with self.assertRaisesRegex(RuntimeError, "confirmation deadline"):
            self.controller._owned_native_pause_clock()
        self.assertIsNone(self.controller._native_pause_intent)

    def test_new_playback_identity_cannot_consume_the_old_pause(self):
        intent = self.confirmed_intent()
        intent["state"] = "confirmed"
        self.controller._playback_details = dict(self.controller._playback_details)
        with self.assertRaisesRegex(RuntimeError, "pause ownership changed"):
            self.controller._owned_native_pause_clock()
        self.assertIsNone(self.controller._native_pause_intent)


if __name__ == "__main__":
    unittest.main()
