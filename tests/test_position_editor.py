"""XYZ transactions cross the real application/history boundary without a game."""
import copy
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from dolly.editor_dispatch import dispatch
from dolly.editor_publication import _configure_visualization, visualization_session
from dolly.gui import DollyApp
from dolly.native_path import compile_project
from dolly.path import AttachKey, Keyframe, Project
from dolly.shot_history import ShotHistory


class PositionEditorTests(unittest.TestCase):
    def setUp(self):
        self.app = DollyApp.__new__(DollyApp)
        self.app.project = Project(keyframes=[Keyframe(0, 10, 20, 30, 4, 5, 6),
                                               Keyframe(3, 50, 60, 70, 8, 9, 10)])
        self.app.shot_history = ShotHistory(self.app.project)
        self.app.busy = self.app.playing = self.app.preview_attach = False
        self.app.status_text = Mock()
        self.app.controller = Mock()
        self.app.video_export = SimpleNamespace(status=lambda: {"state": "idle"})
        self.app.camera_tree = object()
        self.app._selection_index = lambda _: 1
        self.app._title = Mock()
        self.app._refresh_keys = Mock()
        self.app._set_time = Mock()
        self.bridge = Mock()
        self.bridge.editor_status.return_value = dict(enabled=True, ready=True, focused=True,
                                                     paused=True, input_mode="panel")
        self.publish = Mock()

    def edit(self, value=100, *, index=1, axis=0, revision=None, anchor=3, pose=None):
        if revision is None:
            revision = self.app.shot_history.revision
        event = dict(action="set_camera_position", value=index,
                     pose=pose if pose is not None else (revision, axis, value, anchor, 0, 0, 0))
        return dispatch(self.app, event, self.bridge, publish=self.publish)

    def test_edit_changes_one_existing_coordinate_without_timing_or_engine_calls(self):
        original = copy.deepcopy(self.app.project)
        self.assertTrue(self.edit(123.456, axis=1))
        expected = copy.deepcopy(original)
        expected.keyframes[1].y = 123.456
        self.assertEqual(self.app.project, expected)
        self.app.controller.assert_not_called()
        self.assertEqual(self.app.controller.mock_calls, [])
        self.app._set_time.assert_not_called()
        self.publish.assert_called_once()
        self.app._refresh_keys.assert_called_once_with(3)

    def test_each_completed_gesture_has_its_own_undo_even_when_immediate(self):
        original = copy.deepcopy(self.app.project)
        with patch("dolly.shot_history.monotonic", side_effect=[10, 10.01]):
            self.edit(100)
            first = copy.deepcopy(self.app.project)
            self.edit(200)
        history = self.app.shot_history
        self.assertEqual(history.move().project, first)
        self.assertEqual(history.move().project, original)
        self.assertFalse(history.can_undo)
        self.assertEqual(history.move(True).project, first)
        self.assertEqual(history.move(True).project, self.app.project)

    def test_noop_does_not_dirty_invalidate_revision_or_destroy_redo(self):
        self.edit(100)
        self.app.project = self.app.shot_history.move().project
        self.publish.reset_mock()
        self.app._refresh_keys.reset_mock()
        revision = self.app.shot_history.revision
        self.edit(50)
        self.assertEqual(self.app.shot_history.revision, revision)
        self.assertTrue(self.app.shot_history.can_redo)
        self.publish.assert_not_called()
        self.app._refresh_keys.assert_not_called()

    def test_position_edit_save_reopen_keeps_format_and_compiled_motion(self):
        version = self.app.project.to_dict()["version"]
        self.edit(-250.125, axis=2)
        with tempfile.TemporaryDirectory() as directory:
            saved = Path(directory) / "position.json"
            self.app.project.save(saved)
            restored = Project.load(saved)
        self.assertEqual(restored.to_dict(), self.app.project.to_dict())
        self.assertEqual(restored.to_dict()["version"], version)
        self.assertEqual(compile_project(restored), compile_project(self.app.project))
        for time in (0, .375, 1.5, 2.99, 3):
            self.assertEqual(restored.evaluate(time), self.app.project.evaluate(time))

    def test_changed_revision_or_anchor_cannot_edit_a_different_camera(self):
        original = copy.deepcopy(self.app.project)
        for kwargs in ({"revision": self.app.shot_history.revision + 1}, {"anchor": 2}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.edit(**kwargs)
        self.assertEqual(self.app.project, original)
        self.publish.assert_not_called()

    def test_malformed_position_events_fail_without_mutating_the_shot(self):
        original = copy.deepcopy(self.app.project)
        for kwargs in ({"value": math.nan}, {"value": math.inf}, {"value": 1e8 + 1},
                       {"value": True}, {"index": -1}, {"index": 2}, {"index": True},
                       {"axis": .5}, {"axis": 3}, {"axis": True}, {"pose": (1, 2)},
                       {"pose": "bad"}, {"pose": (1, 0, 100, 3, 1, 0, 0)}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.edit(**kwargs)
        self.assertEqual(self.app.project, original)
        self.publish.assert_not_called()

    def test_attached_key_has_no_misleading_world_position_edit(self):
        key = self.app.project.keyframes[1]
        key.source = "attach"
        key.attach = AttachKey(handle=3, model="hero.vmdl", point="bone", bone="head")
        original = copy.deepcopy(self.app.project)
        with self.assertRaisesRegex(ValueError, "attachment offsets"):
            self.edit()
        self.assertEqual(self.app.project, original)
        self.publish.assert_not_called()

    def test_current_native_focus_pause_and_owner_are_rechecked_before_commit(self):
        original = copy.deepcopy(self.app.project)
        for change in ({"focused": False}, {"paused": False}, {"enabled": False},
                       {"ready": False}, {"input_mode": "game_ui"}):
            with self.subTest(change=change):
                self.bridge.editor_status.return_value = dict(enabled=True, ready=True,
                    focused=True, paused=True, input_mode="panel", **{})
                self.bridge.editor_status.return_value.update(change)
                self.assertTrue(self.edit())  # A cancelled event is consumed once.
                self.assertEqual(self.app.project, original)
        self.publish.assert_not_called()

    def test_recording_and_attach_preview_admission_preserves_the_shot(self):
        original = copy.deepcopy(self.app.project)
        self.app.video_export = SimpleNamespace(status=lambda: {"state": "recording"})
        self.edit()
        self.app.video_export = SimpleNamespace(status=lambda: {"state": "idle"})
        self.app.preview_attach = True
        self.edit()
        self.assertEqual(self.app.project, original)
        self.publish.assert_not_called()

    def test_selection_change_cancels_an_already_queued_gesture(self):
        original = copy.deepcopy(self.app.project)
        self.app._selection_index = lambda _: 0
        self.assertTrue(self.edit())
        self.assertEqual(self.app.project, original)
        self.publish.assert_not_called()

    def test_no_tree_selection_matches_published_native_camera_zero(self):
        self.app._selection_index = lambda _: None
        self.assertTrue(self.edit(123, index=0, anchor=0))
        self.assertEqual(self.app.project.keyframes[0].x, 123)
        self.publish.assert_called_once()

    def test_new_history_revision_republishes_even_when_only_curve_metadata_changed(self):
        self.app.project.keyframes[0].curve_yaw = 12
        _configure_visualization(self.app, self.bridge, True, 0)
        first = self.app.shot_history.revision
        self.bridge.publish_visualization.assert_called_once_with(self.app.project,
            enabled=True, selected_camera=0, revision=first, session_id=self.app.shot_history.session_id)
        self.app.project.keyframes[0].curve_yaw = 18
        self.app.shot_history.record(self.app.project)
        _configure_visualization(self.app, self.bridge, True, 0)
        self.assertEqual(self.bridge.publish_visualization.call_count, 2)
        self.assertEqual(self.bridge.publish_visualization.call_args.kwargs["revision"], self.app.shot_history.revision)


class UnifiedCurveEditorTests(unittest.TestCase):
    setUp = PositionEditorTests.setUp

    def edit(self, value=100, *, index=1, channel=0, revision=None, anchor=3,
             session=None, pose=None, action="set_camera_curve_value"):
        if revision is None:
            revision = self.app.shot_history.revision
        if session is None:
            session = self.app.shot_history.session_id
        event = dict(action=action, value=index, pose=pose if pose is not None else
                     (revision, channel, value, anchor, session & 0xFFFFFFFF, session >> 32, 0))
        return dispatch(self.app, event, self.bridge, publish=self.publish)

    def test_all_seven_channels_edit_only_their_authored_field(self):
        fields = ("x", "y", "z", "curve_pitch", "curve_yaw", "curve_roll", "aspect_ratio")
        for channel, field in enumerate(fields):
            with self.subTest(channel=channel):
                self.setUp()
                self.app.project.keyframes[1].lens_scale = .875
                before = copy.deepcopy(self.app.project)
                self.edit(2.25 if channel == 6 else 125.125, channel=channel)
                expected = copy.deepcopy(before)
                setattr(expected.keyframes[1], field, 2.25 if channel == 6 else 125.125)
                self.assertEqual(self.app.project, expected)
                self.assertEqual(self.app.controller.mock_calls, [])
                self.app._set_time.assert_not_called()
                self.publish.assert_called_once()

    def test_captured_rotations_survive_override_and_shortest_full_turn_authorship(self):
        for mode in ("shortest", "unwrapped"):
            with self.subTest(mode=mode):
                self.setUp()
                self.app.project.rotation_mode = mode
                self.app.project.keyframes[0].yaw = 359
                self.app.project.keyframes[1].yaw = 1
                self.edit(721, channel=4)
                key = self.app.project.keyframes[1]
                self.assertEqual((key.yaw, key.curve_yaw), (1, 721))
                expected = 1 if mode == "shortest" else 721
                self.assertEqual(self.app.project.evaluate(3)["yaw"], expected)
                self.assertTrue(compile_project(self.app.project))

    def test_legacy_huge_authored_angle_is_preserved_read_only_in_game(self):
        self.app.project.keyframes[1].curve_yaw = 3.6e12
        before = copy.deepcopy(self.app.project)
        with self.assertRaisesRegex(ValueError, "outside.*range"):
            self.edit(0, channel=4)
        self.assertEqual(self.app.project, before)
        self.publish.assert_not_called()

    def test_numeric_noop_preserves_absent_override_and_redo(self):
        self.edit(120, channel=3)
        self.app.project = self.app.shot_history.move().project
        self.publish.reset_mock()
        revision = self.app.shot_history.revision
        self.edit(8, channel=3)
        self.assertIsNone(self.app.project.keyframes[1].curve_pitch)
        self.assertEqual(self.app.shot_history.revision, revision)
        self.assertTrue(self.app.shot_history.can_redo)
        self.publish.assert_not_called()

    def test_each_generic_gesture_is_a_single_independent_undo(self):
        before = copy.deepcopy(self.app.project)
        session = self.app.shot_history.session_id
        with patch("dolly.shot_history.monotonic", side_effect=[10, 10.01]):
            self.edit(14, channel=5)
            first = copy.deepcopy(self.app.project)
            self.edit(2.39, channel=6)
        final = copy.deepcopy(self.app.project)
        self.assertEqual(self.app.shot_history.move().project, first)
        self.assertEqual(self.app.shot_history.move().project, before)
        self.assertEqual(self.app.shot_history.move(True).project, first)
        self.assertEqual(self.app.shot_history.move(True).project, final)
        self.assertEqual(self.app.shot_history.session_id, session)

    def test_new_shot_with_matching_revision_and_times_rejects_old_event(self):
        old_session = self.app.shot_history.session_id
        self.app.project = copy.deepcopy(self.app.project)
        self.app.shot_history = ShotHistory(self.app.project)
        self.assertEqual(self.app.shot_history.revision, 1)
        with self.assertRaisesRegex(ValueError, "shot changed"):
            self.edit(session=old_session)
        self.publish.assert_not_called()

    def test_reset_renews_session_but_commit_history_and_save_retain_it(self):
        history = self.app.shot_history
        before = history.session_id
        self.edit(1.5, channel=6)
        self.assertEqual(history.session_id, before)
        history.mark_saved(self.app.project)
        self.assertEqual(history.session_id, before)
        history.reset(self.app.project)
        self.assertNotEqual(history.session_id, before)

    def test_malformed_stale_or_out_of_bounds_generic_events_never_mutate(self):
        original = copy.deepcopy(self.app.project)
        for change in ({"value": math.nan}, {"value": math.inf}, {"value": 1e8 + 1},
                       {"value": True}, {"index": 2}, {"index": -1}, {"index": True},
                       {"channel": .5}, {"channel": 7}, {"channel": True},
                       {"channel": 6, "value": .49}, {"channel": 6, "value": 4.01},
                       {"anchor": 2}, {"revision": 2}, {"session": 0},
                       {"pose": (1, 0, 10, 3, -1, 0, 0)},
                       {"pose": (1, 0, 10, 3, .5, 0, 0)},
                       {"pose": (1, 0, 10, 3, 0x100000000, 0, 0)},
                       {"pose": (1, 0, 10, 3, 0, 0, 1)}, {"pose": "bad"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.edit(**change)
        self.assertEqual(self.app.project, original)
        self.publish.assert_not_called()

    def test_all_groups_respect_attach_recording_focus_pause_and_selection(self):
        original = copy.deepcopy(self.app.project)
        for channel in (0, 3, 6):
            for state in ({"focused": False}, {"paused": False}, {"enabled": False},
                          {"ready": False}, {"input_mode": "game_ui"}):
                self.bridge.editor_status.return_value = dict(enabled=True, ready=True,
                    focused=True, paused=True, input_mode="panel")
                self.bridge.editor_status.return_value.update(state)
                self.edit(2, channel=channel)
                self.assertEqual(self.app.project, original)
        self.bridge.editor_status.return_value = dict(enabled=True, ready=True,
            focused=True, paused=True, input_mode="panel")
        self.app.video_export = SimpleNamespace(status=lambda: {"state": "starting"})
        self.edit(2, channel=6)
        self.assertEqual(self.app.project, original)
        self.app.video_export = SimpleNamespace(status=lambda: {"state": "idle"})
        self.app._selection_index = lambda _: 0
        self.edit(2, channel=6)
        self.assertEqual(self.app.project, original)
        self.app.project.keyframes[1].source = "attach"
        self.app.project.keyframes[1].attach = AttachKey(handle=3, model="hero.vmdl", point="bone", bone="head")
        for channel in (0, 3, 6):
            with self.assertRaisesRegex(ValueError, "attachment offsets"):
                self.edit(2, channel=channel)
        self.publish.assert_not_called()

    def test_full_shot_selection_updates_camera_page_without_engine_seek(self):
        self.app.project.keyframes = [Keyframe(i, 1, 2, 3, 4, 5, 6) for i in range(70)]
        self.app.shot_history.reset(self.app.project)
        self.app.camera_tree = Mock()
        self.app._select_key = Mock()
        self.edit(0, action="select_curve_camera", index=69, anchor=69)
        self.app.camera_tree.selection_set.assert_called_once_with("69")
        self.app.camera_tree.see.assert_called_once_with("69")
        self.assertEqual(self.app._native_camera_page, 64)
        self.assertEqual(self.app.controller.mock_calls, [])
        self.publish.assert_called_once()

    def test_save_reopen_keeps_all_generic_edits_lens_and_playback_format(self):
        self.app.project.keyframes[1].lens_scale = .875
        version = self.app.project.to_dict()["version"]
        for channel, value in ((0, -100.123), (3, 190), (4, 721), (5, -359), (6, 2.39)):
            self.edit(value, channel=channel)
        with tempfile.TemporaryDirectory() as directory:
            saved = Path(directory) / "curves.json"
            self.app.project.save(saved)
            restored = Project.load(saved)
        self.assertEqual(restored.to_dict(), self.app.project.to_dict())
        self.assertEqual(restored.to_dict()["version"], version)
        self.assertEqual(compile_project(restored), compile_project(self.app.project))
        self.assertEqual(restored.keyframes[1].lens_scale, .875)

    def test_publication_cache_tracks_overrides_source_and_calibrated_lens(self):
        _configure_visualization(self.app, self.bridge, True, 1)
        for field, value in (("curve_pitch", 12), ("curve_yaw", 18),
                             ("curve_roll", 24), ("lens_scale", .875), ("source", "attach")):
            before = self.bridge.publish_visualization.call_count
            setattr(self.app.project.keyframes[1], field, value)
            _configure_visualization(self.app, self.bridge, True, 1)
            self.assertEqual(self.bridge.publish_visualization.call_count, before + 1)

    def test_publication_session_persists_across_commit_and_changes_on_reset(self):
        first = visualization_session(self.app)
        self.edit(1.5, channel=6)
        self.assertEqual(visualization_session(self.app), first)
        self.app.shot_history.reset(self.app.project)
        self.assertNotEqual(visualization_session(self.app), first)


if __name__ == "__main__":
    unittest.main()
