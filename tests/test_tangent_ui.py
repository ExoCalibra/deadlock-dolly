"""Saved movement-slope authoring transactions and their real desktop controls."""
import copy
import math
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from dolly.curve import PositionBounds
from dolly.curve_workspace import (CameraCurveWorkspace, CurveWorkspaceState,
                                   tangent_handle, tangent_times)
from dolly.path import AttachKey, CameraTangent, Keyframe, Project


def shot():
    return Project(interpolation="smooth", keyframes=[
        Keyframe(0, 0, 0, 0, 0, 0, 0),
        Keyframe(2, 20, 10, 5, 10, 20, 30),
        Keyframe(5, 80, 40, 20, 20, 40, 60)])


class TangentTransactionTests(unittest.TestCase):
    def setUp(self):
        self.project = shot()
        self.changes = Mock()
        self.state = CurveWorkspaceState(Mock(), on_tangent_change=self.changes)
        self.state.refresh(self.project, 1, context=(71, 3))

    def test_preview_uses_the_real_evaluator_and_one_commit_keeps_other_fields_exact(self):
        original = copy.deepcopy(self.project)
        self.state.pin_original()
        self.assertTrue(self.state.begin_tangent(1, "x"))
        preview = self.state.tangent_preview("broken", 0.0, 40.0)
        self.assertEqual(self.project, original)
        self.assertEqual(self.state.original, original)
        self.assertNotEqual(preview.evaluate(1)["x"], original.evaluate(1)["x"])
        self.assertEqual(preview.keyframes[1].time, 2)
        expected = copy.deepcopy(original)
        expected.keyframes[1].tangents["x"] = CameraTangent("broken", 0.0, 40.0)
        self.assertEqual(preview, expected)
        self.assertTrue(self.state.commit_tangent("broken", 0.0, 40.0))
        self.assertFalse(self.state.commit_tangent("flat"))
        self.changes.assert_called_once_with(1, "x", "broken", 0.0, 40.0)

    def test_noop_cancel_and_invalid_slopes_have_no_history_callback(self):
        for mode, incoming, outgoing in (("auto", None, None), ("broken", math.nan, 2),
                                         ("linked", 1, 2), ("broken", 1, math.inf)):
            with self.subTest(mode=mode, incoming=incoming, outgoing=outgoing):
                self.assertTrue(self.state.begin_tangent(1, "x"))
                self.assertFalse(self.state.commit_tangent(mode, incoming, outgoing))
        self.state.begin_tangent(1, "x")
        self.state.tangent_preview("flat")
        self.state.cancel()
        self.assertFalse(self.state.commit_tangent("flat"))
        self.changes.assert_not_called()
        self.assertEqual(self.project, shot())

    def test_mode_source_and_selection_guards_keep_dormant_metadata(self):
        self.project.set_camera_tangent(1, "x", "broken", incoming=2, outgoing=7)
        original = copy.deepcopy(self.project)
        for interpolation in ("linear", "spline"):
            self.project.interpolation = interpolation
            self.assertFalse(self.state.begin_tangent(1, "x"))
        self.project.interpolation = "smooth"
        self.assertTrue(self.state.begin_tangent(1, "x"))
        self.state.cancel()
        for channel in ("pitch", "aspect_ratio", "other"):
            self.assertFalse(self.state.begin_tangent(1, channel))
        for index in (None, True, "1", -1, 9):
            self.assertFalse(self.state.begin_tangent(index, "x"))
        self.project.keyframes[1].source = "attach"
        self.project.keyframes[1].attach = AttachKey(handle=2, model="hero.vmdl", point="bone", bone="head")
        self.assertFalse(self.state.begin_tangent(1, "x"))
        self.assertEqual(self.project.keyframes[1].tangents, original.keyframes[1].tangents)

    def test_session_revision_identity_selection_content_and_busy_changes_cancel(self):
        for change in ("session", "revision", "identity", "selection", "content", "busy", "mode"):
            with self.subTest(change=change):
                self.setUp()
                self.state.begin_tangent(1, "x")
                project, selected, context = self.project, 1, (71, 3)
                if change == "session": context = (72, 3)
                elif change == "revision": context = (71, 4)
                elif change == "identity": project = copy.deepcopy(project)
                elif change == "selection": selected = 2
                elif change == "content": project.keyframes[0].y += 1
                elif change == "busy": self.state.enabled = False
                elif change == "mode": project.interpolation = "linear"
                self.state.refresh(project, selected, context=context)
                self.assertFalse(self.state.commit_tangent("flat"))
                self.changes.assert_not_called()

    def test_tangent_metadata_invalidates_samples_without_camera_value_changes(self):
        first = self.state.samples(self.project, "x", 0, 5)
        self.state.pin_original()
        self.project.set_camera_tangent(1, "x", "flat")
        second = self.state.samples(self.project, "x", 0, 5)
        self.assertNotEqual(first, second)
        self.assertEqual(self.state.samples(self.state.original, "x", 0, 5), first)
        self.assertEqual(tangent_times(self.project, 1), (-2/3, 1.0))
        self.assertEqual(tangent_times(self.project, 0), (None, 2/3))

    def test_compact_arms_represent_the_same_slope_at_both_time_zooms_and_scales(self):
        for end in (5, 2.5):
            for scale in (1, 1.5):
                bounds = PositionBounds(62, 12, 1224, 232, 0, end, -100, 100)
                for delta in (-2/3, 1):
                    for slope in (-400, 0, 25, 2e6):
                        with self.subTest(end=end, scale=scale, delta=delta, slope=slope):
                            x, y, effective_delta = tangent_handle(bounds, 2, 20, delta, slope, scale)
                            key_x, key_y = bounds.point(2, 20)
                            self.assertLessEqual(math.hypot(x-key_x, y-key_y), 56*scale+1e-7)
                            self.assertGreaterEqual(x, bounds.left+7*scale-1e-7)
                            self.assertLessEqual(x, bounds.right-7*scale+1e-7)
                            self.assertGreaterEqual(y, bounds.top+7*scale-1e-7)
                            self.assertLessEqual(y, bounds.bottom-7*scale+1e-7)
                            self.assertEqual(math.copysign(1, effective_delta), math.copysign(1, delta))
                            self.assertAlmostEqual((x-key_x)*bounds.duration/(bounds.right-bounds.left),
                                                   effective_delta)
                            # The display arm's time offset changes, while the
                            # slope in saved units/shot-second remains exact.
                            self.assertAlmostEqual((bounds.value_at(y)-20)/effective_delta,
                                                   slope, delta=max(1e-6, abs(slope)*1e-7))


class TangentControlTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.changes = Mock()
        self.context = [71, 3]
        self.workspace = CameraCurveWorkspace(self.root, on_change=Mock(), on_select=Mock(),
                                              on_reset=Mock(), context=lambda:tuple(self.context),
                                              on_tangent_change=self.changes)
        self.workspace.pack(fill="both", expand=True)
        self.project = shot()
        self.workspace.set_project(self.project, 1)
        self.lane = self.workspace.lanes[0]
        self.root.update_idletasks()

    def draw(self):
        with patch.object(self.lane.canvas, "winfo_width", return_value=640), \
                patch.object(self.lane.canvas, "winfo_height", return_value=180):
            self.lane._redraw()

    def start_handle(self, side="outgoing"):
        self.draw()
        x, y, delta = self.lane._handle_points[side]
        self.lane._press(SimpleNamespace(x=x+1, y=y+1))
        return y+1, delta

    def test_mode_choice_seeds_slopes_and_does_not_change_interpolation(self):
        slopes = self.project.camera_tangent_slopes(1, "x")
        self.lane.tangent_mode.set("Broken")
        self.lane._change_tangent_mode()
        self.changes.assert_called_once_with(1, "x", "broken", *slopes)
        self.assertEqual(self.project.interpolation, "smooth")
        self.assertEqual(self.project.keyframes[1].tangents, {})
        self.changes.reset_mock()
        self.lane.tangent_mode.set("Auto")
        self.lane._change_tangent_mode()
        self.changes.assert_not_called()

    def test_numeric_linked_edit_commits_once_and_exact_focus_noop_does_not(self):
        self.project.set_camera_tangent(1, "x", "linked", incoming=3.1234567890123, outgoing=3.1234567890123)
        self.workspace.set_project(self.project, 1)
        self.lane._begin_tangent_value("incoming")
        self.assertEqual(float(self.lane.tangent_texts["incoming"].get()), 3.1234567890123)
        self.lane._apply_tangent_value()
        self.changes.assert_not_called()
        self.lane._begin_tangent_value("outgoing")
        self.lane.tangent_texts["outgoing"].set("-7.25")
        self.lane._leave_tangent_value()
        self.lane._leave_tangent_value()
        self.changes.assert_called_once_with(1, "x", "linked", -7.25, -7.25)

    def test_numeric_invalid_cancel_and_stale_revision_do_not_commit(self):
        self.project.set_camera_tangent(1, "x", "broken", incoming=2, outgoing=7)
        self.workspace.set_project(self.project, 1)
        self.lane._begin_tangent_value("incoming")
        self.lane.tangent_texts["incoming"].set("nan")
        self.lane._apply_tangent_value()
        self.assertIn("finite slope", self.lane.hint.cget("text"))
        self.assertFalse(self.workspace.settle_numeric())
        self.lane._cancel_tangent_value()
        self.lane._begin_tangent_value("incoming")
        self.lane.tangent_texts["incoming"].set("12")
        self.context[1] += 1
        self.workspace.set_project(self.project, 1)
        self.lane._apply_tangent_value()
        self.changes.assert_not_called()
        self.assertEqual(self.project.camera_tangent(1, "x"), CameraTangent("broken", 2, 7))

    def test_finite_but_unsafe_numeric_slope_keeps_a_visible_correctable_draft(self):
        self.project.set_camera_tangent(1, "x", "broken", incoming=2, outgoing=7)
        self.workspace.set_project(self.project, 1)
        self.lane._begin_tangent_value("outgoing")
        self.lane.tangent_texts["outgoing"].set("1e308")
        self.lane._apply_tangent_value()
        self.assertEqual(self.lane._tangent_side, "outgoing")
        self.assertEqual(self.lane.tangent_texts["outgoing"].get(), "1e308")
        self.assertTrue(self.lane._tangent_error)
        self.assertEqual(self.lane.hint.cget("text"), self.lane._tangent_error)
        self.assertFalse(self.workspace.settle_numeric())
        self.changes.assert_not_called()
        self.lane.tangent_texts["outgoing"].set("100")
        self.lane._apply_tangent_value()
        self.assertIsNone(self.lane._tangent_side)
        self.changes.assert_called_once_with(1, "x", "broken", 2, 100.0)

    def test_handle_drag_is_vertical_fixed_time_private_and_one_commit(self):
        original = copy.deepcopy(self.project)
        y, delta = self.start_handle()
        bounds = self.lane._drag_bounds
        original_slope = self.project.camera_tangent_slopes(1, "x")[1]
        self.lane._motion(SimpleNamespace(y=y))
        self.lane._release()
        self.changes.assert_not_called()
        y, delta = self.start_handle()
        for displacement in (-3, -6, -12):
            self.lane._motion(SimpleNamespace(y=y+displacement))
        expected = original_slope+(bounds.value_at(y-12)-bounds.value_at(y))/delta
        self.assertEqual(self.project, original)
        self.assertEqual(self.lane._preview.keyframes[1].time, 2)
        self.assertAlmostEqual(self.lane._preview.camera_tangent(1, "x").outgoing, expected)
        self.changes.assert_not_called()
        self.lane._release()
        self.lane._release()
        args = self.changes.call_args.args
        self.assertEqual(args[:3], (1, "x", "broken"))
        self.assertAlmostEqual(args[4], expected)
        self.assertEqual(self.changes.call_count, 1)

    def test_handle_preview_keeps_identity_and_live_slope_then_clears_before_commit(self):
        order = []
        self.workspace.on_preview = lambda project,gesture: order.append(("preview",project,gesture))
        self.changes.side_effect = lambda *args: order.append(("commit",args))
        before = copy.deepcopy(self.project)
        y,_delta = self.start_handle()
        gesture = self.workspace.state.gesture
        self.lane._motion(SimpleNamespace(y=y-8))
        preview = order[-1][1]
        self.assertIs(order[-1][2],gesture)
        self.assertEqual(self.project,before)
        self.assertNotEqual(preview.evaluate(3)["x"],before.evaluate(3)["x"])
        self.assertAlmostEqual(float(self.lane.tangent_texts["outgoing"].get()),
                               preview.camera_tangent(1,"x").outgoing, places=5)
        self.lane._motion(SimpleNamespace(y=y))
        self.assertIs(order[-1][1],self.project)
        self.assertIs(order[-1][2],gesture)
        self.lane._motion(SimpleNamespace(y=y-8))
        self.lane._release()
        self.assertEqual(order[-2],("preview",None,None))
        self.assertEqual(order[-1][0],"commit")
        self.assertEqual(self.changes.call_count,1)

    def test_right_click_focus_loss_tab_change_and_busy_cancel_preview(self):
        for reason in ("right-click", "focus-loss", "tab", "busy"):
            with self.subTest(reason=reason):
                self.workspace.set_enabled(True)
                self.workspace.select_group(0)
                y, _delta = self.start_handle()
                self.lane._motion(SimpleNamespace(y=y-10))
                if reason == "right-click": self.lane._pan_press(SimpleNamespace(x=200))
                elif reason == "focus-loss": self.lane._cancel()
                elif reason == "tab": self.workspace.select_group(1)
                elif reason == "busy": self.workspace.set_enabled(False)
                self.lane._release()
                self.assertIsNone(self.lane._preview)
                self.assertIsNone(self.workspace.state.gesture)
        self.changes.assert_not_called()

    def test_dormant_controls_show_saved_values_and_never_autoswitch(self):
        self.project.set_camera_tangent(1, "x", "broken", incoming=2.5, outgoing=-7.5)
        self.project.interpolation = "linear"
        self.workspace.set_project(self.project, 1)
        self.draw()
        self.assertEqual(self.lane.tangent_mode.get(), "Broken")
        self.assertEqual(self.lane.tangent_texts["incoming"].get(), "2.5")
        self.assertEqual(self.lane.tangent_texts["outgoing"].get(), "-7.5")
        self.assertEqual(str(self.lane.tangent_mode_box.cget("state")), "disabled")
        self.assertTrue(all(str(entry.cget("state")) == "disabled" for entry in self.lane.tangent_entries.values()))
        self.assertIn("applies in Smooth", self.lane.hint.cget("text"))
        self.assertEqual(self.lane._handle_points, {})
        self.lane.tangent_mode.set("Flat")
        self.lane._change_tangent_mode()
        self.changes.assert_not_called()
        self.assertEqual(self.project.interpolation, "linear")
        self.project.interpolation = "smooth"
        self.workspace.set_project(self.project, 1)
        self.draw()
        self.assertEqual(self.lane.tangent_mode.get(), "Broken")
        self.assertEqual(len(self.lane._handle_points), 2)


if __name__ == "__main__":
    unittest.main()
