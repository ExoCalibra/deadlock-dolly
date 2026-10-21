"""Startup error routing: a missing Deadlock intro/preload offers the manual load.

The controller stops verified automatic startup early when the game never runs
its hideout intro (see ``_wait_dashboard_preload``). The desktop must turn that
specific failure into an explicit choice instead of a plain error dialog; every
other failure keeps the standard dialog.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from dolly.controller import PreloadUnavailableError, StartupAcknowledgementRequired
from dolly.gui import DollyApp


class LaunchRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.app = DollyApp.__new__(DollyApp)
        self.app.closed = False
        self.app._error_dialog_open = False
        self.app.root = object()
        self.status = SimpleNamespace(set=Mock())
        self.app.status_text = self.status
        self.app.startup_progress = SimpleNamespace(set=Mock())
        self.app._log = Mock()
        self.app._load_replay = Mock()

    def error(self):
        return PreloadUnavailableError(
            "Deadlock never showed its hideout intro or started the map and shader preload, "
            "so Dolly stopped the automatic check. The game session is still open: load the "
            "selected replay from Startup controls to continue without preload verification.")

    def test_preload_unavailable_offers_and_runs_the_manual_load(self):
        with patch("dolly.gui.messagebox.askyesno", return_value=True) as ask, \
             patch("dolly.gui.dialogs.show_error") as dialog:
            self.app._report_operation_error("Starting replay editor", self.error())
        ask.assert_called_once()
        self.app._load_replay.assert_called_once()
        dialog.assert_not_called()
        self.assertIn("never showed its hideout intro", self.status.set.call_args[0][0])

    def test_game_screen_acknowledgement_keeps_normal_checks_and_shows_no_modal(self):
        error = StartupAcknowledgementRequired('Dismiss the development screen, then choose Check startup again.')
        with patch('dolly.gui.messagebox.askyesno') as ask, \
             patch('dolly.gui.dialogs.show_error') as dialog:
            self.app._report_operation_error('Starting replay editor', error)
        self.app._load_replay.assert_not_called()
        ask.assert_not_called(); dialog.assert_not_called()
        self.app.startup_progress.set.assert_called_once_with(str(error))
        self.assertIn('Check startup again', self.status.set.call_args[0][0])

    def test_check_startup_again_submits_same_replay_and_fresh_cancellation(self):
        self.app.demo_path = SimpleNamespace(get=lambda: 'selected.dem')
        self.app.controller = SimpleNamespace(resume_startup=Mock())
        self.app._submit = Mock(return_value=True)
        self.app._editing_started = Mock()
        self.app.startup_bar = Mock()
        self.app._resume_startup()
        label, operation, callback = self.app._submit.call_args.args
        self.assertEqual(label, 'Checking startup again')
        self.assertIs(callback, self.app._editing_started)
        self.assertFalse(self.app.startup_cancel.is_set())
        operation()
        self.app.controller.resume_startup.assert_called_once_with(
            'selected.dem', cancel_event=self.app.startup_cancel)

    def test_declining_the_offer_leaves_the_replay_unloaded(self):
        with patch("dolly.gui.messagebox.askyesno", return_value=False) as ask:
            self.app._report_operation_error("Starting replay editor", self.error())
        ask.assert_called_once()
        self.app._load_replay.assert_not_called()

    def test_other_startup_errors_keep_the_standard_dialog(self):
        failure = RuntimeError("The game console connection failed.")
        with patch("dolly.gui.dialogs.show_error") as dialog:
            self.app._report_operation_error("Starting replay editor", failure)
        dialog.assert_called_once()
        self.assertEqual(dialog.call_args[0][1], "Starting replay editor")
        self.assertIn("game console connection failed", dialog.call_args[0][2])
        self.app._load_replay.assert_not_called()

    def test_closed_window_shows_no_dialog_and_does_not_raise(self):
        self.app.closed = True
        failure = self.error()
        with patch("dolly.gui.dialogs.show_error") as dialog, \
             patch("dolly.gui.messagebox.askyesno") as ask:
            self.app._report_operation_error("Starting replay editor", failure)
        dialog.assert_not_called()
        ask.assert_not_called()
        self.app._load_replay.assert_not_called()


if __name__ == "__main__":
    unittest.main()
