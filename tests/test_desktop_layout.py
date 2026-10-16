"""Real Tk layout transitions, without game commands or user preference writes."""
import copy
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
from dolly.gui import DollyApp
from dolly.settings import AppSettings
from dolly.path import Keyframe

class DesktopLayoutTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.root.withdraw()
        self.submit = patch.object(DollyApp, "_submit").start()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.export_folder = Path(directory.name) / 'Remembered exports'
        self.settings = patch.object(DollyApp, "_load_app_settings",
            return_value=AppSettings(export_folder=str(self.export_folder))).start()
        patch("dolly.graphics_profiles.load_library", return_value={"format": 1, "selected": "", "profiles": []}).start()
        self.addCleanup(patch.stopall)
        self.app = DollyApp(self.root)
        self.addCleanup(self.close_app)

    def close_app(self):
        self.app.closed = True
        self.app.jobs.put(None)
        for timer in self.root.tk.splitlist(self.root.tk.call("after", "info")):
            self.root.tk.call("after", "cancel", timer)
        self.root.destroy()

    def test_old_reduced_preference_does_not_hide_pages_or_change_shot(self):
        from tkinter import ttk
        app = self.app
        self.assertFalse(app.app_settings.full_editor)
        app.project.keyframes = [Keyframe(0, 1, 2, 3, 4, 5, 6)]
        app.dirty = True
        app.video_layer_players.set(True)
        before = copy.deepcopy(app.project)
        app.notebook.select(app.camera_tab)
        for busy in (False, True):
            app.busy = busy
            app.full_editor.set(False)  # An older internal caller cannot hide tools.
            with patch("dolly.gui.save_settings") as save:
                app._toggle_full_editor()
            save.assert_not_called()
            self.assertTrue(app.full_editor.get())
            self.assertEqual(app.notebook.select(), str(app.camera_tab))
        self.assertEqual(app.project, before)
        self.assertTrue(app.dirty)
        self.assertTrue(app.video_layer_players.get())
        self.assertEqual(app.notebook.tab(app.camera_tab, "state"), "normal")
        self.assertEqual(app.notebook.tab(app.cvar_tab, "state"), "normal")
        self.assertEqual(len(app.navigation), 6)
        def children(parent):
            for child in parent.winfo_children():
                yield child
                yield from children(child)
        self.assertFalse([widget for widget in children(self.root)
                          if isinstance(widget, ttk.Checkbutton) and widget.cget("text") == "Full editor"])
        self.assertFalse(app.app_settings.full_editor, "Opening the editor must not rewrite preferences.")

    def test_controls_shortcut_keeps_all_pages_available(self):
        self.app._show_keybinds("reshade")
        self.assertEqual(self.app.notebook.select(), str(self.app.controls_tab))
        self.assertEqual(self.app.controls_view.search.get(), "")
        self.assertIn("reshade", self.app.controls_view.binding_buttons)
        self.assertTrue(self.app.full_editor.get())

    def test_editing_start_opens_camera_without_requiring_a_mode_switch(self):
        self.app.notebook.select(self.app.setup_tab)
        with patch("dolly.gui.editor_session.configure"):
            self.app._editing_started(None)
        self.assertEqual(self.app.notebook.select(), str(self.app.camera_tab))
        self.assertEqual(self.app.notebook.tab(self.app.setup_tab, "state"), "normal")

    def test_mouse_wheel_scrolls_page_without_changing_closed_option(self):
        self.root.deiconify(); self.root.geometry("1000x700")
        self.app.notebook.select(self.app.export_tab); self.root.update()
        combo = self.app.video_fps_combo
        value = combo.get(); page = self.app.export_page.canvas
        page.yview_moveto(0); self.root.update()
        before = page.yview()
        combo.event_generate("<MouseWheel>", delta=-120); self.root.update()
        self.assertEqual(combo.get(), value)
        self.assertGreater(page.yview()[0], before[0])
        # Explicit dropdown selection remains available.
        combo.current(2); combo.event_generate("<<ComboboxSelected>>")
        self.assertEqual(self.app.video_fps.get(), "120")

    def test_export_cards_align_when_encoder_options_expand(self):
        from dolly.gui_layout import Disclosure
        self.root.deiconify(); self.root.geometry("1180x800")
        self.app.notebook.select(self.app.export_tab); self.root.update()
        left, right = self.app.export_passes_card, self.app.export_capture_card
        for expanded in (False, True):
            for child in right.winfo_children():
                if isinstance(child, Disclosure): child.set_open(expanded)
            self.root.update()
            self.assertEqual(left.winfo_rooty(), right.winfo_rooty())
            self.assertEqual(left.winfo_height(), right.winfo_height())

    def test_launch_setup_inherits_card_surface_through_nested_fields(self):
        from dolly.gui_layout import Disclosure
        from tkinter import ttk
        combo = self.app.home_camera_driver_combo
        frame = combo.master
        while not isinstance(frame, Disclosure):
            self.assertEqual(ttk.Style(frame).lookup(frame.cget("style"), "background"),
                             ttk.Style(frame).lookup("Card.TFrame", "background"))
            frame = frame.master
        self.assertEqual(str(frame.toggle.cget("style")), "Disclosure.Card.TButton")

    def test_graphics_profile_selector_is_available_with_current_settings_default(self):
        from dolly.graphics_profiles import CURRENT
        self.assertEqual(self.app.graphics_profiles.selection.get(), CURRENT)
        self.assertEqual(tuple(self.app.graphics_profiles.combo.cget("values")), (CURRENT,))
        self.assertIn("next launch", self.app.graphics_profiles.status.get())


class GraphicsProfileStartupFailureTests(unittest.TestCase):
    def test_damaged_profile_library_reports_error_after_window_finishes_building(self):
        from dolly.launcher import LaunchError
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        root.withdraw()
        app = None
        try:
            with patch.object(DollyApp, '_submit'), \
                 patch.object(DollyApp, '_load_app_settings', return_value=AppSettings()), \
                 patch('dolly.graphics_profiles.load_library', side_effect=LaunchError('Damaged profile library')), \
                 patch('dolly.gui.dialogs.show_error') as show:
                app = DollyApp(root)
                self.assertTrue(hasattr(app, 'log_widget'))
                root.update_idletasks()
                show.assert_called_once()
                self.assertIn('Damaged profile library', app.graphics_profiles.status.get())
                self.assertIn('Damaged profile library', app.log_widget.get('1.0', 'end'))
        finally:
            if app is not None:
                app.closed = True
                app.jobs.put(None)
            for timer in root.tk.splitlist(root.tk.call('after', 'info')):
                root.tk.call('after', 'cancel', timer)
            root.destroy()
