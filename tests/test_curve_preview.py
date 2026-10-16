"""Latest-only draft lifecycle crosses real optional mapping without authoring."""
import copy
import math
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from dolly import curve_preview as preview
from dolly import native_bridge as nb
from dolly import visualization_preview_wire as wire
from dolly.editor_dispatch import dispatch
from dolly.visualization_wire import HEADER as VIEWER_HEADER, KEY_METADATA
from test_tangent_editor import application
from test_visualization_transport import Memory


class CurvePreviewTests(unittest.TestCase):
    def setUp(self):
        self.app = application()
        self.maps = []
        def factory(name, size):
            memory = Memory(size)
            self.maps.append((name, memory))
            return memory
        self.bridge = nb.NativeBridge.create(mapping_factory=factory, token='b'*32, editor_pid=1001,
            clock=lambda: 0, sleep=lambda _: None, start_heartbeat=False)
        self.addCleanup(self.bridge.close)
        self.bridge.editor_status = Mock(return_value=dict(enabled=True, ready=True, paused=True,
            focused=False, flight_active=True, input_mode='unfocused'))
        self.now = 0.
        self.clock = patch('dolly.curve_preview.time.monotonic', side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.bridge.publish_visualization(self.app.project, revision=self.app.shot_history.revision,
            session_id=self.app.shot_history.session_id, selected_camera=1)
        self.original_maps = [bytes(memory) for _, memory in self.maps]
        preview.configure(self.app, self.bridge, active=True, selected=1)

    def gesture(self, channel='x'):
        return SimpleNamespace(project=self.app.project, snapshot=copy.deepcopy(self.app.project),
            context=(self.app.shot_history.session_id, self.app.shot_history.revision),
            index=1, channel=channel, time=2.)

    def candidate(self, value):
        candidate = copy.deepcopy(self.app.project)
        candidate.keyframes[1].x = value
        return candidate

    def envelope(self):
        memory = self.maps[-1][1]
        return wire.HEADER.unpack_from(memory)

    def x(self):
        memory = self.maps[-1][1]
        inner = wire.HEADER_BYTES
        header = VIEWER_HEADER.unpack_from(memory, inner)
        return KEY_METADATA.unpack_from(memory, inner+64+header[5]*8+KEY_METADATA.size)[0]

    def native_event(self, *, action='preview_camera_curve_value', token=17, value=125., tangent=False):
        history = self.app.shot_history
        session = history.session_id
        return dict(action=action, value=15 if tangent else 1,
            pose=(history.revision, -12 if tangent else 0, 55 if tangent else value,
                  2., session & 0xFFFFFFFF, session >> 32, token))

    def assert_unmodified(self, original, revision):
        self.assertEqual(self.app.project, original)
        self.assertEqual(self.app.shot_history.revision, revision)
        self.assertFalse(self.app.dirty)
        self.assertFalse(self.app.shot_history.can_undo)
        self.assertEqual([bytes(memory) for _, memory in self.maps[:2]], self.original_maps)
        self.assertEqual(self.app.controller.mock_calls, [])
        self.app._set_time.assert_not_called()

    def test_latest_candidate_cadence_and_unchanged_heartbeat_preserve_camera_and_history(self):
        original, revision = copy.deepcopy(self.app.project), self.app.shot_history.revision
        gesture = self.gesture()
        with patch('dolly.curve_preview.build_visualization', wraps=preview.build_visualization) as compiler:
            self.assertTrue(preview.offer_desktop(self.app, self.candidate(120), gesture))
            self.assertEqual(self.x(), 120)
            first_sequence = self.envelope()[1]
            self.now = .05
            for value in range(121, 130):
                preview.offer_desktop(self.app, self.candidate(value), gesture)
            self.assertEqual(self.envelope()[1], first_sequence)
            self.now = .101
            preview.configure(self.app, self.bridge, active=True, selected=1)
            self.assertEqual(self.x(), 129)
            packet = bytes(self.maps[-1][1][64:64+self.envelope()[11]])
            self.now = .202
            preview.configure(self.app, self.bridge, active=True, selected=1)
            self.assertEqual(bytes(self.maps[-1][1][64:64+self.envelope()[11]]), packet)
            self.assertEqual(compiler.call_count, 2)
        self.assert_unmodified(original, revision)

    def test_invalid_clear_can_recover_but_terminal_clear_rejects_late_same_gesture(self):
        gesture = self.gesture()
        preview.offer_desktop(self.app, self.candidate(120), gesture)
        token = self.envelope()[5]
        preview.offer_desktop(self.app, None, gesture)
        self.assertEqual(self.envelope()[3:7], (0,0,0,0))
        self.now = .101
        preview.offer_desktop(self.app, self.candidate(130), gesture)
        self.assertEqual(self.envelope()[5], token)
        self.assertEqual(self.x(), 130)
        preview.offer_desktop(self.app, None, gesture)
        preview.offer_desktop(self.app, None, None)
        self.assertEqual(self.envelope()[3:6], (0,1,token))
        self.now = .202
        self.assertFalse(preview.offer_desktop(self.app, self.candidate(140), gesture))
        self.assertEqual(self.envelope()[3], 0)

    def test_stale_identity_selection_recording_owner_and_invalid_candidate_clear_only_preview(self):
        for reason in ('revision','session','selection','inplace','recording','playing','busy','closed',
                       'console','game_ui','reshade','manual','ready','paused','enabled','attach','object_picker'):
            with self.subTest(reason=reason):
                self.setUp()
                preview.offer_desktop(self.app, self.candidate(120), self.gesture())
                if reason == 'revision': self.app.shot_history.revision += 1
                elif reason == 'session': self.app.shot_history.session_id ^= 1
                elif reason == 'selection': self.app._selection_index.return_value = 0
                elif reason == 'inplace': self.app.project.keyframes[0].y += 1
                elif reason == 'recording': self.app.video_export.status = lambda: {'state':'recording'}
                elif reason in ('playing','busy','closed'): setattr(self.app, reason, True)
                elif reason in ('console','game_ui','reshade'): self.bridge.editor_status.return_value['input_mode'] = reason
                elif reason == 'manual': self.bridge.editor_status.return_value['flight_active'] = False
                elif reason in ('ready','paused','enabled'): self.bridge.editor_status.return_value[reason] = False
                elif reason == 'object_picker': self.app.object_picker_open = True
                else: self.app.preview_attach = True
                self.now = .101
                preview.configure(self.app, self.bridge, active=True, selected=1)
                self.assertEqual(self.envelope()[3], 0)
                self.assertFalse(self.app.dirty)
        self.setUp()
        gesture = self.gesture()
        preview.offer_desktop(self.app, self.candidate(120), gesture)
        invalid = self.candidate(math.nan)
        self.now = .101
        with self.assertLogs('dolly.curve_preview', level='WARNING'):
            preview.offer_desktop(self.app, invalid, gesture)
        self.assertEqual(self.envelope()[3:7], (0,0,0,0))
        self.assertFalse(self.app.dirty)

    def test_native_tangent_drafts_expire_and_terminal_tokens_cannot_revive(self):
        self.bridge.editor_status.return_value.update(focused=True, input_mode='panel')
        original, revision = copy.deepcopy(self.app.project), self.app.shot_history.revision
        event = self.native_event(action='preview_camera_position_tangents', tangent=True)
        self.assertTrue(dispatch(self.app, event, self.bridge, publish=Mock()))
        self.assertEqual(self.envelope()[4:6], (2,17))
        self.now = .5
        preview.configure(self.app, self.bridge, active=True, selected=1)
        self.assertEqual(self.envelope()[3], 1)
        self.now = .751
        preview.configure(self.app, self.bridge, active=True, selected=1)
        self.assertEqual(self.envelope()[3], 0)
        self.assertFalse(preview.offer_native(self.app, event, self.bridge, tangent=True))
        event = self.native_event(token=18)
        preview.offer_native(self.app, event, self.bridge)
        clear = self.native_event(action='clear_camera_curve_preview', token=18, value=0)
        self.app.busy = True
        self.bridge.editor_status.return_value.update(focused=False,input_mode='game_ui')
        self.assertTrue(dispatch(self.app, clear, self.bridge, publish=Mock()))
        self.assertEqual(self.envelope()[3:6], (0,2,18))
        self.app.busy = False
        self.bridge.editor_status.return_value.update(focused=True,input_mode='panel')
        self.assertFalse(preview.offer_native(self.app, event, self.bridge))
        self.assertFalse(preview.offer_native(self.app, self.native_event(token=17), self.bridge))
        self.assert_unmodified(original, revision)

    def test_native_preview_requests_are_non_authoring_and_final_release_is_one_undo(self):
        self.bridge.editor_status.return_value.update(focused=True, input_mode='panel')
        original = copy.deepcopy(self.app.project)
        event = self.native_event()
        for value in (110.,120.,130.):
            self.now += .101
            event = self.native_event(value=value)
            dispatch(self.app, event, self.bridge, publish=Mock())
        self.assertFalse(self.app.shot_history.can_undo)
        final = dict(action='set_camera_curve_value', value=1, pose=event['pose'][:6]+(0,))
        dispatch(self.app, final, self.bridge, publish=Mock())
        self.assertEqual(self.app.project.keyframes[1].x, 130)
        self.assertEqual(self.envelope()[3], 0)
        self.assertEqual(self.app.shot_history.move().project, original)
        self.assertFalse(self.app.shot_history.can_undo)
        self.assertFalse(preview.offer_native(self.app, event, self.bridge))

    def test_native_invalid_shape_can_recover_and_terminal_clear_after_hidden_draft_retires_token(self):
        self.bridge.editor_status.return_value.update(focused=True, input_mode='panel')
        event = self.native_event(action='preview_camera_position_tangents', tangent=True)
        self.assertTrue(preview.offer_native(self.app, event, self.bridge, tangent=True))
        invalid = dict(event, pose=(event['pose'][0], 1e9, 1e9, *event['pose'][3:]))
        self.now = .101
        self.assertFalse(preview.offer_native(self.app, invalid, self.bridge, tangent=True))
        self.assertEqual(self.envelope()[3:7], (0,0,0,0))
        self.now = .202
        self.assertTrue(preview.offer_native(self.app, event, self.bridge, tangent=True))
        self.assertEqual(self.envelope()[3:6], (1,2,17))
        self.now = .303
        preview.offer_native(self.app, invalid, self.bridge, tangent=True)
        self.assertEqual(self.envelope()[3:7], (0,0,0,0))
        clear = self.native_event(action='clear_camera_curve_preview', token=17, value=0)
        self.assertTrue(preview.clear_native(self.app, clear))
        self.assertEqual(self.envelope()[3:6], (0,2,17))
        self.assertFalse(preview.offer_native(self.app, event, self.bridge, tangent=True))

    def test_native_token_counter_wrap_rejects_old_requests(self):
        self.bridge.editor_status.return_value.update(focused=True, input_mode='panel')
        for token in (0xFFFFFFFE, 0xFFFFFFFF, 1):
            self.now += .101
            self.assertTrue(preview.offer_native(self.app, self.native_event(token=token), self.bridge))
            self.assertEqual(self.envelope()[5], token)
        self.assertFalse(preview.offer_native(self.app, self.native_event(token=0xFFFFFFFF), self.bridge))
        self.assertEqual(self.envelope()[5], 1)

    def test_refused_late_native_request_cannot_cancel_current_desktop_gesture(self):
        gesture = self.gesture()
        preview.offer_desktop(self.app, self.candidate(120), gesture)
        desktop_token = self.envelope()[5]
        # This older queued native request arrives after focus moved to Dolly.
        # Its native admission fails, while the desktop gesture remains valid.
        self.assertFalse(preview.offer_native(self.app, self.native_event(), self.bridge))
        self.assertEqual(self.envelope()[3:6], (1,1,desktop_token))
        self.now = .101
        self.assertTrue(preview.offer_desktop(self.app, self.candidate(130), gesture))
        self.assertEqual(self.envelope()[3:6], (1,1,desktop_token))
        self.assertEqual(self.x(), 130)
        # Even a malformed candidate from another admitted source must not
        # erase the currently rendered desktop candidate.
        self.bridge.editor_status.return_value.update(focused=True,input_mode='panel')
        invalid = self.native_event(action='preview_camera_position_tangents', token=18, tangent=True)
        invalid['pose'] = (invalid['pose'][0], 1e9, 1e9, *invalid['pose'][3:])
        self.assertFalse(preview.offer_native(self.app, invalid, self.bridge, tangent=True))
        self.assertEqual(self.envelope()[3:6], (1,1,desktop_token))
        # The symmetric late desktop callback cannot retire a newer native
        # source either, and an obsolete temporary-clear callback is ignored.
        self.now = .202
        self.assertTrue(preview.offer_native(self.app, self.native_event(token=19), self.bridge))
        self.assertFalse(preview.offer_desktop(self.app, self.candidate(140), gesture))
        self.assertFalse(preview.offer_desktop(self.app, None, gesture))
        self.assertEqual(self.envelope()[3:6], (1,2,19))


if __name__ == '__main__':
    unittest.main()
