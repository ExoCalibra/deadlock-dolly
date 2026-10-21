"""Review-bound cfg loading and owned deployment at their filesystem boundary."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dolly import editing_assets as assets
from dolly.launch_errors import LaunchError


class EditingAssetsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.assets = self.root / "editing"
        (self.assets / "cfg").mkdir(parents=True)
        self.files = {name: ("// reviewed " + name + "\n").encode() for name in sorted(assets.REQUIRED)}
        self.manifest = {"format": 1, "files": {}}
        self.save_assets()
        game = self.root / "Deadlock/game"
        for relative in ("bin/win64/deadlock.exe", "citadel/bin/win64/server.dll", "citadel/gameinfo.gi"):
            path = game / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"original game")
        self.overlay = game / "citadel_dolly_20261102_010203_aabbccdde0"
        (self.overlay / "cvar_unlocker/bin/win64").mkdir(parents=True)
        self.marker = self.overlay / ".dolly-session.json"
        self.marker.write_text(json.dumps({
            "owner": "Deadlock Dolly",
            "session_dir": str(self.root / "Dolly/logs/20261102_010203_aabbccdde0"),
            "original_gameinfo": str(game / "citadel/gameinfo.gi"),
            "original_sha256": hashlib.sha256(b"original game").hexdigest(),
        }), encoding="utf-8")
        self.install = game / "citadel/cfg/autoexec.cfg"
        self.install.parent.mkdir()
        self.install.write_bytes(b"exec competitive.cfg\n")
        self.user = self.root / "Steam/userdata/123/1422450/local/cfg/user_convars_0_slot0.vcfg"
        self.user.parent.mkdir(parents=True)
        self.user.write_bytes(b"user config untouched")

    def save_assets(self):
        self.manifest["files"] = {}
        for name, data in self.files.items():
            path = self.assets / "cfg" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            self.manifest["files"][name] = {"sha256": hashlib.sha256(data).hexdigest()}
        self.save_manifest()

    def save_manifest(self, data=None):
        data = (json.dumps(self.manifest, indent=2) + "\n").encode() if data is None else data
        (self.assets / "cfg-manifest.json").write_bytes(data)
        (self.assets / "profile.json").write_text(json.dumps({
            "format": 1, "cfg_manifest_sha256": hashlib.sha256(data).hexdigest(),
        }), encoding="utf-8")

    def assert_player_files_unchanged(self):
        self.assertEqual(self.install.read_bytes(), b"exec competitive.cfg\n")
        self.assertEqual(self.user.read_bytes(), b"user config untouched")

    def test_exact_reviewed_bytes_deploy_only_into_fresh_owned_cfg(self):
        files = assets.load(self.assets)
        self.assertEqual(files, self.files)
        assets.deploy(self.overlay, files)
        deployed = self.overlay / "cvar_unlocker/cfg"
        self.assertEqual({path.name: path.read_bytes() for path in deployed.iterdir()}, self.files)
        self.assert_player_files_unchanged()

    def test_tampered_manifest_or_asset_never_returns_partial_review(self):
        original = (self.assets / "cfg-manifest.json").read_bytes()
        (self.assets / "cfg-manifest.json").write_bytes(original + b" ")
        with self.assertRaisesRegex(LaunchError, "manifest failed its SHA-256"):
            assets.load(self.assets)
        self.save_manifest(original)
        (self.assets / "cfg" / "configschema.vcfg").write_bytes(b"unreviewed")
        with self.assertRaisesRegex(LaunchError, "asset failed its SHA-256"):
            assets.load(self.assets)
        self.assertFalse((self.overlay / "cvar_unlocker/cfg").exists())

    def test_no_manifest_pin_or_missing_required_default_is_refused(self):
        (self.assets / "profile.json").write_text('{"format":1}', encoding="utf-8")
        with self.assertRaisesRegex(LaunchError, "no reviewed fingerprint"):
            assets.load(self.assets)
        del self.files["user_keys_default.vcfg"]
        self.save_assets()
        with self.assertRaisesRegex(LaunchError, "incomplete"):
            assets.load(self.assets)

    def test_unsafe_names_are_rejected_before_any_deployment_write(self):
        for name in ("../outside.cfg", "nested/extra.cfg", "C:/outside.cfg", "extra.cfg:stream",
                     "CON.cfg", "con.cfg", "User.cfg", "extra.dll", "extra.cfg."):
            with self.subTest(name=name):
                files = {**self.files, name: b"unsafe"}
                with self.assertRaisesRegex(LaunchError, "unsafe filename"):
                    assets.deploy(self.overlay, files)
                self.assertFalse((self.overlay / "cvar_unlocker/cfg").exists())
        self.assert_player_files_unchanged()

    def test_manifest_duplicate_keys_invalid_utf8_and_future_format_fail(self):
        for data in (b'{"format":1,"format":1,"files":{}}', b"\xff", b'{"format":true,"files":{}}',
                     b'{"format":2,"files":{}}'):
            with self.subTest(data=data):
                self.save_manifest(data)
                with self.assertRaises(LaunchError):
                    assets.load(self.assets)

    def test_bad_file_fingerprint_and_nested_entry_fail(self):
        for entry in ({"sha256": "x" * 64}, [], {"sha256": 123}):
            with self.subTest(entry=entry):
                self.manifest["files"]["autoexec.cfg"] = entry
                self.save_manifest()
                with self.assertRaisesRegex(LaunchError, "invalid fingerprint"):
                    assets.load(self.assets)

    def test_file_count_file_size_and_total_size_caps_before_deploy(self):
        over_count = {**self.files, **{f"extra{i}.cfg": b"" for i in range(assets.MAX_FILES)}}
        over_file = {**self.files, "extra.cfg": b"x" * (assets.MAX_FILE_BYTES + 1)}
        over_total = {**self.files, **{f"extra{i}.cfg": b"x" * assets.MAX_FILE_BYTES for i in range(17)}}
        for files in (over_count, over_file, over_total):
            with self.subTest(count=len(files)):
                with self.assertRaisesRegex(LaunchError, "limit"):
                    assets.deploy(self.overlay, files)
                self.assertFalse((self.overlay / "cvar_unlocker/cfg").exists())

    def test_loading_large_asset_or_aggregate_is_bounded(self):
        self.files["extra.cfg"] = b"x" * (assets.MAX_FILE_BYTES + 1)
        self.save_assets()
        with self.assertRaisesRegex(LaunchError, "file size limit"):
            assets.load(self.assets)
        del self.files["extra.cfg"]
        self.files.update({f"extra{i}.cfg": b"x" * assets.MAX_FILE_BYTES for i in range(17)})
        self.save_assets()
        with self.assertRaisesRegex(LaunchError, "total size limit"):
            assets.load(self.assets)

    def test_ordinary_path_guard_rejects_linked_source(self):
        source = self.assets / "cfg/configschema.vcfg"
        plain = assets._plain_ancestors
        with patch.object(assets, "_plain_ancestors", side_effect=lambda path: False if path == source else plain(path)):
            with self.assertRaisesRegex(LaunchError, "ordinary local files"):
                assets.load(self.assets)
        self.assert_player_files_unchanged()

    def test_wrong_owner_or_unknown_existing_cfg_is_preserved(self):
        self.marker.write_text('{"owner":"Someone else"}', encoding="utf-8")
        with self.assertRaisesRegex(LaunchError, "unrecognized owner"):
            assets.deploy(self.overlay, self.files)
        self.setUp_marker_again()
        target = self.overlay / "cvar_unlocker/cfg"
        target.mkdir()
        sentinel = target / "user.cfg"
        sentinel.write_bytes(b"keep")
        with self.assertRaisesRegex(LaunchError, "already exists"):
            assets.deploy(self.overlay, self.files)
        self.assertEqual(sentinel.read_bytes(), b"keep")

    def setUp_marker_again(self):
        self.marker.write_text(json.dumps({
            "owner": "Deadlock Dolly", "session_dir": str(self.root / "Dolly/logs/20261102_010203_aabbccdde0"),
            "original_gameinfo": str(self.install.parent.parent / "gameinfo.gi"),
            "original_sha256": hashlib.sha256(b"original game").hexdigest(),
        }), encoding="utf-8")

    def test_partial_owned_write_failure_preserves_player_configs(self):
        writer = assets._atomic_write
        calls = []
        def fail_second(path, data, mode=None):
            path.relative_to(self.overlay / "cvar_unlocker/cfg")
            calls.append(path)
            if len(calls) == 2:
                raise OSError("simulated cfg disk failure")
            return writer(path, data, mode)
        with patch.object(assets, "_atomic_write", side_effect=fail_second):
            with self.assertRaisesRegex(LaunchError, "cfg disk failure"):
                assets.deploy(self.overlay, self.files)
        self.assertEqual(len(list((self.overlay / "cvar_unlocker/cfg").iterdir())), 1)
        self.assert_player_files_unchanged()

    def test_deployment_readback_mismatch_is_not_reported_as_success(self):
        reader = assets._read
        with patch.object(assets, "_read", side_effect=lambda path: b"wrong" if self.overlay in path.parents else reader(path)):
            with self.assertRaisesRegex(LaunchError, "read back correctly"):
                assets.deploy(self.overlay, self.files)
        self.assert_player_files_unchanged()


if __name__ == "__main__":
    unittest.main()
