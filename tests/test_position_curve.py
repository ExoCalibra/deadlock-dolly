"""XYZ authoring transactions, graph gestures and coefficient parity; no game."""
import copy
import math
from pathlib import Path
import struct
import tempfile
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from dolly.curve import (PositionCurve, POSITION_CHANNELS, POSITION_LIMIT,
                         TimelineView, position_bounds, sample_channel)
from dolly.gui import DollyApp
from dolly.native_path import CHANNEL_RECORD, HEADER, LENS_HEADER, compile_project
from dolly.object_model import PlacedObject
from dolly.path import CURVE_CHANNELS, AttachKey, CvarTrack, Keyframe, Project, TrackKey
from dolly.shot_history import ShotHistory
from dolly.settings import AppSettings


def shot(mode="smooth"):
    return Project(interpolation=mode, keyframes=[
        Keyframe(.2, -40, 20, 100, 10, 170, 3),
        Keyframe(.7, 80, -30, 200, 20, -175, 4, curve_pitch=22, lens_scale=.9),
        Keyframe(3.1, 15, 100, -80, 30, -140, 5)],
        tracks=[CvarTrack("r_dof_override", [TrackKey(4, 1)], interpolation="step")])


class Value:
    def __init__(self, value=""):
        self.value = value
    def set(self, value):
        self.value = value
    def get(self):
        return self.value


def graph_harness(project=None, channel="x"):
    graph = PositionCurve.__new__(PositionCurve)
    graph.project = project or shot()
    graph.selected_index, graph.current_time, graph.channel = 1, 0.0, channel
    graph._enabled = True
    graph.view = TimelineView()
    graph._bounds = position_bounds(560, 140, graph.project, channel)
    graph._points = [graph._bounds.point(key.time, getattr(key, channel)) for key in graph.project.keyframes]
    graph._clear_drag()
    graph._editing_value, graph._value_origin = False, None
    graph.value_text = Value()
    graph.canvas = SimpleNamespace(focus_set=Mock())
    graph.hint = SimpleNamespace(configure=Mock())
    graph.value_entry = SimpleNamespace(configure=Mock())
    graph.apply_button = SimpleNamespace(configure=Mock())
    graph.channel_box = SimpleNamespace(configure=Mock(), current=Mock(return_value=0))
    graph.on_select, graph.on_change, graph.on_view = Mock(), Mock(), Mock()
    graph._redraw = Mock()
    graph._sync_value()
    return graph


def drag(graph, value=35.25):
    x, y = graph._points[1]
    graph._press(SimpleNamespace(x=x, y=y))
    _, target_y = graph._bounds.point(graph.project.keyframes[1].time, value)
    graph._motion(SimpleNamespace(x=999, y=target_y))


def app_harness():
    app = DollyApp.__new__(DollyApp)
    app.project = shot()
    app.shot_history = ShotHistory(app.project)
    app.busy = app.playing = app.preview_attach = False
    app.dirty = False
    app.video_export = Mock()
    app.video_export.status.return_value = {"state": "idle"}
    app.status_text = Mock()
    app.controller = Mock()
    app.camera_tree = Mock()
    app._selection_index = Mock(return_value=1)
    app._title, app._refresh_keys, app._refresh_curve = Mock(), Mock(), Mock()
    app._refresh_project, app._set_time, app._sync_options = Mock(), Mock(), Mock()
    app._guard = lambda _title, operation: operation()
    return app


def compiled_value(blob, channel, timestamp):
    """Independent little-endian decode and Hermite polynomial evaluation."""
    version = struct.unpack_from("<I", blob, 8)[0]
    header_type = LENS_HEADER if version == 2 else HEADER
    header = header_type.unpack_from(blob)
    count, channels = header[2:4]
    if timestamp <= header[6]:
        return header[8 + channel]
    if timestamp >= header[7]:
        return header[8 + channels + channel]
    stride = 16 + channels * CHANNEL_RECORD.size
    for index in range(count):
        offset = header_type.size + index * stride
        start, end = struct.unpack_from("<2d", blob, offset)
        if start <= timestamp <= end:
            kind, _flags, a, b, da, db = struct.unpack_from("<II4d", blob, offset + 16 + channel * 40)
            if kind == 0:
                return b if timestamp == end else a
            u = (timestamp - start) / (end - start)
            if kind == 1:
                return a * (1 - u) + b * u
            return ((2*u**3 - 3*u**2 + 1)*a + (u**3 - 2*u**2 + u)*(end-start)*da
                    + (-2*u**3 + 3*u**2)*b + (u**3-u**2)*(end-start)*db)
    raise AssertionError("No compiled segment")


class PositionModelTests(unittest.TestCase):
    def test_channels_do_not_change_rotation_override_schema(self):
        self.assertEqual(POSITION_CHANNELS, ("x", "y", "z"))
        self.assertEqual(CURVE_CHANNELS, ("pitch", "yaw", "roll"))
        self.assertNotIn("curve_x", shot().to_dict()["keyframes"][0])

    def test_linear_xyz_samples_have_known_values_and_endpoint_holds(self):
        project = Project(interpolation="linear", keyframes=[
            Keyframe(1, -10, 40, 100, 0, 0, 0), Keyframe(5, 30, -40, 300, 0, 0, 0)])
        for axis, start, end in (("x", -10, 30), ("y", 40, -40), ("z", 100, 300)):
            for time, value in sample_channel(project, axis, 0, 6, 25):
                fraction = min(1, max(0, (time - 1) / 4))
                self.assertAlmostEqual(value, start*(1-fraction)+end*fraction, places=10)

    def test_uneven_smooth_spline_linear_samples_match_compiled_coefficients(self):
        for mode in ("smooth", "spline", "linear"):
            project = shot(mode)
            project.keyframes[1].y = -71.125
            blob = compile_project(project)
            for index, axis in enumerate(POSITION_CHANNELS):
                for time, value in sample_channel(project, axis, 0, 4, 61):
                    with self.subTest(mode=mode, axis=axis, time=time):
                        self.assertAlmostEqual(value, compiled_value(blob, index, time), places=8)

    def test_position_does_not_enable_unsupported_step_camera_mode(self):
        with self.assertRaisesRegex(ValueError, "Camera interpolation"):
            sample_channel(shot("step"), "x", 0, 4, 5)

    def test_empty_flat_and_large_finite_bounds_remain_usable(self):
        for coordinate in (0, -2500, 1e308, -1e308):
            project = Project(keyframes=[Keyframe(0, coordinate, 0, 0, 0, 0, 0)])
            bounds = position_bounds(560, 140, project, "x")
            self.assertTrue(math.isfinite(bounds.low) and math.isfinite(bounds.high))
            self.assertLess(bounds.low, bounds.high)
            self.assertTrue(all(math.isfinite(value) for value in bounds.point(0, coordinate)))
        self.assertGreater(position_bounds(560, 140, Project(), "x").high, 0)


class PositionGestureTests(unittest.TestCase):
    def test_drag_is_private_and_commits_once_with_fixed_time(self):
        graph = graph_harness()
        before = copy.deepcopy(graph.project)
        drag(graph)
        graph._motion(SimpleNamespace(x=-1000, y=graph._bounds.point(.7, 35.25)[1]))
        self.assertEqual(graph.project, before)
        self.assertAlmostEqual(graph._preview.keyframes[1].x, 35.25)
        self.assertEqual([key.time for key in graph._preview.keyframes], [.2, .7, 3.1])
        graph.on_change.assert_not_called()
        graph._release()
        graph._release()
        graph.on_change.assert_called_once()
        self.assertEqual(graph.on_change.call_args.args[:2], (1, "x"))
        self.assertAlmostEqual(graph.on_change.call_args.args[2], 35.25)
        self.assertEqual(graph.project, before)

    def test_off_center_horizontal_drag_and_unchanged_numeric_preserve_full_precision(self):
        graph = graph_harness()
        precise = 123.456789012345
        graph.project.keyframes[1].x = precise
        graph.set_project(graph.project, 1)
        graph._points = [graph._bounds.point(key.time, key.x) for key in graph.project.keyframes]
        x, y = graph._points[1]
        graph._press(SimpleNamespace(x=x + 4, y=y - 5))
        graph._motion(SimpleNamespace(x=x + 200, y=y - 5))
        graph._release()
        graph.on_change.assert_not_called()
        self.assertEqual(graph.value_text.get(), repr(precise))
        graph._begin_value()
        graph._apply_value()
        graph.on_change.assert_not_called()

    def test_click_without_motion_and_escape_do_not_commit(self):
        graph = graph_harness()
        x, y = graph._points[1]
        graph._press(SimpleNamespace(x=x, y=y))
        graph._release()
        drag(graph)
        graph._cancel()
        graph._release()
        graph.on_change.assert_not_called()

    def test_stale_in_place_mutations_cannot_commit(self):
        changes = (lambda p: setattr(p.keyframes[1], "z", 999),
                   lambda p: setattr(p.keyframes[1], "time", .8),
                   lambda p: setattr(p, "interpolation", "linear"),
                   lambda p: p.keyframes.reverse(), lambda p: p.keyframes.pop(1))
        for change in changes:
            graph = graph_harness()
            drag(graph)
            change(graph.project)
            graph._release()
            graph.on_change.assert_not_called()
            self.assertIsNone(graph._preview)

    def test_project_selection_channel_disable_focus_loss_and_hide_cancel(self):
        for boundary in ("project", "selection", "channel", "disable", "focus", "hide", "view"):
            graph = graph_harness()
            drag(graph)
            if boundary == "project":
                graph.set_project(shot(), 1)
            elif boundary == "selection":
                graph.set_project(graph.project, 2)
            elif boundary == "channel":
                graph.channel_box.current.return_value = 2
                graph._channel_changed()
            elif boundary == "disable":
                graph.set_enabled(False)
            elif boundary == "view":
                graph._after_view_change()
            else:
                graph._cancel(SimpleNamespace(type=boundary))
            graph._release()
            graph.on_change.assert_not_called()

    def test_unchanged_enable_poll_does_not_redraw_or_resample_hidden_graph(self):
        graph = graph_harness()
        graph._redraw.reset_mock()
        graph.set_enabled(True)
        graph.set_enabled(True)
        graph._redraw.assert_not_called()
        graph.set_enabled(False)
        graph._redraw.assert_called_once()
        graph.set_enabled(False)
        graph._redraw.assert_called_once()

    def test_keyboard_and_numeric_edits_are_explicit_finite_and_bounded(self):
        graph = graph_harness()
        graph._key(SimpleNamespace(keysym="Up", state=0))
        graph.on_change.assert_called_once_with(1, "x", 81)
        graph.on_change.reset_mock()
        graph._key(SimpleNamespace(keysym="Down", state=1))
        graph.on_change.assert_called_once_with(1, "x", 70)
        for bad in ("nan", "inf", "-inf", "oops", str(POSITION_LIMIT+1)):
            graph.on_change.reset_mock()
            graph._begin_value()
            graph.value_text.set(bad)
            graph._apply_value()
            graph.on_change.assert_not_called()
        graph._begin_value()
        graph.value_text.set("-128.125")
        graph._apply_value()
        graph.on_change.assert_called_once_with(1, "x", -128.125)

    def test_attached_keys_are_readable_selectable_and_not_editable(self):
        project = shot()
        project.keyframes[1].source = "attach"
        project.keyframes[1].attach = AttachKey(handle=3, model="hero.vmdl", point="eyes")
        graph = graph_harness(project)
        drag(graph)
        graph._release()
        graph.value_text.set("42")
        graph._apply_value()
        graph._key(SimpleNamespace(keysym="Up", state=0))
        graph.on_select.assert_called_once_with(1)
        graph.on_change.assert_not_called()
        self.assertEqual(graph.value_entry.configure.call_args.kwargs["state"], "disabled")

    def test_numeric_draft_survives_refresh_and_cannot_reach_new_key_or_project(self):
        graph = graph_harness()
        graph._begin_value()
        graph.value_text.set("123.4")
        graph.set_project(graph.project, 1)
        graph.set_enabled(True)
        self.assertEqual(graph.value_text.get(), "123.4")
        graph._apply_value()
        graph.on_change.assert_called_once_with(1, "x", 123.4)
        for boundary in ("project", "selection", "mutation", "channel", "disable", "focus", "escape", "hide"):
            graph = graph_harness()
            graph._begin_value()
            graph.value_text.set("456.7")
            if boundary == "project":
                graph.set_project(shot(), 1)
            elif boundary == "selection":
                graph.set_project(graph.project, 2)
            elif boundary == "mutation":
                graph.project.keyframes[0].z = 77
            elif boundary == "channel":
                graph.channel_box.current.return_value = 1
                graph._channel_changed()
            elif boundary == "disable":
                graph.set_enabled(False)
            elif boundary in ("focus", "escape"):
                graph._cancel_value()
            else:
                graph._cancel()
            graph._apply_value()
            graph.on_change.assert_not_called()

    def test_numeric_noop_and_out_of_range_drag_do_not_commit(self):
        graph = graph_harness()
        graph._begin_value()
        graph.value_text.set("80")
        graph._apply_value()
        drag(graph, POSITION_LIMIT*2)
        graph._release()
        graph.on_change.assert_not_called()


class PositionTransactionTests(unittest.TestCase):
    def test_edit_save_reopen_undo_redo_preserve_full_metadata_and_native_blob(self):
        app = app_harness()
        app.project.keyframes[2].source = "attach"
        app.project.keyframes[2].attach = AttachKey(handle=3, model="hero.vmdl", point="bone", bone="head")
        app.project.keyframes[2].source_blend = .2
        app.project.objects = [PlacedObject(library_id="crate", position=[1, 2, 3])]
        app.shot_history.reset(app.project)
        original = copy.deepcopy(app.project)
        original_blob = compile_project(original)
        app._change_position_curve(1, "y", -128.25)
        expected = copy.deepcopy(original)
        expected.keyframes[1].y = -128.25
        self.assertEqual(app.project, expected)
        self.assertEqual(app.project.to_dict()["version"], original.to_dict()["version"])
        app._refresh_keys.assert_called_once_with(.7)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"position-shot.json"
            app.project.save(path)
            reopened = Project.load(path)
        self.assertEqual(reopened, expected)
        self.assertEqual(compile_project(reopened), compile_project(expected))
        self.assertNotEqual(compile_project(reopened), original_blob)
        self.assertEqual(app.shot_history.move().project, original)
        self.assertFalse(app.shot_history.can_undo)
        self.assertEqual(app.shot_history.move(True).project, expected)
        self.assertEqual(app.controller.mock_calls, [])

    def test_noop_does_not_advance_dirty_revision_or_publish(self):
        app = app_harness()
        revision = app.shot_history.revision
        app._change_position_curve(1, "x", 80)
        self.assertEqual(app.shot_history.revision, revision)
        self.assertFalse(app.shot_history.can_undo or app.dirty)
        app._refresh_keys.assert_not_called()

    def test_bad_axis_index_nonfinite_range_and_attachment_fail_atomically(self):
        for index, axis, value in ((1, "curve_x", 4), (True, "x", 4), (-1, "x", 4),
                                   (99, "x", 4), (1, "x", math.nan), (1, "x", math.inf),
                                   (1, "x", POSITION_LIMIT+1)):
            app = app_harness()
            original = copy.deepcopy(app.project)
            with self.assertRaises(ValueError):
                app._change_position_curve(index, axis, value)
            self.assertEqual(app.project, original)
            self.assertFalse(app.shot_history.can_undo)
        app = app_harness()
        app.project.keyframes[1].source = "attach"
        with self.assertRaisesRegex(ValueError, "Attached"):
            app._change_position_curve(1, "x", 42)
        self.assertFalse(app.shot_history.can_undo)

    def test_recording_layer_and_live_preview_reject_edits(self):
        for state in ("recording", "layer", "attach", "picker", "capture"):
            app = app_harness()
            before = copy.deepcopy(app.project)
            if state == "recording":
                app.video_export.status.return_value = {"state": "recording"}
            elif state == "layer":
                app._layer_queue = [1]
            elif state == "attach":
                app.preview_attach = True
            elif state == "picker":
                app._bone_picker_context = {"active": True}
            else:
                app._pending_capture = object()
            app._change_position_curve(1, "x", 42)
            self.assertEqual(app.project, before)
            self.assertFalse(app.shot_history.can_undo)

    def test_two_desktop_edits_are_separate_from_native_slider_merge_group(self):
        app = app_harness()
        app._history_edit_group = ("x", 1)
        first = copy.deepcopy(app.project)
        app._change_position_curve(1, "x", 42)
        second = copy.deepcopy(app.project)
        app._change_position_curve(1, "x", 55)
        self.assertEqual(app._history_edit_group, ("x", 1))
        self.assertEqual(app.shot_history.move().project, second)
        self.assertEqual(app.shot_history.move().project, first)


class PositionDesktopLayoutTests(unittest.TestCase):
    def test_real_widgets_share_upper_graph_slot_and_bind_cancel_boundaries(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        root.withdraw()
        app = None
        try:
            with patch.object(DollyApp, "_submit"), \
                 patch.object(DollyApp, "_load_app_settings", return_value=AppSettings(auto_updates=False)), \
                 patch("dolly.graphics_profiles.load_library", return_value={"format": 1, "selected": "", "profiles": []}):
                app = DollyApp(root)
            root.update_idletasks()
            workspace = app.camera_curve_workspace
            self.assertEqual(tuple(button.cget("text") for button in workspace.tab_buttons),
                             ("Position", "Rotation", "Framing"))
            self.assertEqual(app.position_curve.master, app.rotation_curve.master)
            self.assertEqual(app.aspect_curve.master, app.position_curve.master)
            self.assertEqual(app.position_curve.view, app.rotation_curve.view)
            self.assertIs(app.position_curve.view, app.aspect_curve.view)
            self.assertIn("_cancel", app.position_curve.canvas.bind("<FocusOut>"))
            self.assertIn("_cancel", app.position_curve.bind("<Unmap>"))
            self.assertIn("_cancel", app.position_curve.canvas.bind("<KeyPress-Escape>"))
            self.assertIn("_begin_value", app.position_curve.value_entry.bind("<FocusIn>"))
            self.assertIn("_leave_value", app.position_curve.value_entry.bind("<FocusOut>"))
            self.assertIn("_cancel_value", app.position_curve.value_entry.bind("<Escape>"))
            app.position_curve.set_project(shot(), selected_index=1)
            self.assertEqual(app.position_curve.value_text.get(), "80")
            self.assertEqual(str(app.position_curve.value_entry.cget("state")), "normal")
            self.assertFalse(app.shot_history.can_undo)
        finally:
            if app is not None:
                app.closed = True
                app.jobs.put(None)
            for timer in root.tk.splitlist(root.tk.call("after", "info")):
                root.tk.call("after", "cancel", timer)
            root.destroy()


if __name__ == "__main__":
    unittest.main()
