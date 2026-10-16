"""Saved handles cross the real desktop/history/publication boundaries."""
import copy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from dolly.editor_publication import _configure_visualization
from dolly.gui import DollyApp
from dolly.native_path import compile_project
from dolly.path import AttachKey, Keyframe, Project
from dolly.shot_history import ShotHistory
from dolly.ui import shot_commands


def application():
    app = DollyApp.__new__(DollyApp)
    app.project = Project(keyframes=[Keyframe(0, 0, 0, 0, 0, 0, 0),
                                    Keyframe(2, 100, 20, 30, 0, 0, 0),
                                    Keyframe(5, 140, -10, 80, 0, 0, 0)])
    app.shot_history = ShotHistory(app.project)
    app.busy = app.playing = app.preview_attach = False
    app.dirty = False
    app.video_export = SimpleNamespace(status=lambda: {'state': 'idle'})
    app.status_text = Mock()
    app.controller = Mock()
    app.camera_tree = object()
    app._selection_index = Mock(return_value=1)
    app._title = Mock()
    app._refresh_keys = Mock()
    app._refresh_curve = Mock()
    app._set_time = Mock()
    app._guard = lambda _title, operation: operation()
    return app


class TangentEditorTests(unittest.TestCase):
    def test_commit_save_reopen_and_each_gesture_has_one_undo_without_game_calls(self):
        app = application()
        before = copy.deepcopy(app.project)
        self.assertTrue(app._change_camera_tangent(1, 'x', 'broken', -12, 55))
        first = copy.deepcopy(app.project)
        self.assertEqual([k.time for k in app.project.keyframes], [0, 2, 5])
        self.assertEqual([(k.x, k.y, k.z) for k in app.project.keyframes],
                         [(k.x, k.y, k.z) for k in before.keyframes])
        self.assertTrue(app._change_camera_tangent(1, 'y', 'flat'))
        final = copy.deepcopy(app.project)
        self.assertEqual(app.shot_history.move().project, first)
        self.assertEqual(app.shot_history.move().project, before)
        self.assertFalse(app.shot_history.can_undo)
        self.assertEqual(app.shot_history.move(True).project, first)
        self.assertEqual(app.shot_history.move(True).project, final)
        with TemporaryDirectory() as directory:
            path = Path(directory)/'handles.json'
            app.project.save(path)
            restored = Project.load(path)
        self.assertEqual(restored, final)
        self.assertEqual(compile_project(restored), compile_project(final))
        app._set_time.assert_not_called()
        self.assertEqual(app.controller.mock_calls, [])

    def test_noop_keeps_redo_and_reset_auto_is_an_undoable_change(self):
        app = application()
        self.assertFalse(app._change_camera_tangent(1, 'x', 'auto'))
        self.assertFalse(app.shot_history.can_undo)
        self.assertTrue(app._change_camera_tangent(1, 'x', 'linked', 20, 20))
        linked = copy.deepcopy(app.project)
        self.assertTrue(app._change_camera_tangent(1, 'x', 'auto'))
        self.assertEqual(app.project.keyframes[1].tangents, {})
        app.project = app.shot_history.move().project
        self.assertEqual(app.project, linked)
        revision = app.shot_history.revision
        app._refresh_keys.reset_mock()
        self.assertFalse(app._change_camera_tangent(1, 'x', 'linked', 20, 20))
        self.assertEqual(app.shot_history.revision, revision)
        self.assertTrue(app.shot_history.can_redo)
        app._refresh_keys.assert_not_called()

    def test_refused_busy_recording_attached_and_stale_selection_never_mutate(self):
        for reason in ('busy', 'playing', 'recording', 'attached', 'selection', 'linear', 'spline'):
            with self.subTest(reason=reason):
                app = application()
                if reason in ('busy', 'playing'):
                    setattr(app, reason, True)
                elif reason == 'recording':
                    app.video_export.status = lambda: {'state': 'recording'}
                elif reason == 'attached':
                    app.project.keyframes[1].source = 'attach'
                    app.project.keyframes[1].attach = AttachKey(handle=3, model='hero.vmdl', point='bone', bone='head')
                elif reason == 'selection':
                    app._selection_index.return_value = 0
                else:
                    app.project.interpolation = reason
                before = copy.deepcopy(app.project)
                if reason in ('busy', 'playing', 'recording'):
                    self.assertFalse(app._change_camera_tangent(1, 'x', 'flat'))
                else:
                    with self.assertRaises(ValueError):
                        app._change_camera_tangent(1, 'x', 'flat')
                self.assertEqual(app.project, before)
                self.assertFalse(app.shot_history.can_undo)
                app._refresh_keys.assert_not_called()
                self.assertEqual(app.controller.mock_calls, [])

    def test_update_view_preserves_saved_handles_without_aliasing(self):
        app = application()
        app.project.set_camera_tangent(1, 'x', 'broken', incoming=-12, outgoing=55)
        previous = app.project.keyframes[1]
        app._read_key = lambda: Keyframe(2.5, 130, 50, 80, 10, 20, 30)
        app._update_key()
        updated = app.project.keyframes[1]
        self.assertEqual(updated.tangents, previous.tangents)
        self.assertIsNot(updated.tangents, previous.tangents)
        self.assertEqual((updated.time, updated.x), (2.5, 130))

    def test_recapture_preserves_handle_intent_but_new_camera_starts_auto(self):
        app = application()
        app.project.set_camera_tangent(1, 'z', 'flat')
        old = app.project.keyframes[1]
        replacement = Keyframe(2, 12, 34, 56, 0, 0, 0)
        shot_commands.finish_capture(app.project, 'replace', replacement, None, selected=1)
        self.assertEqual(app.project.keyframes[1].tangents, old.tangents)
        self.assertIsNot(app.project.keyframes[1].tangents, old.tangents)
        shot_commands.finish_capture(app.project, 'add', Keyframe(7, 0, 0, 0, 0, 0, 0), None)
        self.assertEqual(app.project.keyframes[-1].tangents, {})

    def test_native_guides_republish_for_in_place_handle_change_without_pose_change(self):
        app = application()
        bridge = Mock()
        first = compile_project(app.project)
        _configure_visualization(app, bridge, True, 1)
        _configure_visualization(app, bridge, True, 1)
        self.assertEqual(bridge.publish_visualization.call_count, 1)
        # Deliberately retain the same Project and history revision to exercise
        # the publication cache's independent in-place-data contract.
        app.project.set_camera_tangent(1, 'x', 'flat')
        _configure_visualization(app, bridge, True, 1)
        self.assertEqual(bridge.publish_visualization.call_count, 2)
        self.assertNotEqual(compile_project(app.project), first)
        bridge.publish_visualization.assert_called_with(
            app.project, enabled=True, selected_camera=1,
            revision=app.shot_history.revision, session_id=app.shot_history.session_id)
