"""Graphics library, file ownership and actual launcher/recovery boundaries."""
from dolly import game_processes
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import uuid

from dolly import graphics_profiles as gp, launcher, session_cleanup
from test_launcher import fake_game, editing_fixture, GAMEINFO


VIDEO = b'''\xef\xbb\xbf"video.cfg"\r
{\r
    "Version" "20"\r
    "VendorID" "4318" // machine identity must remain\r
    "setting.defaultres" "1920"\r
    "setting.defaultresheight" "1080"\r
    "setting.fullscreen" "0"\r
    "setting.r_citadel_upscaling" "0"\r
    "setting.r_citadel_shadow_quality" "0" // keep this comment\r
    "setting.r_effects_bloom" "false"\r
    "future_setting" "preserve unknown fields"\r
}\r
'''
RECORDING = VIDEO.replace(b'quality" "0"', b'quality" "2"').replace(b'bloom" "false"', b'bloom" "true"')


class ProfileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.library = self.root / "graphics-profiles.json"
        self.patch(gp, "library_path", return_value=self.library)
        self.profile = gp.profile_from_bytes("Recording", RECORDING)

    def patch(self, obj, name, **kwargs):
        p = patch.object(obj, name, **kwargs)
        self.addCleanup(p.stop)
        return p.start()

    def save(self):
        gp.save_library({"format": 1, "selected": self.profile["id"], "profiles": [self.profile]})

    def test_default_library_is_opt_in_and_does_not_create_a_file(self):
        self.assertEqual(gp.load_library()["selected"], "")
        self.assertFalse(self.library.exists())

    def test_library_roundtrip_and_profile_rename_delete(self):
        self.save()
        library = gp.load_library()
        self.assertEqual(library["profiles"], [self.profile])
        library["profiles"][0]["name"] = "High quality"
        gp.save_library(library)
        self.assertEqual(gp.load_library()["profiles"][0]["name"], "High quality")
        library.update(selected="", profiles=[])
        gp.save_library(library)
        self.assertEqual(gp.load_library()["profiles"], [])

    def test_preview_only_changes_allowlisted_values_and_preserves_exact_format(self):
        output, changes = gp.preview(self.profile, VIDEO)
        self.assertEqual(output, RECORDING)
        self.assertEqual(len(changes), 2)
        self.assertEqual(set(self.profile["values"]), {"setting.r_citadel_shadow_quality", "setting.r_effects_bloom"})

    def test_imported_machine_values_are_never_applied(self):
        foreign = RECORDING.replace(b'"1920"', b'"640"').replace(b'"4318"', b'"9999"')
        profile = gp.profile_from_bytes("Imported", foreign)
        self.assertEqual(gp.preview(profile, VIDEO)[0], RECORDING)

    def test_malformed_nested_duplicate_conditional_and_future_formats_refused(self):
        cases = [VIDEO.replace(b'"20"', b'"21"'), VIDEO[:-5], b'"video.cfg" { "Version" "20" nested { x y } }',
                 VIDEO.replace(b'"Version" "20"', b'"Version" "20" "VERSION" "20"'),
                 VIDEO.replace(b'"Version" "20"', b'"Version" "20" [$WIN32]'),
                 VIDEO + b' include "another-file"', b'\xff', b'x' * (gp.MAX_BYTES + 1)]
        for data in cases:
            with self.subTest(data=data[:80]), self.assertRaises(launcher.LaunchError):
                gp.profile_from_bytes("Bad", data)

    def test_missing_destination_field_is_not_inserted(self):
        data = VIDEO.replace(b'    "setting.r_effects_bloom" "false"\r\n', b'')
        with self.assertRaisesRegex(launcher.LaunchError, "lacks profile settings"):
            gp.preview(self.profile, data)

    def test_profiles_cannot_contain_commands_or_unknown_keys(self):
        for key, value in [("setting.fullscreen", "1"), ("setting.r_effects_bloom", "true;quit"),
                           ("setting.r_effects_bloom", "NaN"), ("setting.r_effects_bloom", "1e999")]:
            profile = deepcopy(self.profile)
            profile["values"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(launcher.LaunchError):
                gp.preview(profile, VIDEO)

    def test_library_rejects_duplicates_and_preserves_damaged_file(self):
        damaged = b'{"format":1,"format":1,"selected":"","profiles":[]}'
        self.library.write_bytes(damaged)
        with self.assertRaises(launcher.LaunchError):
            gp.load_library()
        self.assertEqual(self.library.read_bytes(), damaged)
        self.save()
        before = self.library.read_bytes()
        for mutate in (lambda d: d["profiles"].append(deepcopy(self.profile)),
                       lambda d: d.update(selected="missing"),
                       lambda d: d["profiles"][0].update(name=gp.CURRENT),
                       lambda d: d["profiles"][0].update(name="../bad\nname"),
                       lambda d: d.update(profiles=[self.profile] * (gp.MAX_PROFILES + 1))):
            library = gp.load_library()
            mutate(library)
            with self.assertRaises(launcher.LaunchError):
                gp.save_library(library)
            self.assertEqual(self.library.read_bytes(), before)

    def test_only_exact_recorded_account_config_can_be_resolved(self):
        target = self.root / "userdata/123/1422450/local/cfg/video.txt"
        target.parent.mkdir(parents=True)
        target.write_bytes(VIDEO)
        self.assertEqual(gp.video_path("123", self.root), target)
        for account in ("0", "../123", "0123", "4294967296", 123, "123/other"):
            with self.subTest(account=account), self.assertRaises(launcher.LaunchError):
                gp.video_path(account, self.root)
        with patch.object(gp, "_plain_ancestors", return_value=False), self.assertRaises(launcher.LaunchError):
            gp.video_path("123", self.root)

    @unittest.skipUnless(os.name == "nt", "Windows Steam registry")
    def test_steam_registry_requires_active_account_and_existing_plain_root(self):
        import winreg
        (self.root / "steam.exe").write_bytes(b"fixture")
        with patch.object(winreg, "OpenKey", return_value=MagicMock()), patch.object(winreg, "QueryValueEx") as query:
            query.return_value = (str(self.root), 1)
            self.assertEqual(gp.steam_root(), self.root)
            for value in (0, -1, True, "123", 2**32):
                query.return_value = (value, 4)
                with self.subTest(value=value), self.assertRaises(launcher.LaunchError):
                    gp.active_account()
            query.return_value = (123, 4)
            self.assertEqual(gp.active_account(), "123")

    def test_gui_selection_is_forwarded_as_next_launch_option(self):
        from dolly.graphics_profiles_ui import GraphicsProfiles, launch_options
        self.save()
        panel = object.__new__(GraphicsProfiles)
        panel.selection = SimpleNamespace(get=lambda: "Recording")
        self.assertEqual(launch_options(SimpleNamespace(graphics_profiles=panel)), {"graphics_profile": self.profile["id"]})
        panel.selection.get = lambda: gp.CURRENT
        self.assertEqual(launch_options(SimpleNamespace(graphics_profiles=panel)), {})
        self.assertEqual(launch_options(SimpleNamespace()), {})
        panel.selection.get = lambda: "Deleted profile"
        with self.assertRaises(launcher.LaunchError):
            panel.selected_id()


class LegacyGraphicsRecoveryTests(unittest.TestCase):
    """Retain recovery proof for real journals created by the old swap design."""
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.paths = fake_game(self.root / "Deadlock")
        self.package = self.root / "Dolly"
        self.target = self.root / "Steam/userdata/123/1422450/local/cfg/video.txt"
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(VIDEO)
        self.patch(gp, "steam_root", return_value=self.root / "Steam")
        self.account = self.patch(gp, "active_account", return_value="123")
        self.patch(gp, "library_path", return_value=self.root / "graphics-profiles.json")
        self.profile = gp.profile_from_bytes("Recording", RECORDING)
        gp.save_library({"format": 1, "selected": self.profile["id"], "profiles": [self.profile]})
        self.patch(launcher, "EDITING_ROOT", new=editing_fixture(self.paths, self.root))
        self.patch(launcher, "PACKAGE_ROOT", new=self.package)
        self.patch(launcher, "_check_runtime")
        self.processes = self.patch(game_processes, "running_processes", return_value={"steam.exe"})
        self.thread = self.patch(launcher.threading, "Thread")
        self.process = MagicMock()
        self.process.pid = 12345
        self.process.poll.return_value = None
        self.popen = self.patch(launcher.subprocess, "Popen", return_value=self.process)

    def patch(self, obj, name, **kwargs):
        p = patch.object(obj, name, **kwargs)
        self.addCleanup(p.stop)
        return p.start()

    def launch(self):
        """Create a historical mounted session through its real file owners.

        New Dolly launches isolate settings instead. This fixture deliberately
        creates the old on-disk state so its recovery contracts remain tested,
        without reviving old launch behavior inside production code.
        """
        if game_processes._game_is_running(game_processes.running_processes()):
            raise launcher.LaunchError("Deadlock is already running.")
        launcher.recover_pending(self.paths.root)
        original = self.paths.gameinfo.read_bytes()
        ident = "legacy_" + uuid.uuid4().hex[:10]
        directory = self.package / "logs" / ident
        overlay = self.paths.game_dir / ("citadel_dolly_" + ident)
        patched = launcher.make_gameinfo(original.decode("utf-8"), overlay.name).encode("utf-8")
        directory.mkdir(parents=True)
        overlay.mkdir()
        marker = {"owner": "Deadlock Dolly", "session_dir": str(directory),
                  "original_gameinfo": str(self.paths.gameinfo),
                  "original_sha256": hashlib.sha256(original).hexdigest()}
        launcher._atomic_write(overlay / ".dolly-session.json", json.dumps(marker).encode("utf-8"))
        target = overlay / "cvar_unlocker/bin/win64/server.dll"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"owned legacy fixture plugin; no game is started")
        command = launcher.build_command(self.paths, overlay, 29090)
        mode = stat.S_IMODE(self.paths.gameinfo.stat().st_mode)
        record = {**marker, "overlay_dir": str(overlay), "backup_name": "original.gameinfo.gi",
                  "patched_sha256": hashlib.sha256(patched).hexdigest(), "original_mode": mode,
                  "config_state": "prepared", "command": command, "port": 29090, "protocol": "netcon"}
        log = directory / "launch.log"
        log.write_text("Legacy graphics recovery fixture\n", encoding="utf-8")
        launcher._atomic_write(directory / "original.gameinfo.gi", original)
        launcher._save_record(directory, record)
        try:
            gp.prepare(directory, self.profile["id"])
            launcher._atomic_write(self.paths.gameinfo, patched, mode)
            record["config_state"] = "mounted"
            launcher._save_record(directory, record)
            gp.apply(directory)
            process = launcher.subprocess.Popen(command, cwd=str(self.paths.game_dir),
                stdin=launcher.subprocess.DEVNULL, stdout=launcher.subprocess.DEVNULL,
                stderr=launcher.subprocess.STDOUT, shell=False)
            record["pid"] = process.pid
            launcher._save_record(directory, record)
            return launcher.Session(process, directory, overlay, log, tuple(command), 29090)
        except (OSError, launcher.LaunchError) as exc:
            try:
                launcher._restore_session_configs(directory)
                session_cleanup.remove_overlay(overlay, self.paths, directory)
            except launcher.LaunchError as recovery:
                raise launcher.LaunchError(f"{exc}\nConfiguration recovery needs attention: {recovery}") from exc
            if isinstance(exc, launcher.LaunchError):
                raise
            raise launcher.LaunchError(str(exc)) from exc

    def close(self, session):
        self.process.poll.return_value = 0
        session.close()

    def test_new_default_launch_reads_display_but_never_replaces_player_graphics(self):
        from dolly import editing_session
        self.target.chmod(stat.S_IREAD)
        mode = stat.S_IMODE(self.target.stat().st_mode)
        try:
            session = launcher.launch(self.paths.root)
            self.assertEqual(self.target.read_bytes(), VIDEO)
            self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), mode)
            self.assertFalse((session.session_dir / gp.JOURNAL).exists())
            own = session.session_dir / editing_session.DIRECTORY
            self.assertEqual(self.popen.call_args.kwargs["env"]["USRLOCAL" + str(self.paths.citadel_dir.resolve())], str(own))
            descriptor = json.loads((session.session_dir / editing_session.JOURNAL).read_text(encoding="utf-8"))
            self.assertEqual(descriptor["root"], str(own))
            self.assertIn("setting.defaultres", descriptor["display_fields_preserved"])
            self.assertTrue((own / "cfg/video.txt").is_file())
            self.close(session)
            self.assertEqual(self.target.read_bytes(), VIDEO)
            self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), mode)
        finally:
            self.target.chmod(stat.S_IREAD | stat.S_IWRITE)

    def test_profile_stays_until_exit_and_restores_actual_original_bytes(self):
        session = self.launch()
        self.assertEqual(self.target.read_bytes(), RECORDING)
        session.restore_gameinfo()
        self.assertEqual(self.paths.gameinfo.read_bytes(), GAMEINFO.encode())
        self.assertEqual(self.target.read_bytes(), RECORDING)
        self.assertFalse(session.close())
        self.close(session)
        self.assertEqual(self.target.read_bytes(), VIDEO)
        self.assertFalse(gp.pending(session.session_dir))
        self.assertFalse(session.overlay_dir.exists())

    def test_journal_and_both_hash_checked_backups_exist_before_target_write(self):
        write = gp._atomic_write
        observed = []
        def checked(path, data, mode=None):
            if path == self.target:
                journal = next((self.package / "logs").glob("*/" + gp.JOURNAL))
                record = json.loads(journal.read_text())
                self.assertEqual(record["state"], "prepared")
                self.assertEqual((journal.parent / gp.ORIGINAL).read_bytes(), VIDEO)
                self.assertEqual((journal.parent / gp.APPLIED).read_bytes(), RECORDING)
                observed.append(path)
            return write(path, data, mode)
        with patch.object(gp, "_atomic_write", side_effect=checked):
            self.launch()
        self.assertEqual(observed, [self.target])

    def test_popen_failure_rolls_back_both_configs(self):
        self.popen.side_effect = OSError("simulated process creation failure")
        with self.assertRaisesRegex(launcher.LaunchError, "process creation failure"):
            self.launch()
        self.assertEqual(self.target.read_bytes(), VIDEO)
        self.assertEqual(self.paths.gameinfo.read_bytes(), GAMEINFO.encode())
        self.assertFalse(list(self.paths.game_dir.glob("citadel_dolly_*")))

    def test_journal_failure_after_video_write_can_still_restore(self):
        save = gp._save_journal
        def failing(session, record):
            if record["state"] == "applied":
                raise OSError("simulated journal failure")
            save(session, record)
        with patch.object(gp, "_save_journal", side_effect=failing), self.assertRaisesRegex(launcher.LaunchError, "journal failure"):
            self.launch()
        self.popen.assert_not_called()
        self.assertEqual(self.target.read_bytes(), VIDEO)
        self.assertEqual(self.paths.gameinfo.read_bytes(), GAMEINFO.encode())

    def test_failure_before_graphics_journal_never_changes_video(self):
        with patch.object(gp, "_save_journal", side_effect=OSError("disk full")), self.assertRaises(launcher.LaunchError):
            self.launch()
        self.popen.assert_not_called()
        self.assertEqual(self.target.read_bytes(), VIDEO)
        self.assertEqual(self.paths.gameinfo.read_bytes(), GAMEINFO.encode())

    def test_newer_edit_during_prepare_is_preserved_and_refuses_launch(self):
        prepare = gp.prepare
        newer = VIDEO.replace(b'"1920"', b'"1280"')
        def changed(*args):
            prepare(*args)
            self.target.write_bytes(newer)
        with patch.object(gp, "prepare", side_effect=changed), self.assertRaisesRegex(launcher.LaunchError, "left untouched"):
            self.launch()
        self.popen.assert_not_called()
        self.assertEqual(self.target.read_bytes(), newer)
        self.assertEqual(self.paths.gameinfo.read_bytes(), GAMEINFO.encode())

    def test_newer_edit_after_exit_is_preserved_and_blocks_next_launch(self):
        session = self.launch()
        newer = RECORDING.replace(b'"1920"', b'"1280"')
        self.target.write_bytes(newer)
        with self.assertRaisesRegex(launcher.LaunchError, "Newer settings were left untouched"):
            self.close(session)
        self.assertEqual(self.target.read_bytes(), newer)
        self.assertEqual(self.paths.gameinfo.read_bytes(), GAMEINFO.encode())
        self.popen.reset_mock()
        with self.assertRaises(launcher.LaunchError):
            self.launch()
        self.popen.assert_not_called()
        # Manual conflict resolution to original is then accepted by recovery.
        self.target.write_bytes(VIDEO)
        launcher.recover_pending(self.paths.root)
        self.assertFalse(gp.pending(session.session_dir))

    def test_game_reserialization_restores_exact_original(self):
        session = self.launch()
        values = gp._values(RECORDING)
        data = 'video.cfg {\n' + '\n'.join(f'"{k}" "{v}"' for k, v in reversed(list(values.items()))) + '\n}'
        self.target.write_bytes(data.encode())
        self.close(session)
        self.assertEqual(self.target.read_bytes(), VIDEO)

    def test_equivalent_quality_numeric_and_boolean_reserialization_is_safe(self):
        session = self.launch()
        self.target.write_bytes(RECORDING.replace(b'quality" "2"', b'quality" "2.000000"')
                               .replace(b'bloom" "true"', b'bloom" "1"'))
        self.close(session)
        self.assertEqual(self.target.read_bytes(), VIDEO)

    def test_restore_write_failure_remains_pending_and_is_recoverable(self):
        session = self.launch()
        write = gp._atomic_write
        def failing(path, data, mode=None):
            if path == self.target:
                raise OSError("locked video file")
            return write(path, data, mode)
        with patch.object(gp, "_atomic_write", side_effect=failing), self.assertRaisesRegex(launcher.LaunchError, "locked video"):
            self.close(session)
        self.assertTrue(gp.pending(session.session_dir))
        self.assertEqual(self.target.read_bytes(), RECORDING)
        launcher.recover_pending(self.paths.root)
        self.assertEqual(self.target.read_bytes(), VIDEO)

    def test_every_session_saves_the_actual_latest_original(self):
        current = VIDEO.replace(b'"1920"', b'"1600"')
        self.target.write_bytes(current)
        session = self.launch()
        self.assertIn(b'"1600"', self.target.read_bytes())
        self.close(session)
        self.assertEqual(self.target.read_bytes(), current)

    def test_runtime_audit_only_queries_and_distinguishes_mismatch_from_unreadable(self):
        session = self.launch()
        query = MagicMock(return_value='r_citadel_shadow_quality = 2\nr_effects_bloom = true\n')
        report = gp.audit_runtime(session.session_dir, query)
        self.assertEqual(report["mismatches"], [])
        self.assertEqual(report["unreadable"], [])
        self.assertFalse(report["visual_verified"])
        requested = {name for item in query.call_args_list for name in item.args[0].split("; ")}
        self.assertEqual(requested, {"r_citadel_shadow_quality", "r_effects_bloom"})
        query.return_value = 'r_citadel_shadow_quality = 0\nUnknown command r_effects_bloom'
        report = gp.audit_runtime(session.session_dir, query)
        self.assertEqual(report["mismatches"], ["r_citadel_shadow_quality"])
        self.assertEqual(report["unreadable"], ["r_effects_bloom"])
        self.assertIn("warning", report)
        self.assertEqual(self.target.read_bytes(), RECORDING)

    def test_missing_video_file_never_falls_back_to_install_cfg(self):
        self.target.unlink()
        other = self.paths.citadel_dir / "cfg/video.txt"
        other.parent.mkdir()
        other.write_bytes(VIDEO)
        with self.assertRaises(launcher.LaunchError):
            self.launch()
        self.popen.assert_not_called()
        self.assertEqual(other.read_bytes(), VIDEO)

    def test_restore_journal_failure_keeps_original_and_retries_idempotently(self):
        session = self.launch()
        with patch.object(gp, "_save_journal", side_effect=OSError("journal locked")), self.assertRaises(launcher.LaunchError):
            self.close(session)
        self.assertEqual(self.target.read_bytes(), VIDEO)
        self.assertTrue(gp.pending(session.session_dir))
        launcher.recover_pending(self.paths.root)
        self.assertFalse(gp.pending(session.session_dir))

    def test_missing_profile_fails_before_process_or_video_changes(self):
        with self.assertRaisesRegex(launcher.LaunchError, "profile is missing"):
            launcher.launch(self.paths.root, graphics_profile="deleted-profile")
        self.popen.assert_not_called()
        self.assertEqual(self.target.read_bytes(), VIDEO)
        self.assertEqual(self.paths.gameinfo.read_bytes(), GAMEINFO.encode())

    def test_crash_recovery_after_early_gameinfo_restore_and_removed_overlay(self):
        session = self.launch()
        session.restore_gameinfo()
        session_cleanup.remove_overlay(session.overlay_dir, self.paths, session.session_dir)
        self.assertEqual(launcher.recover_pending(self.paths.root), [str(session.session_dir)])
        self.assertEqual(self.target.read_bytes(), VIDEO)
        self.assertEqual(launcher.recover_pending(self.paths.root), [])

    def test_recovery_uses_original_account_when_steam_account_changes(self):
        session = self.launch()
        self.account.return_value = "456"
        launcher.recover_pending(self.paths.root)
        self.assertEqual(self.target.read_bytes(), VIDEO)
        self.assertFalse(gp.pending(session.session_dir))

    def test_account_change_before_apply_refuses_launch(self):
        self.account.side_effect = ["123", "456"]
        other = self.root / "Steam/userdata/456/1422450/local/cfg/video.txt"
        other.parent.mkdir(parents=True)
        other.write_bytes(RECORDING)
        with self.assertRaisesRegex(launcher.LaunchError, "Steam user"):
            self.launch()
        self.popen.assert_not_called()
        self.assertEqual(self.target.read_bytes(), VIDEO)
        self.assertEqual(other.read_bytes(), RECORDING)

    def test_gameinfo_conflict_does_not_prevent_graphics_restoration(self):
        session = self.launch()
        self.paths.gameinfo.write_bytes(GAMEINFO.encode() + b"// new user edit")
        with self.assertRaises(launcher.LaunchError):
            self.close(session)
        self.assertEqual(self.target.read_bytes(), VIDEO)

    def test_running_game_and_readonly_video_refuse_before_any_change(self):
        self.processes.return_value = {"steam.exe", "deadlock.exe"}
        with self.assertRaises(launcher.LaunchError):
            self.launch()
        self.processes.return_value = {"steam.exe"}
        os.chmod(self.target, stat.S_IREAD)
        try:
            with self.assertRaisesRegex(launcher.LaunchError, "read-only"):
                self.launch()
        finally:
            os.chmod(self.target, stat.S_IREAD | stat.S_IWRITE)
        self.popen.assert_not_called()
        self.assertEqual(self.target.read_bytes(), VIDEO)
        self.assertEqual(self.paths.gameinfo.read_bytes(), GAMEINFO.encode())

    def test_no_restore_over_another_running_game(self):
        session = self.launch()
        self.processes.return_value = {"deadlock.exe"}
        with self.assertRaisesRegex(launcher.LaunchError, "Exit Deadlock"):
            self.close(session)
        self.assertEqual(self.target.read_bytes(), RECORDING)

    def test_modified_backup_or_redirected_journal_is_rejected(self):
        session = self.launch()
        journal = session.session_dir / gp.JOURNAL
        original = journal.read_bytes()
        for key, value in [("target", str(self.paths.gameinfo)), ("account", "../123"), ("original_sha256", "0" * 64)]:
            record = json.loads(original)
            record[key] = value
            journal.write_text(json.dumps(record))
            with self.subTest(key=key), self.assertRaises(launcher.LaunchError):
                launcher.recover_pending(self.paths.root)
            self.assertEqual(self.target.read_bytes(), RECORDING)
        journal.write_bytes(original)
        (session.session_dir / gp.ORIGINAL).write_bytes(b"corrupt")
        with self.assertRaisesRegex(launcher.LaunchError, "hash check"):
            launcher.recover_pending(self.paths.root)
        self.assertEqual(self.target.read_bytes(), RECORDING)

    def test_normal_exit_watcher_restores_graphics(self):
        # Exercise the actual current launcher's exit watcher with an existing
        # legacy transaction, rather than writing a fixture copy of that watcher.
        session = launcher.launch(self.paths.root)
        gp.prepare(session.session_dir, self.profile["id"])
        gp.apply(session.session_dir)
        self.assertEqual(self.target.read_bytes(), RECORDING)
        self.process.poll.return_value = 0
        self.process.wait.return_value = 0
        with patch.object(launcher, "dismiss_assert_dialogs", return_value=[]):
            self.thread.call_args.kwargs["target"]()
        self.assertEqual(self.target.read_bytes(), VIDEO)
        self.assertFalse(session.overlay_dir.exists())

    @unittest.skipUnless(os.name == "nt", "Windows cleanup waiter")
    def test_detached_cleanup_helper_restores_graphics_after_owned_handle_signals(self):
        session = self.launch()
        api = MagicMock()
        api.WaitForSingleObject.return_value = 0
        with patch.object(session_cleanup.ctypes, "WinDLL", return_value=api):
            self.assertEqual(session_cleanup.wait_and_cleanup(session.session_dir, 1234), 0)
        self.assertEqual(self.target.read_bytes(), VIDEO)
        self.assertFalse(session.overlay_dir.exists())


if __name__ == "__main__":
    unittest.main()
