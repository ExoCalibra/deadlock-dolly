"""Exercise replay pause transitions at the controller/bridge boundary."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import test_native_controller as fixture


class NativePauseBoundaryTests(unittest.TestCase):
    setUp = fixture.NativeControllerTests.setUp
    prepare = fixture.NativeControllerTests.prepare
    run_native = fixture.NativeControllerTests.run_native

    def install_transition(self, *, raw_tick=115, replay_tick=116,
                           paused=True, frozen=False, cancel=False,
                           one_sample=False, seek_while_paused=False,
                           stale_frame=False, bad_effects=False,
                           bad_phase=False, wrong_demo=False):
        self.prepare(frozen=frozen)
        original_status = self.bridge.status
        samples = []

        def status():
            # First establish two running samples. The third render is a
            # paused view with a native tick that crosses the strict raw-tick
            # guard. The authoritative console replay can remain continuous
            # or independently confirm a real seek.
            if len(samples) == 2:
                self.console.paused = paused
                self.console.tick = replay_tick
            result = original_status()
            if len(samples) in (2, 3):
                self.console.tick = replay_tick
                result.update(tick=raw_tick, paused=paused, phase=.25,
                              state='playing')
                if len(samples) == 3 and one_sample:
                    result['tick'] = replay_tick
                if len(samples) == 3 and seek_while_paused:
                    self.console.tick = result['tick'] = 50
                if stale_frame:
                    result['frame_count'] = 0
                if bad_effects:
                    result['effect_count'] = 3
                if bad_phase:
                    result['phase'] = float('nan')
                if wrong_demo:
                    result['demo_name'] = 'another.dem'
                if cancel:
                    self.controller._stop_event.set()
            elif len(samples) == 4:
                self.console.paused = False
            samples.append(deepcopy(result))
            return result

        self.bridge.status = status
        return samples

    def test_continuous_replay_pause_reconciles_render_tick_then_resumes(self):
        saved = self.project.to_dict()
        samples = self.install_transition()
        self.run_native()
        self.assertGreaterEqual(len(samples), 5)
        self.assertNotIn('error', self.controller._playback_details)
        self.assertIn('Native shot finished', self.controller.status()['message'])
        self.assertEqual(self.project.to_dict(), saved)
        self.assertEqual(self.controller._playback_samples[-1]['phase'], 1)
        correction = self.controller._playback_details['pause_clock_checks'][0]
        self.assertEqual((correction['previous_tick'], correction['native_tick'],
                          correction['replay_tick']), (116, 115, 116))

    def test_actual_backward_seek_during_pause_is_still_rejected(self):
        self.install_transition(raw_tick=40, replay_tick=40)
        self.run_native()
        self.assertIn('replay jumped', self.controller.status()['message'])
        self.assertLess(self.controller._playback_samples[-1]['phase'], .5)

    def test_one_anomalous_sample_is_not_learned_as_replay_tick(self):
        self.install_transition(raw_tick=6000, one_sample=True)
        self.run_native()
        self.assertNotIn('error', self.controller._playback_details)
        self.assertTrue(all(sample['tick'] != 6000 for sample in
                            self.controller._playback_samples if sample['paused'] is False))

    def test_real_seek_after_confirmed_pause_still_stops(self):
        self.install_transition(seek_while_paused=True)
        self.run_native()
        self.assertIn('replay jumped', self.controller.status()['message'])

    def test_periodic_identity_read_checks_replay_tick_when_native_tick_is_stale(self):
        self.install_transition()
        original_status = self.bridge.status
        original_read = self.controller._require_demo
        paused_reads = 0

        def status():
            result = original_status()
            if result['paused']:
                self.clock.advance(.6)
            return result

        def read(*args, **kwargs):
            nonlocal paused_reads
            result = original_read(*args, **kwargs)
            if self.console.paused and self.bridge.state == 'playing':
                paused_reads += 1
                if paused_reads >= 2:
                    result['tick'] = 50
            return result

        self.bridge.status = status
        with patch.object(self.controller, '_require_demo', side_effect=read):
            self.run_native()
        self.assertGreaterEqual(paused_reads, 2)
        self.assertIn('replay jumped', self.controller.status()['message'])

    def test_restarted_callback_is_rejected_before_clock_reconciliation(self):
        self.install_transition(stale_frame=True)
        self.run_native()
        self.assertIn('callback restarted', self.controller.status()['message'])
        self.assertNotIn('pause_clock_checks', self.controller._playback_details)

    def test_wrong_effects_are_rejected_before_clock_reconciliation(self):
        self.install_transition(bad_effects=True)
        self.run_native()
        self.assertIn('effect count', self.controller.status()['message'])
        self.assertNotIn('pause_clock_checks', self.controller._playback_details)

    def test_invalid_phase_is_rejected_before_clock_reconciliation(self):
        self.install_transition(bad_phase=True)
        self.run_native()
        self.assertIn('time changed unexpectedly', self.controller.status()['message'])
        self.assertNotIn('pause_clock_checks', self.controller._playback_details)

    def test_changed_demo_is_rejected_before_clock_reconciliation(self):
        self.install_transition(wrong_demo=True)
        self.run_native()
        self.assertIn('identity changed', self.controller.status()['message'])
        self.assertNotIn('pause_clock_checks', self.controller._playback_details)

    def test_frozen_tick_change_cannot_use_pause_reconciliation(self):
        self.install_transition(frozen=True)
        self.run_native(frozen=True)
        self.assertIn('scene resumed during native Frozen', self.controller.status()['message'])
        self.assertNotIn('pause_clock_checks', self.controller._playback_details)

    def test_actual_large_forward_seek_during_pause_is_still_rejected(self):
        self.install_transition(raw_tick=500, replay_tick=500)
        self.run_native()
        self.assertIn('replay jumped', self.controller.status()['message'])

    def test_running_tick_rewind_cannot_use_pause_reconciliation(self):
        self.install_transition(paused=False)
        self.run_native()
        self.assertIn('replay jumped', self.controller.status()['message'])
        self.assertNotIn('pause_clock_checks', self.controller._playback_details)

    def test_unreadable_replay_cannot_authorize_pause_reconciliation(self):
        self.install_transition()
        original = self.controller._require_demo

        def read(*args, **kwargs):
            if self.console.paused and self.bridge.state == 'playing':
                raise RuntimeError('Replay identity unavailable')
            return original(*args, **kwargs)

        with patch.object(self.controller, '_require_demo', side_effect=read):
            self.run_native()
        self.assertIn('Replay identity unavailable', self.controller.status()['message'])

    def test_cancellation_during_status_does_not_report_a_clock_failure(self):
        self.install_transition(cancel=True)
        self.run_native()
        self.assertNotIn('error', self.controller._playback_details)
        self.assertNotIn('replay jumped', self.controller.status()['message'])


if __name__ == '__main__':
    unittest.main()
