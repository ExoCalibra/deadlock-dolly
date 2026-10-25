"""Actual private settings preparation keeps the player's files untouched."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from dolly import editing_session as editing, gameinfo_transaction, graphics_profiles as graphics
from dolly.game_installation import validate_game
from dolly.launch_errors import LaunchError


class EditingSessionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        install = self.root / "Steam library" / "Deadlock"
        for relative in ("game/bin/win64/deadlock.exe", "game/citadel/bin/win64/server.dll",
                         "game/citadel/gameinfo.gi"):
            path = install / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"original game bytes")
        self.paths = validate_game(install)
        self.session = self.root / "Dolly" / "logs" / "20261102_010203_aabbccdde0"
        self.session.mkdir(parents=True)
        digest = hashlib.sha256(self.paths.gameinfo.read_bytes()).hexdigest()
        gameinfo_transaction.save_record(self.session, {
            "owner": "Deadlock Dolly", "session_dir": str(self.session),
            "original_gameinfo": str(self.paths.gameinfo),
            "overlay_dir": str(self.paths.game_dir / ("citadel_dolly_" + self.session.name)),
            "backup_name": "original.gameinfo.gi", "original_sha256": digest,
            "patched_sha256": "f" * 64, "config_state": "prepared",
        })
        self.assets = self.root / "editing assets"
        self.assets.mkdir()
        self.profile = {"format": 1}
        self.asset_profile = self.assets / "profile.json"
        self.asset_profile.write_text(json.dumps(self.profile), encoding="utf-8")
        self.target = self.root / "Steam/userdata/123/1422450/local/cfg/video.txt"
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b'''"video.cfg"\n{
"Version" "20"
"VendorID" "4318"
"DeviceID" "10118"
"setting.defaultres" "2560"
"setting.defaultresheight" "1440"
"setting.coop_fullscreen" "1"
"setting.r_citadel_fog_quality" "0"
"setting.r_citadel_upscaling" "4"
"setting.mat_viewportscale" "0.5"
"setting.gpu_level" "0"
"unexpected" "user setting"
}\n''')
        self.install_before = {str(p): p.read_bytes() for p in self.paths.root.rglob("*") if p.is_file()}
        self.original_video = self.target.read_bytes()
        self.patch(editing, "EDITING_ROOT", self.assets)
        self.patch(graphics, "current_video", return_value=self.target)
        self.patch(graphics, "library_path", return_value=self.root / "graphics-profiles.json")

    def patch(self, obj, name, *args, **kwargs):
        owner = patch.object(obj, name, *args, **kwargs)
        self.addCleanup(owner.stop)
        return owner.start()

    def baseline(self):
        values = {name: "1" for name in graphics.QUALITY_FIELDS}
        values.update({"version": "20", "setting.r_citadel_upscaling": "0", "setting.mat_viewportscale": "1"})
        data = ('"video.cfg"\n{\n' + "".join(f'"{key}" "{value}"\n' for key, value in values.items()) + "}\n").encode()
        (self.assets / "video.txt").write_bytes(data)
        self.profile["video_sha256"] = hashlib.sha256(data).hexdigest()
        self.asset_profile.write_text(json.dumps(self.profile), encoding="utf-8")
        return data

    def result_video(self):
        return editing._values((self.session / editing.DIRECTORY / "cfg/video.txt").read_bytes())

    def assert_player_files_unchanged(self):
        self.assertEqual(self.target.read_bytes(), self.original_video)
        self.assertEqual({str(p): p.read_bytes() for p in self.paths.root.rglob("*") if p.is_file()}, self.install_before)

    def test_prepares_only_private_files_and_child_environment(self):
        self.baseline()
        before_environment = dict(os.environ)
        result = editing.prepare(self.session, self.paths)
        directory = self.session / editing.DIRECTORY
        self.assertEqual(result["environment"]["USRLOCAL" + str(self.paths.citadel_dir.resolve())], str(directory))
        self.assertEqual(result["environment"]["USRLOCALcitadel"], str(directory))
        self.assertEqual(result["environment"]["USRLOCAL"], str(directory))
        self.assertEqual(dict(os.environ), before_environment)
        self.assertEqual(json.loads((self.session / editing.JOURNAL).read_text()), result["audit"])
        self.assertFalse(result["audit"]["runtime_verified"])
        for relative, digest in result["audit"]["files"].items():
            self.assertEqual(hashlib.sha256((directory / relative).read_bytes()).hexdigest(), digest)
        self.assertEqual((directory / "cfg/machine_convars.vcfg").read_bytes(), editing.EMPTY_CONVARS)
        self.assertEqual((directory / "cfg/user_convars_0_slot0.vcfg").read_bytes(), editing.EMPTY_CONVARS)

    def test_audio_levels_are_carried_without_other_player_settings(self):
        self.baseline()
        self.target.parent.joinpath("machine_convars.vcfg").write_text(
            '"config"\n{\n\t"convars"\n\t{\n'
            '\t\t"volume"\t\t"0.21"\n'
            '\t\t"snd_voipvolume"\t\t"1.76"\n'
            '\t\t"snd_musicvolume"\t\t"0"\n'
            '\t\t"r_citadel_fog_quality"\t\t"4"\n'
            '\t}\n}\n', encoding="utf-8")
        result = editing.prepare(self.session, self.paths)
        directory = self.session / editing.DIRECTORY
        values = editing._convar_values((directory / "cfg/machine_convars.vcfg").read_bytes())
        self.assertEqual(values, {"volume": "0.21", "snd_voipvolume": "1.76",
                                  "snd_musicvolume": "0"})
        self.assertEqual(result["audit"]["audio_convar_count"], 3)
        self.assertNotIn("r_citadel_fog_quality", values)

    def test_explicit_window_size_overrides_saved_borderless_only_in_session(self):
        self.baseline()
        editing.prepare(self.session, self.paths, launch_options='-windowed -w 1280 -h 720')
        result = self.result_video()
        self.assertEqual(result['setting.defaultres'], '1280')
        self.assertEqual(result['setting.defaultresheight'], '720')
        self.assertEqual(result['setting.fullscreen'], '0')
        self.assertEqual(result['setting.coop_fullscreen'], '0')
        self.assert_player_files_unchanged()

    def test_graphics_audit_retains_known_values_when_bulk_reply_is_incomplete(self):
        self.baseline()
        editing.prepare(self.session, self.paths)
        # The live console returned the early render values but omitted the
        # final motion/shadow responses. Shadow is independently registered;
        # an incomplete bulk reply must not lose its separate readable value.
        absent = {'r_particle_depth_feathering', 'r_citadel_motion_blur'}
        def query(command):
            names = command.split('; ')
            return '\n'.join(f'{name} = 1' for name in names
                             if name not in absent and
                             (len(names) == 1 or name != 'r_citadel_shadow_quality'))
        report = graphics.audit_runtime(self.session, query)
        # Deadlock hides these two from the console echo. A silent reply is
        # recorded separately instead of warning about an unchecked profile.
        self.assertEqual(set(report['not_echoed']), absent)
        self.assertEqual(report['unreadable'], [])
        self.assertEqual(report['observed']['r_citadel_shadow_quality'], 1)
        self.assertEqual(report['mismatches'], [])
        self.assertNotIn('warning', report)
        self.assertFalse(report['visual_verified'])
        self.assert_player_files_unchanged()

    def test_runtime_requires_exact_private_path_and_user_config_gate(self):
        self.baseline()
        editing.prepare(self.session, self.paths)
        root = self.session / editing.DIRECTORY
        commands = []
        def query(command):
            commands.append(command)
            return ('host_readconfig_ignore_userconfig = true' if command != 'path'
                    else f'USRLOCAL "{root}"\nGAME "ordinary game path"')
        report = editing.verify_runtime(self.session, query, pid=1234)
        self.assertTrue(report['runtime_verified'])
        self.assertEqual(report['pid'], 1234)
        self.assertEqual(commands, ['host_readconfig_ignore_userconfig', 'path'])
        for gate, path in [('0', str(root)), ('1', str(root) + '-different'),
                           ('1', str(root / 'different')), ('1', str(self.target.parent))]:
            with self.subTest(gate=gate, path=path):
                def invalid(command):
                    return f'host_readconfig_ignore_userconfig = {gate}' if command != 'path' else f'USRLOCAL "{path}"'
                with self.assertRaises(LaunchError):
                    editing.verify_runtime(self.session, invalid, pid=1234)
                self.assertFalse(editing.descriptor(self.session)['runtime_verified'])
        for listing in [f'USRLOCAL "{root}"\nUSRLOCAL "{self.target.parent}"',
                        f'GAME "{root}"\nGAME "C:/USRLOCAL/ordinary-folder"',
                        f'GAME "USRLOCAL {root}"']:
            with self.subTest(listing=listing), self.assertRaises(LaunchError):
                editing.verify_runtime(self.session, lambda command: (
                    'host_readconfig_ignore_userconfig = 1' if command != 'path' else listing), pid=1234)
        self.assert_player_files_unchanged()

    def test_runtime_query_failure_invalidates_previous_verification(self):
        self.baseline()
        editing.prepare(self.session, self.paths)
        path = self.session / editing.JOURNAL
        record = json.loads(path.read_text(encoding='utf-8'))
        record['runtime_verified'] = True
        path.write_text(json.dumps(record), encoding='utf-8')
        def failed(_command):
            raise RuntimeError('owned connection lost')
        with self.assertRaisesRegex(LaunchError, 'owned connection lost'):
            editing.verify_runtime(self.session, failed, pid=1234)
        self.assertFalse(editing.descriptor(self.session)['runtime_verified'])
        self.assert_player_files_unchanged()
        self.assert_player_files_unchanged()

    def test_retains_only_display_identity_from_competitive_video(self):
        self.baseline()
        editing.prepare(self.session, self.paths)
        values = self.result_video()
        self.assertEqual(values["vendorid"], "4318")
        self.assertEqual(values["deviceid"], "10118")
        self.assertEqual(values["setting.defaultres"], "2560")
        self.assertEqual(values["setting.defaultresheight"], "1440")
        self.assertEqual(values["setting.coop_fullscreen"], "1")
        self.assertEqual(values["setting.r_citadel_fog_quality"], "1")
        self.assertEqual(values["setting.r_citadel_upscaling"], "0")
        self.assertEqual(values["setting.mat_viewportscale"], "1")
        self.assertNotIn("setting.gpu_level", values)
        self.assertNotIn("unexpected", values)
        self.assert_player_files_unchanged()

    def test_named_quality_profile_changes_only_private_video(self):
        baseline = self.baseline()
        profile = graphics.profile_from_bytes("Recording", baseline.replace(b'quality" "1"', b'quality" "2"'))
        graphics.save_library({"format": 1, "selected": profile["id"], "profiles": [profile]})
        library_before = graphics.library_path().read_bytes()
        result = editing.prepare(self.session, self.paths, graphics_profile=profile["id"])
        self.assertEqual(self.result_video()["setting.r_citadel_fog_quality"], "2")
        self.assertEqual(result["audit"]["profile"], {"id": profile["id"], "name": "Recording"})
        self.assertEqual(graphics.library_path().read_bytes(), library_before)
        self.assertFalse((self.session / graphics.JOURNAL).exists())
        self.assert_player_files_unchanged()

    def test_missing_named_profile_refuses_before_creating_settings(self):
        self.baseline()
        with self.assertRaisesRegex(LaunchError, "profile is missing"):
            editing.prepare(self.session, self.paths, graphics_profile="a" * 32)
        self.assertFalse((self.session / editing.DIRECTORY).exists())
        self.assert_player_files_unchanged()

    def test_missing_baseline_does_not_inherit_user_quality(self):
        result = editing.prepare(self.session, self.paths)
        self.assertEqual(result["audit"]["baseline"], "game_defaults_with_display")
        values = self.result_video()
        self.assertEqual(values["setting.defaultres"], "2560")
        self.assertNotIn("setting.r_citadel_fog_quality", values)
        self.assertNotIn("setting.mat_viewportscale", values)

    def test_named_profile_requires_a_reviewed_baseline(self):
        with self.assertRaisesRegex(LaunchError, "reviewed editing video baseline"):
            editing.prepare(self.session, self.paths, graphics_profile="a" * 32)
        self.assertFalse((self.session / editing.DIRECTORY).exists())

    def test_unavailable_or_malformed_player_video_uses_private_defaults(self):
        self.baseline()
        self.target.write_bytes(b"malformed user video")
        self.original_video = self.target.read_bytes()
        result = editing.prepare(self.session, self.paths)
        self.assertEqual(result["audit"]["display_fields_preserved"], [])
        self.assertIn("unavailable", result["audit"]["warning"])
        self.assertNotIn(str(self.target), json.dumps(result["audit"]))
        self.assertEqual(self.result_video()["setting.r_citadel_fog_quality"], "1")
        self.assert_player_files_unchanged()

    def test_absent_steam_and_baseline_leaves_video_for_game_defaults(self):
        self.patch(graphics, "current_video", side_effect=LaunchError("no signed-in Steam user"))
        result = editing.prepare(self.session, self.paths)
        self.assertEqual(result["audit"]["baseline"], "game_defaults")
        self.assertNotIn("cfg/video.txt", result["audit"]["files"])

    def test_invalid_display_values_cannot_override_defaults(self):
        self.baseline()
        self.target.write_bytes(self.original_video.replace(b'"2560"', b'"9999999"').replace(b'"4318"', b'"1;quit"'))
        editing.prepare(self.session, self.paths)
        values = self.result_video()
        self.assertNotIn("vendorid", values)
        self.assertNotIn("setting.defaultres", values)
        self.assertEqual(values["setting.defaultresheight"], "1440")

    def test_readonly_player_video_is_read_without_changing_mode(self):
        self.baseline()
        self.target.chmod(stat.S_IREAD)
        self.addCleanup(self.target.chmod, stat.S_IREAD | stat.S_IWRITE)
        mode = stat.S_IMODE(self.target.stat().st_mode)
        editing.prepare(self.session, self.paths)
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), mode)
        self.assert_player_files_unchanged()

    def test_corrupt_or_unpinned_baseline_is_never_silently_used(self):
        self.baseline()
        (self.assets / "video.txt").write_bytes(b"corrupt")
        with self.assertRaisesRegex(LaunchError, "SHA-256"):
            editing.prepare(self.session, self.paths)
        self.assertFalse((self.session / editing.DIRECTORY).exists())
        self.profile.pop("video_sha256")
        self.asset_profile.write_text(json.dumps(self.profile), encoding="utf-8")
        with self.assertRaisesRegex(LaunchError, "fingerprint"):
            editing.prepare(self.session, self.paths)

    def test_baseline_with_missing_quality_fields_is_refused(self):
        data = b'"video.cfg" { "Version" "20" }'
        (self.assets / "video.txt").write_bytes(data)
        self.profile["video_sha256"] = hashlib.sha256(data).hexdigest()
        self.asset_profile.write_text(json.dumps(self.profile), encoding="utf-8")
        with self.assertRaisesRegex(LaunchError, "required quality"):
            editing.prepare(self.session, self.paths)
        self.assertFalse((self.session / editing.DIRECTORY).exists())

    def test_existing_private_directory_is_preserved(self):
        directory = self.session / editing.DIRECTORY
        directory.mkdir()
        sentinel = directory / "do-not-touch"
        sentinel.write_bytes(b"keep")
        with self.assertRaisesRegex(LaunchError, "already has editing settings"):
            editing.prepare(self.session, self.paths)
        self.assertEqual(sentinel.read_bytes(), b"keep")
        self.assert_player_files_unchanged()

    def test_owned_journal_cannot_target_another_installation(self):
        alternate = self.root / "another gameinfo.gi"
        paths = SimpleNamespace(citadel_dir=self.paths.citadel_dir, gameinfo=alternate)
        with self.assertRaisesRegex(LaunchError, "another game installation"):
            editing.prepare(self.session, paths)
        self.assertFalse((self.session / editing.DIRECTORY).exists())

    def test_failure_during_private_write_never_touches_player_files(self):
        self.baseline()
        write = editing._atomic_write
        calls = []
        def fail_second(path, data, mode=None):
            calls.append(path)
            path.relative_to(self.session)
            if len(calls) == 2:
                raise OSError("simulated private disk failure")
            return write(path, data, mode)
        self.patch(editing, "_atomic_write", side_effect=fail_second)
        with self.assertRaisesRegex(LaunchError, "private disk failure"):
            editing.prepare(self.session, self.paths)
        self.assertFalse((self.session / editing.JOURNAL).exists())
        self.assert_player_files_unchanged()


if __name__ == "__main__":
    unittest.main()
