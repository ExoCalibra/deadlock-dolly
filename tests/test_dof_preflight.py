"""Native DOF preflight reads the user's own install and fails closed."""
import binascii
import json
from pathlib import Path, PurePosixPath
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from dolly import dof_preflight
from dolly import panorama_assets
from dolly.controller import Controller


def write_vpk(path, entries):
    """Write one VPK v2 index with inline payloads."""
    groups = {}
    for name, payload in entries.items():
        item = PurePosixPath(name)
        groups.setdefault((item.suffix[1:], item.parent.as_posix()), []).append((item.stem, payload))
    tree = bytearray()
    data = bytearray()
    for extension in sorted({key[0] for key in groups}):
        tree += extension.encode() + b"\0"
        for (ext, directory), members in sorted(groups.items()):
            if ext != extension:
                continue
            tree += directory.encode() + b"\0"
            for name, payload in members:
                tree += name.encode() + b"\0"
                tree += struct.pack("<IHHIIH", binascii.crc32(payload) & 0xffffffff, 0,
                                    0x7fff, len(data), len(payload), 0xffff)
                data += payload
            tree += b"\0"
        tree += b"\0"
    tree += b"\0"
    header = struct.pack("<III", 0x55AA1234, 2, len(tree)) + struct.pack("<IIII", len(data), 0, 0, 0)
    Path(path).write_bytes(header + bytes(tree) + bytes(data))


def make_install(root, *, renderer="dx11", materials=None, models=("50",)):
    root = Path(root)
    citadel = root / "game" / "citadel"
    bin_dir = root / "game" / "bin" / "win64"
    citadel.mkdir(parents=True, exist_ok=True)
    bin_dir.mkdir(parents=True, exist_ok=True)
    platform = "pc" if renderer == "dx11" else "vulkan"
    shard = "shaders_pc" if renderer == "dx11" else "shaders_vulkan"
    entries = {}
    for model in models:
        for stage in ("vs", "ps", "features"):
            entries[f"shaders/vfx/dof_{platform}_{model}_{stage}.vcs"] = b"\x12\x0a" + stage.encode()
    write_vpk(citadel / f"{shard}_dir.vpk", entries)
    write_vpk(citadel / "pak01_dir.vpk", materials if materials is not None else {
        name: b"material" for name in dof_preflight.MATERIALS})
    (citadel / "steam.inf").write_text("ClientVersion=6795\n", encoding="utf-8")
    (bin_dir / "vfx_dx11.dll").write_bytes(b"MZ")
    return root


class GameDirTests(unittest.TestCase):
    def test_resolves_every_selection_shape(self):
        base = Path("C:/Games/Deadlock")
        expected = (base / "game", base / "game" / "citadel", base / "game" / "bin" / "win64")
        for selected in (base, base / "game", base / "game" / "bin" / "win64",
                         base / "game" / "bin" / "win64" / "deadlock.exe",
                         base / "game" / "citadel"):
            self.assertEqual(dof_preflight.game_dirs(selected), expected, str(selected))


class PreflightTests(unittest.TestCase):
    def test_ready_install_reports_the_shipped_shader(self):
        with tempfile.TemporaryDirectory() as temp:
            root = make_install(temp)
            report = dof_preflight.check_installation(root)
        self.assertEqual(report["status"], dof_preflight.READY)
        self.assertEqual(report["build"], "6795")
        self.assertEqual(report["shader_models"], {"50": ["features", "ps", "vs"]})
        self.assertEqual(report["missing_materials"], [])
        self.assertFalse(report["dynamic_compile"]["available"])
        self.assertEqual(report["dynamic_compile"]["missing"], ["slang.dll"])
        self.assertIn("no vfx shader compiler is needed", " ".join(report["notes"]))

    def test_executable_selection_works(self):
        with tempfile.TemporaryDirectory() as temp:
            root = make_install(temp)
            report = dof_preflight.check_installation(root / "game" / "bin" / "win64" / "deadlock.exe")
        self.assertEqual(report["status"], dof_preflight.READY)

    def test_missing_shader_stage_fails_closed_with_verify_advice(self):
        with tempfile.TemporaryDirectory() as temp:
            root = make_install(temp)
            citadel = root / "game" / "citadel"
            write_vpk(citadel / "shaders_pc_dir.vpk", {
                "shaders/vfx/dof_pc_50_vs.vcs": b"vs",
                "shaders/vfx/dof_pc_50_features.vcs": b"features"})
            report = dof_preflight.check_installation(root)
        self.assertEqual(report["status"], dof_preflight.VERIFY_FILES)
        self.assertTrue(report["missing_shader"])
        self.assertIn("Verify the game files in Steam", " ".join(report["notes"]))

    def test_missing_material_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = make_install(temp, materials={
                "materials/dev/dof1_general.vmat_c": b"material"})
            report = dof_preflight.check_installation(root)
        self.assertEqual(report["status"], dof_preflight.VERIFY_FILES)
        self.assertEqual(report["missing_materials"], ["materials/dev/dof1_blur.vmat_c"])

    def test_vulkan_pack_is_selected_by_renderer(self):
        with tempfile.TemporaryDirectory() as temp:
            root = make_install(temp, renderer="vulkan")
            vulkan = dof_preflight.check_installation(root, renderer="vulkan")
            dx11 = dof_preflight.check_installation(root)
        self.assertEqual(vulkan["status"], dof_preflight.READY)
        self.assertIn("dof_vulkan_50_ps.vcs", " ".join(vulkan["shader_variants"]))
        self.assertEqual(dx11["status"], dof_preflight.VERIFY_FILES)

    def test_corrupt_pack_does_not_raise(self):
        with tempfile.TemporaryDirectory() as temp:
            root = make_install(temp)
            (root / "game" / "citadel" / "shaders_pc_dir.vpk").write_bytes(b"not a vpk")
            report = dof_preflight.check_installation(root)
        self.assertEqual(report["status"], dof_preflight.VERIFY_FILES)
        self.assertTrue(report["problems"])

    def test_unknown_or_absent_install_is_not_a_crash(self):
        self.assertEqual(dof_preflight.check_installation(None)["status"],
                         dof_preflight.UNKNOWN_INSTALL)
        with tempfile.TemporaryDirectory() as temp:
            report = dof_preflight.check_installation(Path(temp) / "nowhere")
        self.assertEqual(report["status"], dof_preflight.UNKNOWN_INSTALL)
        self.assertTrue(report["problems"])

    def test_disabled_dynamic_compile_is_reported_not_treated_as_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = make_install(temp)
            report = dof_preflight.check_installation(root, dynamic_compile=1)
        self.assertEqual(report["status"], dof_preflight.READY)
        self.assertEqual(report["dynamic_compile_setting"], 1)
        self.assertIn("Dolly clears it for the session", " ".join(report["notes"]))

    def test_report_text_has_no_absolute_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = make_install(temp)
            report = dof_preflight.check_installation(root)
            text = dof_preflight.format_report(report)
        self.assertIn("Native DOF support: ready", text)
        self.assertNotIn(str(root), text)
        self.assertNotIn(":\\", text)

    def test_unreadable_pack_report_does_not_expose_the_install_path(self):
        reader = panorama_assets.list_vpk_entries
        with tempfile.TemporaryDirectory() as temp:
            root = make_install(temp)
            for pack_name in ("shaders_pc_dir.vpk", "pak01_dir.vpk"):
                with self.subTest(pack=pack_name):
                    def read_pack(path, **options):
                        if Path(path).name == pack_name:
                            raise PermissionError(13, "Permission denied", str(path))
                        return reader(path, **options)

                    with patch.object(panorama_assets, "list_vpk_entries", side_effect=read_pack):
                        report = dof_preflight.check_installation(root)
                    text = dof_preflight.format_report(report)
                    self.assertEqual(report["status"], dof_preflight.VERIFY_FILES)
                    self.assertNotIn(root.name, text)
                    self.assertNotIn(root.name, json.dumps(report))
                    self.assertIn(pack_name, text)
                    self.assertIn("PermissionError", text)

    def test_permission_denied_metadata_is_reported_without_raising_or_path_leaks(self):
        stat = Path.stat
        with tempfile.TemporaryDirectory() as temp:
            root = make_install(temp)
            for target, status in (
                    (root / "game" / "citadel", dof_preflight.VERIFY_FILES),
                    (root / "game" / "citadel" / "shaders_pc_dir.vpk", dof_preflight.VERIFY_FILES),
                    (root / "game" / "bin" / "win64" / "vfx_dx11.dll", dof_preflight.READY)):
                with self.subTest(target=target.name):
                    def inspect(path, *args, **options):
                        if path == target:
                            raise PermissionError(13, "Permission denied", str(path))
                        return stat(path, *args, **options)

                    with patch.object(Path, "stat", inspect):
                        report = dof_preflight.check_installation(root)
                    text = dof_preflight.format_report(report)
                    self.assertEqual(report["status"], status)
                    self.assertIn("PermissionError", text)
                    self.assertNotIn(root.name, text)
                    self.assertNotIn(root.name, json.dumps(report))
                    self.assertFalse(report["dynamic_compile"]["available"])


class PreflightIntegrationTests(unittest.TestCase):
    def test_selected_install_can_be_checked_before_any_launch(self):
        controller = Controller()
        with tempfile.TemporaryDirectory() as temp:
            root = make_install(temp)
            report = controller.dof_preflight(root)
        self.assertEqual(report["status"], dof_preflight.READY)
        self.assertIsNone(controller._launch_attempt)

    def test_unselected_install_falls_back_to_the_last_launch(self):
        controller = Controller()
        with tempfile.TemporaryDirectory() as temp:
            root = make_install(temp)
            controller._launch_attempt = {"game_path": str(root)}
            report = controller.dof_preflight()
        self.assertEqual(report["status"], dof_preflight.READY)

    def test_gui_checks_the_selected_path_and_reads_tk_only_before_submission(self):
        from dolly.gui import DollyApp

        app = DollyApp.__new__(DollyApp)
        app.controller = Controller()
        app.controller._launch_attempt = {"game_path": "unused/previous-install"}
        app._dof_checked = Mock()
        app._submit = Mock()
        with tempfile.TemporaryDirectory() as temp:
            root = make_install(temp)
            app.game_path = SimpleNamespace(get=Mock(return_value=str(root)))
            app._check_dof()
            app.game_path.get.assert_called_once_with()
            app.game_path.get.side_effect = AssertionError("worker accessed Tk")
            report = app._submit.call_args.args[1]()
        self.assertEqual(report["status"], dof_preflight.READY)


class VpkListingTests(unittest.TestCase):
    def test_listing_filters_and_limits(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "pak01_dir.vpk"
            write_vpk(path, {
                "shaders/vfx/dof_pc_50_ps.vcs": b"ps",
                "shaders/vfx/dof_pc_50_vs.vcs": b"vs",
                "materials/dev/dof1_general.vmat_c": b"mat"})
            found = panorama_assets.list_vpk_entries(path, prefixes=("shaders/vfx/dof_",))
            self.assertEqual(sorted(found), ["shaders/vfx/dof_pc_50_ps.vcs",
                                             "shaders/vfx/dof_pc_50_vs.vcs"])
            with self.assertRaises(ValueError):
                panorama_assets.list_vpk_entries(path, prefixes=("shaders/",), max_entries=1)
            with self.assertRaises(ValueError):
                panorama_assets.list_vpk_entries(path)

    def test_reader_still_returns_payloads(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "pak01_dir.vpk"
            write_vpk(path, {"materials/dev/dof1_blur.vmat_c": b"blur"})
            self.assertEqual(
                panorama_assets.read_vpk_entries(path, ("materials/dev/dof1_blur.vmat_c",))[
                    "materials/dev/dof1_blur.vmat_c"], b"blur")


if __name__ == "__main__":
    unittest.main()
