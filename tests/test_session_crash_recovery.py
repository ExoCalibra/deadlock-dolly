import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace
from tests.test_native_flight_controller import configured_controller
from dolly.gui import DollyApp

class SessionCrashRecoveryTests(unittest.TestCase):
    def test_launch_clears_dead_camera_ownership_before_creating_next_session(self):
        c,_,_=configured_controller()
        old=c._session
        old.process.poll=lambda:1
        c._follow_mode_original=2
        c._follow_mode_session=old
        c._follow_transaction=SimpleNamespace(originals={'setting':1})
        c._native_active=c._native_manual=True
        fresh=SimpleNamespace(process=SimpleNamespace(poll=lambda:None),pid=5678,
                              session_dir=Path('next-session'),native=None)
        def launch(*args,**kwargs):
            self.assertIsNone(c._follow_mode_original)
            self.assertIsNone(c._follow_transaction)
            self.assertFalse(c._native_active)
            old.close.assert_called_once()
            return fresh
        with tempfile.TemporaryDirectory() as folder:
            replay=Path(folder)/'next.dem';replay.write_bytes(b'fixture')
            with patch('dolly.controller.launcher.launch',side_effect=launch):
                result=c._launch('unused-game',replay,'netcon',native=True)
        self.assertEqual(result['pid'],5678)
        self.assertIs(c._session,fresh)
        self.assertEqual(c.status()['startup_stage'],'waiting_hideout')

    def test_dead_session_discards_camera_journals_and_preserves_editor_data(self):
        c,console,bridge=configured_controller()
        c._session.process.poll=lambda:1
        c._native_active=c._native_manual=c._follow_active=True
        c._follow_mode_original=0
        c._follow_mode_session=object()
        monitor=Mock();c._follow_monitor=monitor
        c._follow_transaction=SimpleNamespace(originals={'setting':1})
        c._game_ui_restore={'citadel_spectator_mode':0}
        c._state.update(playing=True,paused_flight=True)
        c._recording_warmup={'project':'old-session'}
        self.assertTrue(c.recover_dead_session())
        monitor.close.assert_called_once()
        self.assertIsNone(c._follow_mode_original)
        self.assertIsNone(c._follow_transaction)
        self.assertIsNone(c._recording_warmup)
        self.assertFalse(c._native_active)
        self.assertFalse(c.status()['playing'])
        self.assertFalse(c.status()['native_editor_active'])
        self.assertFalse(c._game_ui_restore)
        self.assertFalse(c.recover_dead_session(),'Cleanup must be idempotent')
        c._session.close.assert_called_once()

    def test_live_session_is_never_discarded(self):
        c,_,_=configured_controller()
        c._native_active=True
        self.assertFalse(c.recover_dead_session())
        self.assertTrue(c._native_active)
        c._session.close.assert_not_called()

    def test_crashed_status_does_not_leave_playback_or_native_editor_active(self):
        c,_,_=configured_controller()
        c._session.process.poll=lambda:1
        c._native_active=c._native_manual=c._follow_active=True
        c._state.update(playing=True,paused_flight=True,paused_camera=True)
        state=c.status()
        self.assertFalse(state['playing'])
        self.assertFalse(state['native_editor_active'])
        self.assertFalse(state['game_follow_active'])

    def test_gui_returns_minimized_launcher_and_queues_cleanup_once(self):
        app=DollyApp.__new__(DollyApp)
        session=object();app.controller=SimpleNamespace(_session=session,recover_dead_session=Mock())
        app.root=SimpleNamespace(state=lambda:'iconic',deiconify=Mock())
        app.closed=False;app.busy=False;app.playing=True
        app._bone_picker_context=object();app.preview_attach=True;app.native_editor_active=True
        app.startup_cancel=None;app._submit=Mock(return_value=True)
        app._handle_game_exit({'game_running':True})
        app._handle_game_exit({'game_running':False})
        app._handle_game_exit({'game_running':False})
        app.root.deiconify.assert_called_once()
        self.assertIsNone(app._bone_picker_context)
        self.assertFalse(app.preview_attach)
        self.assertFalse(app.native_editor_active)
        app._submit.assert_called_once()

if __name__=='__main__':unittest.main()
