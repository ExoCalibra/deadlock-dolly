"""Only content mods join a Dolly session; render and visual overrides stay out."""
from pathlib import Path
import tempfile
import unittest

from dolly import mod_policy
from test_panorama_assets import write_vpk


class ModPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name) / "game"
        self.addons = self.game / "citadel" / "addons"

    def mount(self, *names):
        for name in names:
            path = self.addons / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"content")
        return self.addons

    def test_skin_map_and_audio_content_is_allowed(self):
        root = self.mount(
            "models/heroes/haze/haze_body.vmdl",
            "materials/models/heroes/haze/haze_body.vmat",
            "maps/custom_map.vmap",
            "sound/music/theme.vsnd",
            "README.txt",
            "licence.txt")
        self.assertEqual(mod_policy.classify_mount(root),
                         {"allowed": True, "reason": None, "evidence": []})

    def test_environment_material_override_is_refused(self):
        root = self.mount("materials/environment/sky_noon.vmat")
        verdict = mod_policy.classify_mount(root)
        self.assertFalse(verdict["allowed"])
        self.assertIn("visual material", verdict["reason"])

    def test_loose_render_and_interface_overrides_are_refused(self):
        for index, name in enumerate(("panorama/layout/hud.xml", "shaders/hero.vfx",
                                      "particles/effects/trail.vpcf", "cfg/autoexec.cfg")):
            with self.subTest(name=name):
                root = Path(self.temp.name) / f"mount{index}" / "addons"
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"content")
                self.assertFalse(mod_policy.classify_mount(root)["allowed"])

    def test_mod_folder_inside_a_shared_mount_is_classified_one_level_down(self):
        root = self.mount("my_skin/models/heroes/x.vmdl",
                          "my_skin/materials/models/heroes/x.vmat")
        self.assertTrue(mod_policy.classify_mount(root)["allowed"])
        (root / "qol_ui" / "panorama").mkdir(parents=True)
        (root / "qol_ui" / "panorama" / "hud.xml").write_bytes(b"ui")
        verdict = mod_policy.classify_mount(root)
        self.assertTrue(verdict["allowed"])
        self.assertTrue(verdict["mixed_skin"])

    def test_vpk_pack_is_classified_from_its_directory_tree(self):
        self.addons.mkdir(parents=True)
        write_vpk(self.addons / "pak01_dir.vpk", {"models/heroes/x.vmdl": b"model"})
        self.assertTrue(mod_policy.classify_mount(self.addons)["allowed"])
        write_vpk(self.addons / "pak01_dir.vpk", {"models/heroes/x.vmdl": b"model",
                                                  "panorama/layout/hud.xml": b"ui"})
        verdict = mod_policy.classify_mount(self.addons)
        self.assertTrue(verdict["allowed"])
        self.assertTrue(verdict["mixed_skin"])
        write_vpk(self.addons / "pak01_dir.vpk", {"panorama/layout/hud.xml": b"ui"})
        verdict = mod_policy.classify_mount(self.addons)
        self.assertFalse(verdict["allowed"])
        self.assertIn("panorama", verdict["reason"])

    def test_unreadable_pack_is_refused_instead_of_guessed(self):
        self.addons.mkdir(parents=True)
        (self.addons / "pak01_dir.vpk").write_bytes(b"not a vpk")
        verdict = mod_policy.classify_mount(self.addons)
        self.assertFalse(verdict["allowed"])
        self.assertIn("could not be checked", verdict["reason"])

    def test_mixed_skin_pack_is_automatic_and_force_override_is_explicit(self):
        root = self.mount("models/heroes/holiday.vmdl",
                          "panorama/layout/holiday.vxml",
                          "postprocessing/holiday.vpost")
        automatic = mod_policy.classify_mount(root)
        self.assertTrue(automatic["allowed"])
        self.assertTrue(automatic["mixed_skin"])
        carried, excluded = mod_policy.split_mounts([("Game", "citadel/addons")], self.game)
        self.assertEqual(excluded, [])
        self.assertTrue(carried[0]["mixed_skin"])
        allowed = mod_policy.classify_mount(root, allow_overrides=True)
        self.assertTrue(allowed["allowed"])
        self.assertTrue(allowed["allow_overrides"])
        carried, excluded = mod_policy.split_mounts(
            [("Game", "citadel/addons")], self.game, allow_overrides=True)
        self.assertEqual(excluded, [])
        self.assertTrue(carried[0]["allow_overrides"])

    def test_metadata_mounts_only_travel_with_carried_content(self):
        self.mount("models/heroes/x.vmdl")
        mounts = [("Game", "citadel/addons"), ("Mod", "citadel"), ("Write", "citadel"),
                  ("AddonRoot", "citadel_addons")]
        carried, excluded = mod_policy.split_mounts(mounts, self.game)
        self.assertEqual([record["key"] for record in carried],
                         ["Game", "Mod", "Write", "AddonRoot"])
        self.assertEqual(excluded, [])
        environment = self.game / "citadel" / "addons_env" / "materials" / "environment"
        environment.mkdir(parents=True)
        (environment / "fog.vmat").write_bytes(b"content")
        carried, excluded = mod_policy.split_mounts(
            [("Game", "citadel/addons_env"), ("Mod", "citadel")], self.game)
        self.assertEqual(carried, [])
        self.assertEqual([record["path"] for record in excluded], ["citadel/addons_env"])
        self.assertIn("visual material", excluded[0]["reason"])

    def test_mount_outside_the_game_or_missing_is_refused(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        carried, excluded = mod_policy.split_mounts(
            [("Game", "../outside"), ("Game", "citadel/addons")], self.game)
        self.assertEqual(carried, [])
        self.assertEqual([record["path"] for record in excluded], ["../outside", "citadel/addons"])

    def test_addon_root_is_classified_like_a_content_mount(self):
        self.mount("models/heroes/x.vmdl")
        (self.game / "citadel_addons" / "panorama").mkdir(parents=True)
        (self.game / "citadel_addons" / "panorama" / "hud.xml").write_bytes(b"ui")
        carried, excluded = mod_policy.split_mounts(
            [("Game", "citadel/addons"), ("AddonRoot", "citadel_addons")], self.game)
        self.assertEqual([record["key"] for record in carried], ["Game"])
        self.assertEqual([record["key"] for record in excluded], ["AddonRoot"])
        self.assertIn("panorama", excluded[0]["reason"])


if __name__ == "__main__":
    unittest.main()
