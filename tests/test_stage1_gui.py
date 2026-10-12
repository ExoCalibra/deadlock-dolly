"""User intent at the new desktop/native-editor boundary, without a game."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from dolly.bindings import CaptureBinding
from dolly.editor_actions import EditorBinding
from dolly.gui import DollyApp, _binding_event_key
from dolly.path import Keyframe
from dolly.settings import AppSettings
from test_gui_capture import CaptureHarness, Var


class Stage1GuiTests(unittest.TestCase):
    def test_confirmed_native_reset_replaces_path_without_desktop_dialog(self):
        from copy import deepcopy
        from dolly.editor_session import dispatch
        from dolly.path import CvarTrack, TrackKey
        h = CaptureHarness()
        app = h.app
        app.project.keyframes = [Keyframe(0, 1, 2, 3, 4, 5, 6),
                                 Keyframe(3, 7, 8, 9, 10, 11, 12)]
        app.project.tracks = [CvarTrack('r_depth_of_field', [TrackKey(0, 1)], 'step')]
        old_tracks = deepcopy(app.project.tracks)
        event = {'action': 'reset_camera_path', 'value': 0,
                 'pose': [10, 20, 30, 4, 5, 6, 1.5], 'tick': 512, 'paused': True}
        key = Keyframe(0, 10, 20, 30, 4, 5, 6, aspect_ratio=1.5)
        app.controller.capture_native_snapshot = Mock(return_value=(key, 512))
        with patch('dolly.gui.messagebox.askyesno') as confirm:
            dispatch(app, event, Mock())
            h.finish()
            confirm.assert_not_called()
        self.assertEqual(app.project.keyframes, [key])
        self.assertEqual(app.project.start_tick, 512)
        self.assertEqual(app.project.tracks, old_tracks)
        self.assertEqual(h.errors, [])

    def test_failed_native_reset_preserves_existing_path(self):
        from dolly.editor_session import dispatch
        h = CaptureHarness()
        app = h.app
        app.project.keyframes = [Keyframe(0, 1, 2, 3, 4, 5, 6)]
        original = app.project
        app.controller.capture_native_snapshot = Mock(side_effect=ValueError('Capture unavailable'))
        dispatch(app, {'action': 'reset_camera_path', 'value': 0}, Mock())
        h.finish()
        self.assertIs(app.project, original)
        self.assertEqual(len(h.errors), 1)

    def test_native_reset_is_blocked_during_path_playback(self):
        from dolly.editor_session import dispatch
        h = CaptureHarness()
        h.app.playing = True
        with self.assertRaisesRegex(ValueError, 'Stop path playback'):
            dispatch(h.app, {'action': 'reset_camera_path'}, Mock())
        self.assertIsNone(h.pending)

    def harness(self):
        h = CaptureHarness()
        app = h.app
        app.game_path = Var('B:/SteamLibrary/Deadlock/game/bin/win64/deadlock.exe')
        app.demo_path = Var('B:/SteamLibrary/Deadlock/game/citadel/replays/shot.dem')
        app.replay_folder = Var('B:/SteamLibrary/Deadlock/game/citadel/replays')
        app.launch_options = Var('-windowed -w 1920 -h 1080')
        app.protocol = Var('Netconsole')
        app.startup_bar = Mock()
        app.startup_progress = Var('')
        app.startup_cancel = None
        app.cancel_startup_button = Mock()
        app._disable_external_input = Mock()
        app.controller.start_editing = Mock(return_value={'startup_stage': 'editing_ready'})
        app._editing_started = Mock()
        app._refresh_bindings = Mock()
        app.binding_feedback = Var('')
        return h, app

    def test_one_click_snapshots_paths_and_options_and_enters_native_editor(self):
        h, app = self.harness()
        app._start_editing_session()
        app.demo_path.set('different.dem')
        with patch('dolly.gui.save_settings') as save:
            h.finish()
        args, kwargs = app.controller.start_editing.call_args
        self.assertTrue(args[1].endswith('/shot.dem'))
        self.assertEqual(kwargs['protocol'], 'netcon')
        self.assertIs(kwargs['native'], True)
        self.assertEqual(kwargs['launch_options'], '-windowed -w 1920 -h 1080')
        self.assertFalse(kwargs['cancel_event'].is_set())
        self.assertEqual(save.call_args.args[0].demo_path, args[1])
        app._disable_external_input.assert_called_once()
        app._editing_started.assert_called_once()
        self.assertEqual(h.errors, [])

    def test_invalid_additional_options_never_launch_or_disable_current_input(self):
        h, app = self.harness()
        app.launch_options.set('-secure +playdemo other.dem')
        app._start_editing_session()
        self.assertTrue(h.errors)
        self.assertIsNone(h.pending)
        app.controller.start_editing.assert_not_called()
        app._disable_external_input.assert_not_called()

    def test_cancel_button_sets_the_same_live_signal_passed_to_startup(self):
        h, app = self.harness()
        app._start_editing_session()
        app._cancel_startup()
        with patch('dolly.gui.save_settings'):
            h.finish()
        self.assertTrue(app.controller.start_editing.call_args.kwargs['cancel_event'].is_set())
        self.assertIn('Cancelling', app.startup_progress.get())

    def test_native_event_starts_empty_path_and_uses_press_pose_and_tick(self):
        h = CaptureHarness()
        app = h.app
        snapshot = {'pose': [10, 20, 30, 4, 5, 6, 1.5], 'tick': 512, 'paused': True}
        app.controller.capture_native_snapshot = Mock(return_value=(Keyframe(0, 10, 20, 30, 4, 5, 6, aspect_ratio=1.5), 512))
        app._capture_view('append', native_snapshot=snapshot)
        h.finish()
        app.controller.capture_native_snapshot.assert_called_once_with(snapshot, time=0.0)
        self.assertEqual(app.project.start_tick, 512)
        self.assertEqual(app.project.keyframes[0].z, 30)
        self.assertEqual(app.project.keyframes[0].aspect_ratio, 1.5)
        self.assertEqual(app.controller.calls, [])
        self.assertEqual(h.errors, [])

    def test_native_replay_timing_uses_snapshot_tick_not_later_live_tick(self):
        h = CaptureHarness()
        app = h.app
        app.project.keyframes = [Keyframe(0, 1, 2, 3, 0, 0, 0)]
        app.project.start_tick = 512
        app.start_tick.set('512')
        app.capture_mode.set('Replay timing')
        app.controller.tick = 2000
        app.controller.capture_native_snapshot = Mock(return_value=(Keyframe(0, 10, 20, 30, 0, 0, 0), 640))
        app._capture_view('append', native_snapshot={'tick': 640})
        h.finish()
        self.assertEqual(app.project.keyframes[-1].time, 2.0)
        self.assertEqual(h.errors, [])

    def test_saving_keybind_retires_old_listener_and_keeps_launcher_preferences(self):
        h, app = self.harness()
        app.capture_hotkey = helper = Mock()
        settings = app.app_settings.with_capture_binding(CaptureBinding('Mouse5', False, False))
        app._persist_preferences(settings, 'Saved')
        with patch('dolly.gui.save_settings') as save, patch('dolly.gui.editor_session.configure'):
            h.finish()
        helper.stop.assert_called_once()
        self.assertIsNone(app.capture_hotkey)
        self.assertFalse(app.hotkey_enabled.get())
        self.assertTrue(save.call_args.args[0].game_path.startswith('B:/'))
        self.assertEqual(app.app_settings.capture_binding.key, 'Mouse5')

    def test_clearing_capture_binding_stops_legacy_listener_despite_retained_alias(self):
        h, app = self.harness()
        app.capture_hotkey = helper = Mock()
        bindings = dict(app.app_settings.action_bindings)
        bindings['capture'] = None
        settings = app.app_settings.with_action_bindings(bindings)
        app._persist_preferences(settings, 'Unbound')
        with patch('dolly.gui.save_settings'), patch('dolly.gui.editor_session.configure'):
            h.finish()
        helper.stop.assert_called_once()
        app._toggle_capture_hotkey()
        self.assertFalse(app.hotkey_enabled.get())
        self.assertIn('Unbound', app.hotkey_label.get())

    def test_binding_recorder_preserves_f7_and_side_mouse_buttons(self):
        self.assertEqual(_binding_event_key(SimpleNamespace(keysym='F7', num='??')), 'F7')
        self.assertEqual(_binding_event_key(SimpleNamespace(num=4)), 'Mouse4')
        self.assertEqual(_binding_event_key(SimpleNamespace(num=5)), 'Mouse5')
        self.assertIsNone(_binding_event_key(SimpleNamespace(num=1)))
        self.assertEqual(_binding_event_key(SimpleNamespace(keysym='k', num='??')), 'K')


class CloseAfterGameExitTests(unittest.TestCase):
    """Closing Dolly must work after the user already closed Deadlock."""

    def app(self):
        from dolly.ui.operations import OperationQueue
        app = DollyApp.__new__(DollyApp)
        app._operations = OperationQueue()
        app.closed = False
        app._closing = False
        app.busy = False
        app.playing = False
        app._error_dialog_open = False
        app._log = Mock()
        app.status_text = Mock()
        app.busy_text = Mock()
        app.root = SimpleNamespace(my_id=lambda: 1)
        app.controller = Mock()
        app._destroy = Mock()
        app._clear_layer_pipeline = Mock()
        app._report_operation_error = Mock()
        app.startup_cancel = None
        return app

    def test_close_after_failure_still_runs_controller_close_and_destroys(self):
        app = self.app()
        app.controller.close.side_effect = RuntimeError("game already exited")
        # A direct (worker-unavailable) close must still tear the window down.
        app._submit = lambda *a, **k: False
        app._close_after_failure()
        app.controller.close.assert_called_once()
        app._destroy.assert_called_once()

    def test_close_after_failure_uses_the_worker_when_available(self):
        app = self.app()
        calls = []
        app._submit = lambda label, fn, cb=None: calls.append((label, fn, cb)) or True
        app._close_after_failure()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "Closing replay connection")

    def test_closing_error_event_destroys_the_window(self):
        # A stop/close step failing after the game exited must not re-open an
        # error dialog or block the close; the poll throws the event away.
        app = self.app()
        app._submit = lambda *a, **k: False
        app.events.put(("error", "Stopping before closing", RuntimeError("game exited")))
        app._closing = True
        app._poll_once()  # Must not raise and must destroy.
        app._destroy.assert_called_once()
        app._report_operation_error.assert_not_called()


if __name__ == '__main__':
    unittest.main()
