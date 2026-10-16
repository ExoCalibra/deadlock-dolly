"""Recorder state, settings validation and local side-button boundaries."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from dolly.editor_actions import BINDABLE_ORDER, EDITOR_KEY_CHOICES, MOVEMENT_ACTIONS, EditorBinding
from dolly.settings import AppSettings, load_settings, save_settings
from dolly.ui.binding_capture import (
    BindingCapture, SideMouseCapture, binding_settings, binding_snapshot,
    key_from_event, modifiers_from_event, _WindowsSideMouseAPI,
)


class BindingCaptureTests(unittest.TestCase):
    def setUp(self):
        self.settings = AppSettings()
        self.before = binding_snapshot(self.settings)

    def test_chord_records_once_and_requires_explicit_proposal(self):
        capture = BindingCapture(self.settings, "capture")
        capture.press("Ctrl", 1)
        capture.press("Alt", 3)
        self.assertTrue(capture.press("K", 3))
        self.assertTrue(capture.ready)
        self.assertFalse(capture.press("F24"))
        self.assertFalse(capture.release("Alt"))
        self.assertEqual(capture.candidate, EditorBinding("K", True, True))
        self.assertEqual(binding_snapshot(self.settings), self.before)
        proposed = capture.settings_for(self.settings)
        self.assertEqual(binding_snapshot(proposed), self.before)

    def test_conflict_names_actions_and_does_not_displace_either(self):
        capture = BindingCapture(self.settings, "capture")
        self.assertFalse(capture.press("F8"))
        self.assertIn("Capture camera", capture.error)
        self.assertIn("Toggle Dolly panel", capture.error)
        self.assertTrue(capture.listening)
        self.assertFalse(capture.ready)
        self.assertEqual(binding_snapshot(self.settings), self.before)
        self.assertTrue(capture.press("Mouse5"))
        result = capture.settings_for(self.settings)
        self.assertEqual(result.action_bindings["capture"], EditorBinding("Mouse5"))
        self.assertEqual(result.action_bindings["panel"], self.settings.action_bindings["panel"])
        self.assertEqual(result.capture_binding.key, "Mouse5")

    def test_conflicting_chord_modifier_release_cannot_replace_candidate(self):
        capture = BindingCapture(self.settings, "move_down")
        capture.press("Alt", 2)
        self.assertFalse(capture.press("G", 2))  # Framing guide owns Alt+G.
        self.assertFalse(capture.release("Alt"))
        self.assertIsNone(capture.candidate)
        self.assertTrue(capture.listening)
        self.assertIn("framing", capture.error)

    def test_f7_remains_reserved_with_and_without_modifiers(self):
        for bits in (0, 1, 2, 4, 7):
            capture = BindingCapture(self.settings, "panel")
            self.assertFalse(capture.press("F7", bits))
            self.assertIn("F7 is reserved", capture.error)
            self.assertTrue(capture.listening)
            with self.assertRaisesRegex(ValueError, "Record a shortcut"):
                capture.settings_for(self.settings)
        self.assertEqual(binding_snapshot(self.settings), self.before)

    def test_escape_cancels_while_explicit_escape_preserves_supported_chords(self):
        capture = BindingCapture(self.settings, "panel")
        self.assertFalse(capture.press("Escape", 3))
        self.assertTrue(capture.cancelled)
        self.assertFalse(capture.bind_escape())
        capture.retry()
        self.assertFalse(capture.listening)
        for bits in (0, 1, 2, 4, 7):
            capture = BindingCapture(self.settings, "panel")
            self.assertTrue(capture.bind_escape(bits))
            self.assertEqual(capture.settings_for(self.settings).action_bindings["panel"].modifiers, bits)

    def test_modifier_alone_only_settles_for_movement_on_release(self):
        for action, key in (("move_down", "Ctrl"), ("move_fast", "Shift"), ("move_slow", "Alt")):
            with self.subTest(action=action):
                capture = BindingCapture(self.settings, action)
                self.assertFalse(capture.press(key))
                self.assertFalse(capture.press(key))  # autorepeat
                self.assertFalse(capture.ready)
                self.assertTrue(capture.release(key))
                self.assertEqual(capture.candidate, EditorBinding(key))
                self.assertFalse(capture.release(key))
        for action in ("capture", "panel", "reshade"):
            capture = BindingCapture(self.settings, action)
            capture.press("Ctrl")
            self.assertFalse(capture.release("Ctrl"))
            self.assertIn("not a modifier alone", capture.error)

    def test_multiple_modifiers_are_not_guessed_as_a_standalone_bind(self):
        capture = BindingCapture(self.settings, "move_down")
        capture.press("Ctrl", 1)
        capture.press("Shift", 5)
        capture.release("Shift")
        capture.release("Ctrl")
        self.assertFalse(capture.ready)
        self.assertTrue(capture.listening)

    def test_windows_chord_is_not_silently_recorded_without_its_modifier(self):
        capture = BindingCapture(self.settings, "panel")
        capture.press("Win_L")
        capture.press("Win_R")
        self.assertFalse(capture.press("F24"))
        self.assertIn("Windows", capture.error)
        capture.release("Win_L")
        self.assertFalse(capture.press("F24"))
        self.assertFalse(capture.bind_escape())
        capture.release("Win_R")
        self.assertTrue(capture.press("F24"))
        self.assertEqual(capture.candidate, EditorBinding("F24"))

    def test_focus_loss_or_unsupported_chord_prevents_modifier_release_guess(self):
        for change in (lambda capture: capture.focus_lost(), lambda capture: capture.press(None, 1)):
            capture = BindingCapture(self.settings, "move_down")
            capture.press("Ctrl")
            change(capture)
            self.assertFalse(capture.release("Ctrl"))
            self.assertFalse(capture.ready)
            self.assertTrue(capture.listening)

    def test_retry_and_cancel_never_apply_reviewed_candidate(self):
        capture = BindingCapture(self.settings, "panel")
        capture.press("F24")
        capture.retry()
        self.assertIsNone(capture.candidate)
        with self.assertRaises(ValueError):
            capture.settings_for(self.settings)
        capture.press("Mouse4")
        capture.cancel()
        with self.assertRaises(ValueError):
            capture.settings_for(self.settings)
        self.assertEqual(binding_snapshot(self.settings), self.before)

    def test_every_available_action_uses_same_proposal_validator(self):
        for action in (*BINDABLE_ORDER, "reshade"):
            if action == "object_picker":
                with self.assertRaisesRegex(ValueError, "not available"):
                    BindingCapture(self.settings, action)
                continue
            with self.subTest(action=action):
                capture = BindingCapture(self.settings, action)
                self.assertTrue(capture.press("F24"))
                result = capture.settings_for(self.settings)
                actual = result.reshade_binding if action == "reshade" else result.action_bindings[action]
                self.assertEqual(actual, EditorBinding("F24"))
                for name, binding in self.settings.action_bindings.items():
                    if name != action:
                        self.assertEqual(result.action_bindings[name], binding)

    def test_every_supported_nonmodifier_key_can_be_recorded_without_conflicts(self):
        empty = self.settings.with_reshade_binding(None).with_action_bindings({name: None for name in BINDABLE_ORDER})
        for key in EDITOR_KEY_CHOICES:
            if key in ("Ctrl", "Alt", "Shift"):
                continue
            capture = BindingCapture(empty, "panel")
            result = capture.bind_escape() if key == "Escape" else capture.press(key)
            self.assertTrue(result, (key, capture.error))
            self.assertEqual(capture.candidate.key, key)

    def test_capture_rejects_editor_only_punctuation_without_changing_alias(self):
        capture = BindingCapture(self.settings, "capture")
        self.assertFalse(capture.press("LeftBracket"))
        self.assertFalse(capture.ready)
        self.assertEqual(self.settings.capture_binding, AppSettings().capture_binding)

    def test_reshade_conflicts_are_checked_in_both_directions(self):
        for action, key in (("panel", "F11"), ("reshade", "F8")):
            capture = BindingCapture(self.settings, action)
            self.assertFalse(capture.press(key))
            self.assertIn("ReShade menu", capture.error)
            self.assertIn("Toggle Dolly panel", capture.error)
        self.assertEqual(binding_snapshot(self.settings), self.before)

    def test_stale_binding_snapshot_rejects_save_but_keeps_other_current_preferences(self):
        capture = BindingCapture(self.settings, "panel")
        capture.press("F24")
        changed = binding_settings(self.settings, "capture", EditorBinding("Mouse4"))
        with self.assertRaisesRegex(ValueError, "Controls changed"):
            capture.settings_for(changed)
        changed_menu = self.settings.with_reshade_binding(None)
        with self.assertRaisesRegex(ValueError, "Controls changed"):
            capture.settings_for(changed_menu)
        fresh = replace(self.settings, mouse_sensitivity=.25, export_folder="D:/Fixtures", pause_after_capture=True)
        result = capture.settings_for(fresh)
        self.assertEqual(result.mouse_sensitivity, .25)
        self.assertEqual(result.export_folder, "D:/Fixtures")
        self.assertTrue(result.pause_after_capture)

    def test_snapshot_is_detached_even_if_external_binding_dictionary_mutates(self):
        capture = BindingCapture(self.settings, "panel")
        self.settings.action_bindings["capture"] = None
        self.assertTrue(capture.press("F24"))
        with self.assertRaisesRegex(ValueError, "Controls changed"):
            capture.settings_for(self.settings)

    def test_clear_capture_and_reset_rebind_roundtrip_without_reenabling(self):
        cleared = binding_settings(self.settings, "capture", None)
        self.assertIsNone(cleared.action_bindings["capture"])
        self.assertEqual(cleared.capture_binding, self.settings.capture_binding)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            save_settings(cleared, path)
            self.assertIsNone(load_settings(path).action_bindings["capture"])
            capture = BindingCapture(load_settings(path), "capture")
            self.assertTrue(capture.press("MiddleMouse", 4))
            save_settings(capture.settings_for(load_settings(path)), path)
            actual = load_settings(path)
            self.assertEqual(actual.action_bindings["capture"], EditorBinding("MiddleMouse", shift=True))
            self.assertEqual(actual.capture_binding.key, "MiddleMouse")
            self.assertTrue(actual.capture_binding.shift)

    def test_unknown_control_and_invalid_bits_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "existing control"):
            binding_settings(self.settings, "bogus", None)
        for bits in (-1, 8, True, "Ctrl"):
            capture = BindingCapture(self.settings, "panel")
            self.assertFalse(capture.press("F24", bits))
            self.assertTrue(capture.error)


class TkEventTranslationTests(unittest.TestCase):
    def test_supported_punctuation_shifted_digits_and_modifiers(self):
        for symbol, expected in (("comma", "Comma"), ("less", "Comma"), ("period", "Period"),
                                 ("minus", "Minus"), ("underscore", "Minus"), ("equal", "Equals"),
                                 ("bracketleft", "LeftBracket"), ("braceright", "RightBracket"),
                                 ("exclam", "1"), ("parenright", "0"), ("Control_R", "Ctrl"),
                                 ("a", "A"), ("Next", "PageDown"), ("F24", "F24"), ("F7", "F7")):
            self.assertEqual(key_from_event(SimpleNamespace(keysym=symbol, num="??")), expected)
        self.assertEqual(modifiers_from_event(SimpleNamespace(state=0x4 | 0x20000 | 0x1), platform="win32"), 7)
        self.assertEqual(modifiers_from_event(SimpleNamespace(state=0x4 | 0x8 | 0x1), platform="linux"), 7)
        self.assertEqual(modifiers_from_event(SimpleNamespace(state=0x4 | 0x8 | 0x1), platform="win32"), 5)
        self.assertEqual(modifiers_from_event(SimpleNamespace(state=0x100 | 0x200 | 0x10 | 0x8 | 0x2), platform="win32"), 0)

    def test_windows_uses_native_virtual_key_independently_of_printed_layout_character(self):
        for code, symbol, expected in ((0x32, "quotedbl", "2"), (0xDB, "udiaeresis", "LeftBracket"),
                                       (0xBC, "semicolon", "Comma"), (0x5B, "??", "Win_L"),
                                       (0x76, "??", "F7"), (0x72, "F3", "F3"),
                                       (0xBA, "semicolon", None), (0xA0, "Shift_L", None)):
            self.assertEqual(key_from_event(SimpleNamespace(keysym=symbol, keycode=code), platform="win32"), expected)

    def test_primary_and_wheel_buttons_never_become_keyboard_or_side_binds(self):
        for platform in ("win32", "linux"):
            for number in (1, 3, 4, 5):
                self.assertIsNone(key_from_event(SimpleNamespace(num=number, keysym="K"), platform=platform))
            self.assertEqual(key_from_event(SimpleNamespace(num=2), platform=platform), "MiddleMouse")
        self.assertEqual(key_from_event(SimpleNamespace(num=8), platform="linux"), "Mouse4")
        self.assertEqual(key_from_event(SimpleNamespace(num=9), platform="linux"), "Mouse5")
        self.assertEqual(key_from_event(SimpleNamespace(keysym="Super_L")), "Super_L")
        self.assertIsNone(key_from_event(SimpleNamespace(keysym="semicolon")))


class FakeDialog:
    def __init__(self):
        self.exists = True
        self.callbacks = {}
        self.bindings = {}
        self.next_token = 0

    def winfo_exists(self):
        return self.exists

    def winfo_id(self):
        return 123

    def bind(self, name, callback, add):
        self.bindings[name] = callback
        return "destroy-binding"

    def unbind(self, name, token):
        self.bindings.pop(name, None)

    def after(self, delay, callback):
        self.next_token += 1
        self.callbacks[self.next_token] = callback
        return self.next_token

    def after_cancel(self, token):
        self.callbacks.pop(token, None)

    def tick(self):
        callbacks = tuple(self.callbacks.values())
        self.callbacks.clear()
        for callback in callbacks:
            callback()


class FakeSideMouseAPI:
    def __init__(self):
        self.owns_focus = True
        self.keys = set()
        self.focus_answers = []
        self.down_calls = []

    def focused(self, hwnd):
        assert hwnd == 123
        return self.focus_answers.pop(0) if self.focus_answers else self.owns_focus

    def down(self, vk):
        self.down_calls.append(vk)
        return vk in self.keys


class SideMouseCaptureTests(unittest.TestCase):
    def setUp(self):
        self.dialog = FakeDialog()
        self.api = FakeSideMouseAPI()
        self.calls = []
        self.listener = SideMouseCapture(self.dialog, lambda *args: self.calls.append(args), api=self.api)
        self.addCleanup(self.listener.stop)

    def test_release_then_press_records_each_side_once_with_current_modifiers(self):
        self.assertTrue(self.listener.start())
        self.api.keys = {5, 0x11, 0x10}
        self.dialog.tick()
        self.dialog.tick()
        self.assertEqual(self.calls, [("Mouse4", 5)])
        self.api.keys.clear()
        self.dialog.tick()
        self.api.keys = {6, 0x12}
        self.dialog.tick()
        self.assertEqual(self.calls, [("Mouse4", 5), ("Mouse5", 2)])

    def test_held_on_open_or_refocus_cannot_record_until_fresh_release(self):
        self.api.keys = {5}
        self.listener.start()
        self.dialog.tick()
        self.assertEqual(self.calls, [])
        self.api.keys.clear()
        self.dialog.tick()
        self.api.owns_focus = False
        self.dialog.tick()
        self.api.keys = {5}
        self.api.owns_focus = True
        self.dialog.tick()
        self.assertEqual(self.calls, [])
        self.api.keys.clear()
        self.dialog.tick()
        self.api.keys = {5}
        self.dialog.tick()
        self.assertEqual(self.calls, [("Mouse4", 0)])

    def test_press_outside_dialog_and_late_focus_loss_cannot_record(self):
        self.listener.start()
        self.api.owns_focus = False
        self.api.keys = {6}
        self.api.down_calls.clear()
        self.dialog.tick()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.api.down_calls, [])
        self.api.keys.clear()
        self.api.owns_focus = True
        self.dialog.tick()
        self.api.keys = {6}
        self.api.focus_answers = [True, False]
        self.dialog.tick()
        self.assertEqual(self.calls, [])

    def test_windows_key_blocks_and_requires_release_again(self):
        self.listener.start()
        self.api.keys = {5, 0x5B}
        self.dialog.tick()
        self.api.keys = {5}
        self.dialog.tick()
        self.assertEqual(self.calls, [])
        self.api.keys.clear()
        self.dialog.tick()
        self.api.keys = {5}
        self.dialog.tick()
        self.assertEqual(self.calls, [("Mouse4", 0)])

    def test_keyboard_guard_sees_windows_key_held_before_dialog_open(self):
        self.api.keys = {0x5C}
        self.listener.start()
        self.assertTrue(self.listener.keyboard_blocked())
        self.api.keys.clear()
        self.assertFalse(self.listener.keyboard_blocked())
        self.api.owns_focus = False
        self.assertTrue(self.listener.keyboard_blocked())
        self.api.owns_focus = True
        self.dialog.exists = False
        self.assertTrue(self.listener.keyboard_blocked())

    def test_callback_can_stop_before_other_simultaneous_button_or_reschedule(self):
        self.listener.callback = lambda *args: (self.calls.append(args), self.listener.stop())
        self.listener.start()
        self.api.keys = {5, 6}
        self.dialog.tick()
        self.assertEqual(self.calls, [("Mouse4", 0)])
        self.assertFalse(self.listener.running)
        self.assertEqual(self.dialog.callbacks, {})
        self.assertEqual(self.dialog.bindings, {})

    def test_stop_and_destroy_remove_callbacks_without_late_record(self):
        self.listener.start()
        pending = next(iter(self.dialog.callbacks.values()))
        self.listener.stop()
        self.api.keys = {5}
        pending()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.dialog.callbacks, {})
        self.listener.start()
        self.dialog.bindings["<Destroy>"](SimpleNamespace(widget=self.dialog))
        self.assertFalse(self.listener.running)
        self.assertEqual(self.dialog.callbacks, {})

    def test_invisible_destroyed_dialog_stops_without_polling_input(self):
        self.listener.start()
        self.dialog.exists = False
        self.dialog.tick()
        self.assertFalse(self.listener.running)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.dialog.callbacks, {})

    def test_windows_ownership_requires_same_valid_root_hwnd(self):
        api = _WindowsSideMouseAPI.__new__(_WindowsSideMouseAPI)
        api.user32 = SimpleNamespace(
            IsWindow=lambda hwnd: hwnd == 123,
            GetAncestor=lambda hwnd, flag: {123: 900, 456: 900, 789: 901}.get(hwnd, 0),
            GetForegroundWindow=lambda: 456)
        self.assertTrue(api.focused(123))  # Native wrapper/descendant of this dialog.
        api.user32.GetForegroundWindow = lambda: 789
        self.assertFalse(api.focused(123))  # Another Dolly window is insufficient.
        api.user32.GetForegroundWindow = lambda: 0
        self.assertFalse(api.focused(123))
        self.assertFalse(api.focused(999))


if __name__ == "__main__":
    unittest.main()
