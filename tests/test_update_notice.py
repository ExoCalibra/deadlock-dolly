"""Update highlights animation and lifecycle without opening a Tk window."""
import heapq
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import tkinter as tk

from dolly.ui import update_notice


class Clock:
    """A deterministic Tk after queue, including canceled callback handles."""
    def __init__(self):
        self.now = 10.0
        self.queue = []
        self.pending = {}
        self.sequence = 0

    def after(self, milliseconds, callback):
        self.sequence += 1
        token = f"after{self.sequence}"
        self.pending[token] = callback
        heapq.heappush(self.queue, (self.now + milliseconds / 1000, self.sequence, token))
        return token

    def cancel(self, token):
        self.pending.pop(token, None)

    def advance(self, seconds):
        target = self.now + seconds
        callbacks = 0
        while self.queue and self.queue[0][0] <= target:
            self.now, _, token = heapq.heappop(self.queue)
            callback = self.pending.pop(token, None)
            if callback is not None:
                callback()
                callbacks += 1
                if callbacks > 1000:
                    raise AssertionError("Animation did not settle")
        self.now = target

    def finish(self):
        for _ in range(1000):
            if not self.pending:
                return
            self.advance(max(0, self.queue[0][0] - self.now) + .000001)
        raise AssertionError("Animation left timers running")


class Variable:
    def __init__(self, *args, **kwargs):
        self.value = kwargs.get("value", "")

    def set(self, value):
        self.value = value

    def get(self):
        return self.value


class Widget:
    """Only the widget/scheduler contract used by the real notice view."""
    def __init__(self, parent=None, **options):
        self.parent = parent
        self.children = []
        self.options = options
        self.bindings = {}
        self.mapped = False
        self.dead = False
        self.height_writes = []
        self.requested_height = 24
        self.grid_options = {}
        self.yposition = 0
        if parent is not None:
            parent.children.append(self)
            self.clock, self.tk = parent.clock, parent.tk

    def configure(self, **options):
        if self.dead:
            raise tk.TclError("Widget was destroyed")
        self.options.update(options)
        if "height" in options:
            self.height_writes.append(options["height"])

    def cget(self, name):
        return self.options.get(name, "")

    def grid(self, **options):
        self.mapped = True
        self.grid_options.update(options)

    def grid_remove(self):
        self.mapped = False

    def pack(self, **options):
        self.mapped = True

    def columnconfigure(self, *args, **kwargs):
        pass

    def rowconfigure(self, *args, **kwargs):
        pass

    def grid_propagate(self, value):
        self.propagates = value

    def bind(self, name, callback, **kwargs):
        self.bindings.setdefault(name, []).append(callback)

    def after(self, milliseconds, callback):
        return self.clock.after(milliseconds, callback)

    def after_cancel(self, token):
        self.clock.cancel(token)

    def winfo_reqheight(self):
        return self.requested_height

    def winfo_reqwidth(self):
        return 300

    def winfo_children(self):
        return list(self.children)

    def update_idletasks(self):
        pass

    def yview_moveto(self, position):
        self.yposition = position

    def destroy(self):
        self.dead = True
        for callback in self.bindings.get("<Destroy>", ()):
            callback(SimpleNamespace(widget=self))
        for child in list(self.children):
            child.destroy()
        if self.parent is not None:
            self.parent.children.remove(self)


class ScrollPage(Widget):
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = Widget(self)
        self.body = Widget(self)


class UpdateNoticeTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.parent = Widget()
        self.parent.clock = self.clock
        self.parent.tk = SimpleNamespace(call=Mock(return_value=96 / 72))
        for target, replacement in (("ttk.Frame", Widget), ("ttk.Label", Widget),
                                    ("ttk.Button", Widget), ("tk.StringVar", Variable),
                                    ("ScrollPage", ScrollPage)):
            patcher = patch("dolly.ui.update_notice." + target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        style = patch("dolly.ui.update_notice.ttk.Style", return_value=Mock())
        style.start()
        self.addCleanup(style.stop)
        clock = patch("dolly.ui.update_notice.time.monotonic", side_effect=lambda: self.clock.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.update = Mock()
        self.full_notes = Mock()
        self.view = update_notice.UpdateNotice(self.parent, update=self.update, notes=Mock(),
                                              full_notes=self.full_notes, later=Mock(), reopen=Mock())
        self.release = ("9.0.1", "official-package", "a" * 64, 100)
        self.notes = [dict(title="Camera editing", before="Clear could fail.", after="Cameras stay safe.")]
        self.view.set_notes(self.notes, release=self.release)
        self.view.notes_page.body.requested_height = 800

    def open_fully(self):
        self.view.toggle_notes()
        self.clock.finish()

    def test_open_is_gradual_bounded_and_stops_scheduling_at_the_endpoint(self):
        self.view.toggle_notes()
        self.assertTrue(self.view.notes_open)
        self.assertTrue(self.view.notes_clip.mapped)
        self.assertEqual(self.view._notes_height, 0)
        self.clock.advance(.015)
        first = self.view._notes_height
        self.assertGreater(first, 0)
        self.assertLess(first, 168)
        self.clock.advance(.030)
        self.assertGreater(self.view._notes_height, first)
        self.clock.finish()
        self.assertEqual(self.view._notes_height, 168)
        self.assertFalse(self.clock.pending)
        self.assertIsNone(self.view._animation_job)
        self.assertTrue(all(1 <= height <= 168 for height in self.view.notes_clip.height_writes))
        self.update.assert_not_called()
        self.full_notes.assert_not_called()

    def test_close_animates_before_removing_the_notes_region(self):
        self.open_fully()
        self.view.toggle_notes()
        self.assertFalse(self.view.notes_open)
        self.assertTrue(self.view.notes_clip.mapped)
        self.assertEqual(self.view._notes_height, 168)
        self.clock.advance(.045)
        self.assertGreater(self.view._notes_height, 0)
        self.assertLess(self.view._notes_height, 168)
        self.clock.finish()
        self.assertEqual(self.view._notes_height, 0)
        self.assertFalse(self.view.notes_clip.mapped)
        self.assertFalse(self.clock.pending)

    def test_reversing_twice_starts_each_animation_at_the_current_height(self):
        self.view.toggle_notes()
        self.clock.advance(.045)
        opening_height = self.view._notes_height
        self.view.toggle_notes()
        self.assertEqual(self.view._notes_height, opening_height)
        self.assertEqual(len(self.clock.pending), 1)
        self.clock.advance(.015)
        closing_height = self.view._notes_height
        self.assertTrue(0 < closing_height < opening_height)
        self.view.toggle_notes()
        self.assertEqual(self.view._notes_height, closing_height)
        self.assertEqual(len(self.clock.pending), 1)
        self.clock.finish()
        self.assertTrue(self.view.notes_open)
        self.assertEqual(self.view._notes_height, 168)
        self.assertFalse(self.clock.pending)

    def test_late_tick_from_a_reversed_animation_cannot_overwrite_the_new_one(self):
        self.view.toggle_notes()
        self.clock.advance(.030)
        stale_tick = self.clock.pending[self.view._animation_job]
        self.view.toggle_notes()
        before = (self.view._notes_height, list(self.view.notes_clip.height_writes), dict(self.clock.pending))
        stale_tick()
        self.assertEqual((self.view._notes_height, self.view.notes_clip.height_writes, self.clock.pending), before)
        self.clock.finish()
        self.assertEqual(self.view._notes_height, 0)

    def test_hide_and_later_cancel_timers_close_immediately_and_reject_late_ticks(self):
        for close in (self.view.hide, lambda: self.view.collapse("9.0.1")):
            with self.subTest(close=close):
                self.view.toggle_notes()
                self.clock.advance(.030)
                stale_tick = self.clock.pending[self.view._animation_job]
                close()
                self.assertFalse(self.view.notes_open)
                self.assertEqual(self.view._notes_height, 0)
                self.assertFalse(self.view.notes_clip.mapped)
                self.assertFalse(self.clock.pending)
                before = list(self.view.notes_clip.height_writes)
                stale_tick()
                self.clock.finish()
                self.assertEqual(self.view.notes_clip.height_writes, before)

    def test_destroy_cancels_callbacks_and_future_toggle_does_not_touch_dead_widgets(self):
        self.view.toggle_notes()
        self.clock.advance(.030)
        stale_tick = self.clock.pending[self.view._animation_job]
        self.view.frame.destroy()
        self.assertTrue(self.view._destroyed_flag)
        self.assertFalse(self.clock.pending)
        before = list(self.view.notes_clip.height_writes)
        stale_tick()
        self.view.toggle_notes()
        self.clock.finish()
        self.assertEqual(self.view.notes_clip.height_writes, before)

    def test_descendant_destroy_does_not_cancel_the_live_notice_animation(self):
        self.view.toggle_notes()
        job = self.view._animation_job
        self.view._destroyed(SimpleNamespace(widget=self.view.notes_page.body))
        self.assertFalse(self.view._destroyed_flag)
        self.assertIn(job, self.clock.pending)
        self.clock.finish()
        self.assertEqual(self.view._notes_height, 168)

    def test_repeated_render_preserves_open_animation_cards_and_scroll_position(self):
        self.view.toggle_notes()
        self.clock.advance(.030)
        self.view.notes_page.canvas.yview_moveto(.55)
        before = (self.view._notes_height, self.view._animation_job,
                  self.view.notes_page.body.winfo_children())
        self.view.set_notes([dict(self.notes[0])], release=tuple(self.release))
        self.view.show("9.0.1", "Still waiting for Update now.", busy=True)
        self.assertTrue(self.view.notes_open)
        self.assertEqual(self.view.notes_page.canvas.yposition, .55)
        self.assertEqual((self.view._notes_height, self.view._animation_job,
                          self.view.notes_page.body.winfo_children()), before)
        self.clock.finish()

    def test_changed_release_closes_and_replaces_cards_without_a_stale_animation(self):
        self.view.toggle_notes()
        self.clock.advance(.030)
        stale_tick = self.clock.pending[self.view._animation_job]
        old_cards = self.view.notes_page.body.winfo_children()
        self.view.notes_page.canvas.yview_moveto(.55)
        changed_release = (*self.release[:2], "b" * 64, self.release[3])
        self.view.set_notes([dict(title="New release", before="Old behavior", after="New behavior")],
                            release=changed_release)
        self.assertFalse(self.view.notes_open)
        self.assertFalse(self.view.notes_clip.mapped)
        self.assertEqual(self.view._notes_height, 0)
        self.assertFalse(self.clock.pending)
        self.assertTrue(all(card.dead for card in old_cards))
        self.assertEqual(self.view.notes_page.canvas.yposition, 0)
        stale_tick()
        self.assertEqual(self.view._notes_height, 0)
        self.assertIn("New release", [label.cget("text") for label in self.view._note_labels])

    def test_many_before_after_cards_stay_inside_a_scaled_scroll_viewport(self):
        notes = [dict(title=f"Change {i}", before="Earlier behavior " * 30, after="New behavior " * 30)
                 for i in range(8)]
        self.view.scale = 1.5
        self.view.set_notes(notes, release=self.release)
        self.view.notes_page.body.requested_height = 2000
        cards = self.view.notes_page.body.winfo_children()
        self.assertEqual([(card.grid_options["row"], card.grid_options["column"]) for card in cards],
                         [(i // 2, i % 2) for i in range(8)])
        self.assertEqual(len(self.view._note_labels), 24)
        self.assertEqual(self.view._note_labels[1].cget("text"), "Before: " + notes[0]["before"])
        self.assertEqual(self.view._note_labels[2].cget("text"), "After: " + notes[0]["after"])
        self.view._notes_wrap(SimpleNamespace(width=480))
        self.assertTrue(all(label.cget("wraplength") == 210 for label in self.view._note_labels))
        self.open_fully()
        self.assertFalse(self.view.notes_clip.propagates)
        self.assertEqual(self.view._notes_height, 252)
        self.assertLess(self.view._notes_height, self.view.notes_page.body.requested_height)
        self.assertFalse(self.clock.pending)

    def test_short_notes_use_their_requested_height_instead_of_empty_maximum_space(self):
        self.view.notes_page.body.requested_height = 20
        self.open_fully()
        self.assertEqual(self.view._notes_height, 76)

    def test_constructor_height_callback_caps_the_view_in_physical_pixels(self):
        for budget, scale, body_height, expected in ((64, 1, 800, 64), (800, 1, 800, 168),
                                                    (64, 1.5, 800, 64), (-5, 1, 800, 1),
                                                    (150, 1, 20, 76)):
            with self.subTest(budget=budget, scale=scale, body_height=body_height):
                limit = Mock(return_value=budget)
                view = update_notice.UpdateNotice(
                    self.parent, update=self.update, notes=Mock(), full_notes=self.full_notes,
                    later=Mock(), reopen=Mock(), height_limit=limit)
                view.scale = scale
                view.set_notes(self.notes, release=self.release)
                view.notes_page.body.requested_height = body_height
                view.toggle_notes()
                self.clock.finish()
                self.assertEqual(view._notes_height, expected)
                self.assertTrue(view.notes_clip.mapped)
                self.assertTrue(all(1 <= height <= expected for height in view.notes_clip.height_writes))
                limit.assert_called_once_with()
        self.update.assert_not_called()
        self.full_notes.assert_not_called()

    def test_settled_resize_animates_from_current_height_in_both_directions(self):
        budget = [72]
        self.view.height_limit = lambda: budget[0]
        self.open_fully()
        for target in (132, 40):
            with self.subTest(target=target):
                start = self.view._notes_height
                budget[0] = target
                self.view.fit_height()
                self.assertEqual(self.view._notes_height, start)
                self.assertEqual(len(self.clock.pending), 1)
                self.clock.advance(.045)
                self.assertTrue(min(start, target) < self.view._notes_height < max(start, target))
                self.clock.finish()
                self.assertEqual(self.view._notes_height, target)
                self.assertTrue(self.view.notes_open)
                self.assertTrue(self.view.notes_clip.mapped)
                self.assertFalse(self.clock.pending)

    def test_fit_at_the_existing_budget_does_not_restart_an_animation(self):
        self.view.height_limit = Mock(return_value=72)
        self.open_fully()
        before = (self.view._animation_generation, list(self.view.notes_clip.height_writes))
        self.view.fit_height()
        self.assertEqual((self.view._animation_generation, self.view.notes_clip.height_writes), before)
        self.assertIsNone(self.view._animation_job)
        self.assertFalse(self.clock.pending)

    def test_closed_or_destroyed_notice_ignores_fit_without_reading_layout(self):
        limit = self.view.height_limit = Mock(return_value=72)
        before = list(self.view.notes_clip.height_writes)
        self.view.fit_height()
        limit.assert_not_called()
        self.assertEqual(self.view.notes_clip.height_writes, before)
        self.assertFalse(self.clock.pending)
        self.open_fully()
        self.view.frame.destroy()
        limit.reset_mock()
        before = list(self.view.notes_clip.height_writes)
        self.view.fit_height()
        limit.assert_not_called()
        self.assertEqual(self.view.notes_clip.height_writes, before)
        self.assertFalse(self.clock.pending)

    def test_resize_at_a_rounded_animation_endpoint_fits_after_completion_without_another_event(self):
        limit = self.view.height_limit = Mock(return_value=168)
        self.view.toggle_notes()
        self.clock.advance(.166)
        self.assertEqual(self.view._notes_height, 168)
        self.assertIsNotNone(self.view._animation_job)
        before = (self.view._animation_job, self.view._animation_generation,
                  list(self.view.notes_clip.height_writes), dict(self.clock.pending))
        limit.reset_mock()
        limit.return_value = 40
        self.view.fit_height()
        self.view.fit_height()
        limit.assert_not_called()
        self.assertEqual((self.view._animation_job, self.view._animation_generation,
                          self.view.notes_clip.height_writes, self.clock.pending), before)
        self.assertTrue(self.view._fit_pending)
        self.clock.finish()
        self.assertEqual(self.view._notes_height, 40)
        self.assertFalse(self.view._fit_pending)
        self.assertIsNone(self.view._animation_job)
        self.assertTrue(self.view.notes_open)
        self.assertTrue(self.view.notes_clip.mapped)
        self.assertFalse(self.clock.pending)
        limit.assert_called_once_with()

    def test_closing_cancels_an_inflight_pending_resize(self):
        limit = self.view.height_limit = Mock(return_value=168)
        for close in (self.view.close_notes, self.view.hide, lambda: self.view.collapse("9.0.1")):
            with self.subTest(close=close):
                limit.return_value = 168
                self.view.toggle_notes()
                self.clock.advance(.045)
                stale_tick = self.clock.pending[self.view._animation_job]
                limit.return_value = 40
                self.view.fit_height()
                self.assertTrue(self.view._fit_pending)
                close()
                limit.reset_mock()
                before = list(self.view.notes_clip.height_writes)
                stale_tick()
                self.clock.finish()
                self.assertFalse(self.view._fit_pending)
                self.assertFalse(self.view.notes_open)
                self.assertFalse(self.view.notes_clip.mapped)
                self.assertEqual(self.view._notes_height, 0)
                self.assertEqual(self.view.notes_clip.height_writes, before)
                self.assertFalse(self.clock.pending)
                limit.assert_not_called()

    def test_empty_notes_keep_an_inline_fallback_and_separate_full_notes_action(self):
        self.view.set_notes([], release=self.release)
        children = self.view.notes_page.body.winfo_children()
        self.assertEqual(len(children), 1)
        self.assertIn("full release notes", children[0].cget("text"))
        self.view.toggle_notes()
        self.clock.finish()
        self.assertTrue(self.view.notes_open)
        self.full_notes.assert_not_called()
        self.update.assert_not_called()
        self.view.full_notes_button.cget("command")()
        self.full_notes.assert_called_once_with()
        self.update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
