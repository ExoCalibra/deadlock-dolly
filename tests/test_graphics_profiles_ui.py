"""Graphics panel behavior with isolated files, dialogs and process inventory."""
from dolly import game_processes
import gc
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from dolly import graphics_profiles as profiles, launcher
from dolly.graphics_profiles_ui import GraphicsProfiles

VIDEO = b'"video.cfg" { "Version" "20" "setting.r_effects_bloom" "1" "setting.defaultres" "2560" }'


class GraphicsPanelTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.root.withdraw()
        self.errors = []
        self.addCleanup(self.close_panel)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.video = self.folder / 'video.txt'
        self.video.write_bytes(VIDEO)
        self.library = self.folder / 'profiles.json'
        self.patch(profiles, 'library_path', return_value=self.library)
        self.panel = GraphicsProfiles(ttk.Frame(self.root), root=self.root, on_error=lambda *args: self.errors.append(args))

    def close_panel(self):
        # Registered first so patched methods release their callbacks before Tk.
        self.root.destroy()
        self.panel = None
        self.root = None
        self.errors.clear()  # Exceptions can retain panel frames through tracebacks.
        gc.collect()  # Finalize the unreachable Tk graph on its creating thread.

    def patch(self, obj, name, **kwargs):
        mock = patch.object(obj, name, **kwargs)
        self.addCleanup(mock.stop)
        return mock.start()

    def save_profile(self):
        profile = profiles.profile_from_bytes('Recording', VIDEO)
        profiles.save_library({'format': 1, 'selected': profile['id'], 'profiles': [profile]})
        self.panel.refresh()
        return profile

    def test_preview_precedes_save_and_confirmation_rereads_library(self):
        from dolly.graphics_profiles_ui import simpledialog
        self.patch(simpledialog, 'askstring', return_value=' Recording ')
        preview = self.patch(self.panel, 'show_preview')
        self.panel.add(self.video)
        self.assertFalse(self.library.exists())
        title, text, commit = preview.call_args.args
        self.assertEqual(title, 'Save graphics profile')
        self.assertIn('Effects bloom: 1', text)
        self.assertIn('setting.defaultres', text)
        self.assertIn('version', text)
        external = profiles.profile_from_bytes('Other', VIDEO)
        profiles.save_library({'format': 1, 'selected': '', 'profiles': [external]})
        commit()
        stored = profiles.load_library()
        self.assertEqual([p['name'] for p in stored['profiles']], ['Other', 'Recording'])
        self.assertEqual(stored['selected'], stored['profiles'][1]['id'])
        self.assertEqual(self.panel.selection.get(), 'Recording')
        self.assertEqual(self.video.read_bytes(), VIDEO)

    def test_cancelled_name_creates_no_profile_or_preview(self):
        from dolly.graphics_profiles_ui import simpledialog
        self.patch(simpledialog, 'askstring', return_value=None)
        preview = self.patch(self.panel, 'show_preview')
        self.panel.add(self.video)
        preview.assert_not_called()
        self.assertFalse(self.library.exists())

    def test_unreadable_source_fails_before_name_prompt(self):
        from dolly.graphics_profiles_ui import simpledialog
        prompt = self.patch(simpledialog, 'askstring')
        self.panel.run(lambda: self.panel.add(self.folder / 'missing.txt'))
        prompt.assert_not_called()
        self.assertEqual(self.errors[0][0], 'Graphics profiles')
        self.assertIsInstance(self.errors[0][1], (OSError, profiles.LaunchError))
        self.assertIn('missing.txt', str(self.errors[0][1]))
        self.assertEqual(self.panel.status.get(), str(self.errors[0][1]))

    def test_active_game_refuses_capture_before_resolving_or_reading_video(self):
        self.patch(game_processes, 'running_processes', return_value=['fixture'])
        guard = self.patch(game_processes, '_game_is_running', return_value=True)
        current = self.patch(profiles, 'current_video')
        self.panel.run(self.panel.capture)
        guard.assert_called_once_with(['fixture'])
        current.assert_not_called()
        self.assertEqual(str(self.errors[0][1]), 'Close Deadlock before saving its graphics profile, so the file contains its final saved settings.')
        self.assertFalse(self.library.exists())

    def test_stopped_game_capture_resolves_current_source_then_adds_it(self):
        self.patch(game_processes, 'running_processes', return_value=[])
        self.patch(game_processes, '_game_is_running', return_value=False)
        self.patch(profiles, 'current_video', return_value=self.video)
        add = self.patch(self.panel, 'add')
        self.panel.capture()
        add.assert_called_once_with(self.video)

    def test_removed_choice_is_rejected_after_disk_reread(self):
        self.save_profile()
        profiles.save_library({'format': 1, 'selected': '', 'profiles': []})
        self.panel.run(self.panel.select)
        self.assertEqual(str(self.errors[0][1]), 'Graphics profile changed outside this window. Reopen Settings and choose a profile.')
        self.assertEqual(profiles.load_library()['profiles'], [])

    def test_select_current_preserves_profiles_and_clears_selected_id(self):
        profile = self.save_profile()
        self.panel.selection.set(profiles.CURRENT)
        self.panel.select()
        self.assertEqual(profiles.load_library(), {'format': 1, 'selected': '', 'profiles': [profile]})
        self.assertEqual(self.panel.selection.get(), profiles.CURRENT)

    def test_preview_does_not_modify_source_or_library(self):
        self.save_profile()
        self.patch(profiles, 'current_video', return_value=self.video)
        preview = self.patch(self.panel, 'show_preview')
        before = self.library.read_bytes()
        self.panel.preview()
        self.assertEqual(preview.call_args.args[0], 'Next-launch graphics preview')
        self.assertIn('No game files are changed', preview.call_args.args[1])
        self.assertEqual(len(preview.call_args.args), 2)
        self.assertEqual(self.library.read_bytes(), before)
        self.assertEqual(self.video.read_bytes(), VIDEO)

    def test_failed_save_keeps_disk_and_reports_error_without_refresh(self):
        from dolly.graphics_profiles_ui import simpledialog
        self.save_profile()
        before = self.library.read_bytes()
        self.patch(simpledialog, 'askstring', return_value='Renamed')
        self.patch(profiles, 'save_library', side_effect=OSError('fixture write refusal'))
        refresh = self.patch(self.panel, 'refresh')
        self.panel.run(self.panel.rename)
        refresh.assert_not_called()
        self.assertEqual(str(self.errors[0][1]), 'fixture write refusal')
        self.assertEqual(self.library.read_bytes(), before)

    def test_delete_confirmation_and_cancellation_keep_original_selection_policy(self):
        from dolly.graphics_profiles_ui import messagebox
        self.save_profile()
        before = self.library.read_bytes()
        confirm = self.patch(messagebox, 'askyesno', return_value=False)
        self.panel.delete()
        self.assertEqual(self.library.read_bytes(), before)
        confirm.return_value = True
        self.panel.delete()
        self.assertEqual(profiles.load_library(), {'format': 1, 'selected': '', 'profiles': []})
        self.assertEqual(self.panel.selection.get(), profiles.CURRENT)
