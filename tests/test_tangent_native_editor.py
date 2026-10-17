"""Native slope messages cross the normal mutation/history boundary offline."""
import copy
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from dolly import editor_wire as wire
from dolly.editor_dispatch import dispatch
from dolly.native_path import compile_project
from dolly.path import AttachKey, Project
from dolly.shot_history import ShotHistory
from test_tangent_editor import application


class NativeTangentEditorTests(unittest.TestCase):
    def setUp(self):
        self.app = application()
        self.bridge = Mock()
        self.bridge.editor_status.return_value = dict(enabled=True, ready=True, focused=True,
                                                     paused=True, input_mode="panel")
        self.publish = Mock()

    def event(self, *, index=1, axis=0, mode=3, incoming=-12, outgoing=55,
              revision=None, anchor=2, session=None, pose=None, encoded=None):
        history = self.app.shot_history
        revision = history.revision if revision is None else revision
        session = history.session_id if session is None else session
        return dict(action="set_camera_position_tangents",
                    value=index * 12 + axis * 4 + mode if encoded is None else encoded,
                    pose=(revision, incoming, outgoing, anchor, session & 0xFFFFFFFF,
                          session >> 32, 0) if pose is None else pose)

    def edit(self, **kwargs):
        return dispatch(self.app, self.event(**kwargs), self.bridge, publish=self.publish)

    def test_wire_action_atomically_authors_one_axis_with_save_and_no_engine_calls(self):
        event = self.event(axis=2)
        data = bytearray(wire.STATUS_BYTES)
        wire.HEADER.pack_into(data, 0, wire.STATUS_MAGIC, 2, wire.EDITOR_ABI, 2,
                             23, 1, 3, 1, 0, 320, *([0] * 7), b"Ready", 0, 42, 0, 17)
        # The numeric ID is deliberately independent of the production action tuple.
        wire.EVENT.pack_into(data, wire.HEADER.size, 1, 114, event["value"], *event["pose"], 42, 1)
        decoded = wire.unpack_status(data)["events"][0]
        self.assertEqual(decoded["action"], "set_camera_position_tangents")
        before = copy.deepcopy(self.app.project)
        self.assertTrue(dispatch(self.app, decoded, self.bridge, publish=self.publish))
        expected = copy.deepcopy(before)
        expected.set_camera_tangent(1, "z", "broken", incoming=-12, outgoing=55)
        self.assertEqual(self.app.project, expected)
        self.assertEqual(self.app.controller.mock_calls, [])
        self.app._set_time.assert_not_called()
        self.publish.assert_called_once()
        with TemporaryDirectory() as directory:
            saved = Path(directory) / "native-handles.json"
            self.app.project.save(saved)
            restored = Project.load(saved)
        self.assertEqual(restored, expected)
        self.assertEqual(compile_project(restored), compile_project(expected))

    def test_completed_gestures_are_unmerged_and_auto_reset_only_clears_one_axis(self):
        before = copy.deepcopy(self.app.project)
        with patch("dolly.shot_history.monotonic", side_effect=[10, 10.01, 10.02]):
            self.edit(axis=0)
            first = copy.deepcopy(self.app.project)
            self.edit(axis=1, mode=1, incoming=0, outgoing=0)
            second = copy.deepcopy(self.app.project)
            self.edit(axis=0, mode=0, incoming=0, outgoing=0)
        self.assertEqual(set(self.app.project.keyframes[1].tangents), {"y"})
        self.assertEqual(self.app.shot_history.move().project, second)
        self.assertEqual(self.app.shot_history.move().project, first)
        self.assertEqual(self.app.shot_history.move().project, before)
        self.assertFalse(self.app.shot_history.can_undo)

    def test_noop_preserves_clean_state_revision_and_redo(self):
        self.edit()
        self.app.project = self.app.shot_history.move().project
        revision = self.app.shot_history.revision
        self.publish.reset_mock()
        self.app._refresh_keys.reset_mock()
        self.edit(mode=0, incoming=0, outgoing=0)
        self.assertEqual(self.app.shot_history.revision, revision)
        self.assertTrue(self.app.shot_history.can_redo)
        self.assertFalse(self.app.shot_history.is_dirty(self.app.project))
        self.publish.assert_not_called()
        self.app._refresh_keys.assert_not_called()

    def test_stale_identity_and_malformed_pairs_never_mutate_or_discard_redo(self):
        self.edit()
        self.app.project = self.app.shot_history.move().project
        before = copy.deepcopy(self.app.project)
        history = self.app.shot_history
        session = history.session_id
        for kwargs in ({"incoming": math.nan}, {"outgoing": math.inf}, {"incoming": True},
                       {"mode": 0}, {"mode": 1}, {"mode": 2}, {"anchor": 3},
                       {"revision": history.revision + 1}, {"session": 0}, {"session": session ^ 1},
                       {"encoded": math.nan}, {"encoded": True}, {"encoded": -.1},
                       {"encoded": 12.5}, {"encoded": 4096 * 12}, {"index": 3},
                       {"pose": "bad"}, {"pose": (1, 0, 0, 2, 1, 1, 1)},
                       {"pose": (history.revision, 0, 0, 2, .5, 0, 0)},
                       {"pose": (history.revision, 0, 0, 2, 1 << 32, 0, 0)}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.edit(**kwargs)
        self.assertEqual(self.app.project, before)
        self.assertTrue(history.can_redo)

    def test_matching_reopened_shot_cannot_reuse_an_old_session(self):
        event = self.event()
        self.app.shot_history = ShotHistory(self.app.project)
        with self.assertRaisesRegex(ValueError, "shot changed"):
            dispatch(self.app, event, self.bridge, publish=self.publish)
        self.assertFalse(self.app.shot_history.can_undo)

    def test_live_admission_selection_and_mode_are_rechecked_before_mutation(self):
        before = copy.deepcopy(self.app.project)
        original = dict(self.bridge.editor_status.return_value)
        for changes in ({"enabled": False}, {"ready": False}, {"focused": False},
                        {"paused": False}, {"input_mode": "game_ui"}):
            self.bridge.editor_status.return_value = dict(original, **changes)
            self.edit()
            self.assertEqual(self.app.project, before)
        self.bridge.editor_status.return_value = original
        for reason in ("recording", "playing", "preview_attach", "selection", "attached", "linear", "spline"):
            with self.subTest(reason=reason):
                self.setUp()
                if reason == "recording":
                    self.app.video_export.status = lambda: {"state": "recording"}
                elif reason in ("playing", "preview_attach"):
                    setattr(self.app, reason, True)
                elif reason == "selection":
                    self.app._selection_index.return_value = 0
                elif reason == "attached":
                    self.app.project.keyframes[1].source = "attach"
                    self.app.project.keyframes[1].attach = AttachKey(handle=3, model="hero.vmdl", point="bone", bone="head")
                else:
                    self.app.project.interpolation = reason
                before = copy.deepcopy(self.app.project)
                if reason in ("attached", "linear", "spline"):
                    with self.assertRaises(ValueError):
                        self.edit()
                else:
                    self.edit()
                self.assertEqual(self.app.project, before)
                self.assertFalse(self.app.shot_history.can_undo)
                self.publish.assert_not_called()

    def test_slope_range_is_validated_by_the_curve_not_by_world_coordinate_units(self):
        # A short segment can safely use a derivative larger than any authored
        # world coordinate. The same derivative over a long segment is unsafe.
        for key in self.app.project.keyframes:
            key.time *= 1e-6
        self.app.shot_history.reset(self.app.project)
        self.edit(mode=2, incoming=1e9, outgoing=1e9, anchor=2e-6)
        tangent = self.app.project.camera_tangent(1, "x")
        self.assertEqual((tangent.incoming, tangent.outgoing), (1e9, 1e9))
        self.setUp()
        before = copy.deepcopy(self.app.project)
        with self.assertRaisesRegex(ValueError, "position range"):
            self.edit(mode=2, incoming=1e9, outgoing=1e9)
        self.assertEqual(self.app.project, before)
        self.assertFalse(self.app.shot_history.can_undo)


if __name__ == "__main__":
    unittest.main()
