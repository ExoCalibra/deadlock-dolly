"""Saved XYZ handle intent and the shared camera motion/compiler contract."""

import copy
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest

from dolly.native_path import CHANNEL_RECORD, HEADER_BYTES, SEGMENT_BYTES, compile_project
from dolly.path import CameraTangent, CvarTrack, Keyframe, Project, TrackKey


def camera(time, x=0, y=0, z=0):
    return Keyframe(time, x, y, z, 0, 0, 0)


class AuthoredTangentTests(unittest.TestCase):
    def test_flat_two_key_arrival_departure_and_unchanged_channels(self):
        shot = Project(keyframes=[camera(0), camera(2, 10, 20, 30)])
        legacy = compile_project(shot)
        self.assertTrue(shot.set_camera_tangent(0, "x", "flat"))
        self.assertTrue(shot.set_camera_tangent(1, "x", "flat"))
        samples = shot.camera_channel_samples("x")
        for time, expected in ((-.1, 0), (0, 0), (.5, 1.5625), (1, 5), (1.5, 8.4375), (2, 10), (3, 10)):
            with self.subTest(time=time):
                self.assertEqual(shot.evaluate(time)["x"], expected)
                self.assertEqual(samples.evaluate(time), expected)
        data = compile_project(shot)
        offset = HEADER_BYTES + 16
        self.assertEqual(CHANNEL_RECORD.unpack_from(data, offset), (2, 0, 0, 10, 0, 0))
        self.assertEqual(data[offset + CHANNEL_RECORD.size:], legacy[offset + CHANNEL_RECORD.size:])
        self.assertEqual(shot.interpolation, "smooth")

    def test_broken_sides_have_independent_world_units_per_second(self):
        shot = Project(keyframes=[camera(0), camera(1, 10), camera(2, 20)])
        shot.set_camera_tangent(1, "x", "broken", incoming=0, outgoing=20)
        self.assertEqual(shot.camera_tangent_slopes(1, "x"), (0, 20))
        self.assertEqual(shot.evaluate(.5)["x"], 6.25)
        self.assertEqual(shot.evaluate(1.5)["x"], 16.25)
        data = compile_project(shot)
        left = CHANNEL_RECORD.unpack_from(data, HEADER_BYTES + 16)
        right = CHANNEL_RECORD.unpack_from(data, HEADER_BYTES + SEGMENT_BYTES + 16)
        self.assertEqual(left[-2:], (10, 0))
        self.assertEqual(right[-2:], (20, 10))

    def test_linked_shares_a_slope_and_auto_restores_old_motion_and_format(self):
        shot = Project(keyframes=[camera(0), camera(.5, 10), camera(3, -5)])
        before, blob = shot.to_dict(), compile_project(shot)
        self.assertEqual(shot.camera_tangent(1, "x"), CameraTangent())
        self.assertEqual(shot.camera_tangent_slopes(1, "x"), (-5 / 3, -5 / 3))
        shot.set_camera_tangent(1, "x", "linked", incoming=7, outgoing=7)
        self.assertEqual(shot.camera_tangent_slopes(1, "x"), (7, 7))
        self.assertFalse(shot.set_camera_tangent(1, "x", "linked", incoming=7, outgoing=7))
        self.assertTrue(shot.set_camera_tangent(1, "x", "auto"))
        self.assertFalse(shot.set_camera_tangent(1, "x", "auto"))
        self.assertEqual(shot.keyframes[1].tangents, {})
        self.assertEqual(shot.to_dict(), before)
        self.assertEqual(compile_project(shot), blob)
        shot.keyframes[1].tangents["x"] = CameraTangent()
        self.assertEqual(shot.to_dict(), before)
        self.assertTrue(shot.set_camera_tangent(1, "x", "auto"))
        self.assertEqual(shot.keyframes[1].tangents, {})

    def test_saved_handles_are_dormant_in_linear_and_spline(self):
        shot = Project(keyframes=[camera(0), camera(.7, 10), camera(2, -4)])
        old = copy.deepcopy(shot)
        shot.set_camera_tangent(1, "x", "broken", incoming=-30, outgoing=100)
        authored = copy.deepcopy(shot.keyframes[1].tangents)
        for mode in ("linear", "spline"):
            shot.interpolation = old.interpolation = mode
            with self.subTest(mode=mode):
                self.assertEqual(compile_project(shot), compile_project(old))
                self.assertEqual(shot.camera_tangent_slopes(1, "x"), old.camera_tangent_slopes(1, "x"))
                for time in (.1, .4, .7, 1, 1.8):
                    self.assertEqual(shot.evaluate(time), old.evaluate(time))
                self.assertEqual(Project.from_dict(shot.to_dict()), shot)
        shot.interpolation = old.interpolation = "smooth"
        self.assertNotEqual(shot.evaluate(.4)["x"], old.evaluate(.4)["x"])
        self.assertEqual(shot.keyframes[1].tangents, authored)

    def test_save_reopen_and_copy_keep_only_authored_channel_metadata(self):
        shot = Project(keyframes=[camera(0), camera(1, 10)])
        shot.set_camera_tangent(0, "x", "flat")
        shot.set_camera_tangent(1, "z", "broken", incoming=-2.5, outgoing=3.25)
        data = shot.to_dict()
        self.assertEqual(data["version"], 12)
        self.assertEqual(data["keyframes"][0]["tangents"], {"x": {"mode": "flat"}})
        self.assertEqual(data["keyframes"][1]["tangents"],
                         {"z": {"mode": "broken", "incoming": -2.5, "outgoing": 3.25}})
        with tempfile.TemporaryDirectory(prefix="dolly-handles-") as folder:
            path = Path(folder) / "saved.dolly.json"
            shot.save(path)
            reopened = Project.load(path)
        self.assertEqual(reopened, shot)
        copied = copy.deepcopy(reopened)
        copied.set_camera_tangent(1, "z", "auto")
        self.assertEqual(reopened.camera_tangent(1, "z"), CameraTangent("broken", -2.5, 3.25))
        self.assertEqual(compile_project(reopened), compile_project(shot))

    def test_malformed_schema_and_unsupported_channels_are_rejected(self):
        shot = Project(keyframes=[camera(0), camera(1, 10)])
        shot.set_camera_tangent(1, "x", "flat")
        valid = shot.to_dict()
        malformed = (
            [], {"yaw": {"mode": "flat"}}, {"X": {"mode": "flat"}},
            {"x": []}, {"x": {}}, {"x": {"mode": "unknown"}},
            {"x": {"mode": "flat", "incoming": 0}},
            {"x": {"mode": "auto", "outgoing": 0}},
            {"x": {"mode": "linked", "incoming": 1, "outgoing": 2}},
            {"x": {"mode": "broken", "incoming": 1}},
            {"x": {"mode": "broken", "incoming": True, "outgoing": 1}},
            {"x": {"mode": "broken", "incoming": math.nan, "outgoing": 1}},
            {"x": {"mode": "broken", "incoming": 1, "outgoing": math.inf}},
            {"x": {"mode": "broken", "incoming": "1", "outgoing": 1}},
            {"x": {"mode": "flat", "weight": 1}},
        )
        for tangents in malformed:
            data = copy.deepcopy(valid)
            data["keyframes"][1]["tangents"] = tangents
            with self.subTest(tangents=tangents), self.assertRaises(ValueError):
                Project.from_dict(data)
        data = copy.deepcopy(valid)
        data["version"] = 11
        with self.assertRaisesRegex(ValueError, "tangents"):
            Project.from_dict(data)
        shot.keyframes[1].tangents = {"x": {"mode": "flat"}}
        with self.assertRaisesRegex(ValueError, "CameraTangent"):
            shot.validate()

    def test_setter_rejects_invalid_changes_without_partial_mutation(self):
        shot = Project(keyframes=[camera(0), camera(1, 10)])
        shot.set_camera_tangent(1, "x", "linked", incoming=5, outgoing=5)
        before = shot.to_dict()
        calls = (
            (-1, "x", "flat", {}), (True, "x", "flat", {}), (2, "x", "flat", {}),
            (1, "pitch", "flat", {}), (1, "x", "bad", {}),
            (1, "x", "flat", {"incoming": 0}),
            (1, "x", "broken", {"incoming": 1, "outgoing": False}),
            (1, "x", "linked", {"incoming": 1, "outgoing": 2}),
        )
        for index, channel, mode, kwargs in calls:
            with self.subTest(index=index, channel=channel, mode=mode), self.assertRaises(ValueError):
                shot.set_camera_tangent(index, channel, mode, **kwargs)
            self.assertEqual(shot.to_dict(), before)

    def test_retime_scales_dormant_derivatives_and_preserves_replay_shape(self):
        shot = Project(keyframes=[camera(0), camera(1, 10), camera(3, -5)],
                       tracks=[CvarTrack("r_dof", [TrackKey(2, 1)])])
        shot.set_camera_tangent(1, "x", "broken", incoming=3, outgoing=-4)
        original = copy.deepcopy(shot)
        shot.interpolation = "linear"
        shot.retime(32)
        self.assertEqual([key.time for key in shot.keyframes], [0, 2, 6])
        self.assertEqual(shot.tracks[0].keys[0].time, 4)
        self.assertEqual(shot.camera_tangent(1, "x"), CameraTangent("broken", 1.5, -2))
        shot.interpolation = "smooth"
        for time in (.2, .7, 1, 1.7, 2.9):
            self.assertAlmostEqual(shot.evaluate(time * 2)["x"], original.evaluate(time)["x"], places=12)
        shot.retime(64)
        self.assertEqual(shot, original)

    def test_retime_overflow_is_atomic(self):
        shot = Project(keyframes=[camera(0), camera(1, 10)], interpolation="linear")
        shot.set_camera_tangent(1, "x", "linked", incoming=1e308, outgoing=1e308)
        before = shot.to_dict()
        with self.assertRaisesRegex(ValueError, "finite"):
            shot.retime(640)
        self.assertEqual(shot.to_dict(), before)

    def test_no_authored_data_preserves_legacy_json_and_native_bytes(self):
        shot = Project(name="Compatibility fixture", keyframes=[
            Keyframe(.25, 1, 2, 3, 4, 170, -170),
            Keyframe(.8, 12, -5, 8, 30, -170, 150),
            Keyframe(2.4, -4, 7, 10, -10, 160, -140),
        ])
        # Pinned before adding this feature; protects old serialization and the
        # existing protocol, including intentionally unclamped Spline channels.
        expected = {
            "smooth": ("f27f8a709250325ce1e269b1b5a179801c3a629e393567c8ddc7270847d13dc5",
                       "7f404766cd904bdcc25c4617e49214c9f5bc938da58202a2767e73f473ddd8d9"),
            "linear": ("dcd826c4ab7a1cb1aab8beec89d6f6de6eb76c0b967eb623f3a027c8ee124858",
                       "80a5e7ff2c1241f7df1e555bb676587efeb4a911de0cb679b8e633b203553625"),
            "spline": ("7a235710da39360f0fac2b307f7f90bad2e8d71d4fb0d4d328d5b86dcf65fedf",
                       "ebd7a556cb99c87f303721a1b2670ef510e11a3b288ad729cfb4edc0295ba638"),
        }
        for mode, (json_hash, blob_hash) in expected.items():
            shot.interpolation = mode
            encoded = json.dumps(shot.to_dict(), sort_keys=True, separators=(",", ":")).encode()
            with self.subTest(mode=mode):
                self.assertEqual(hashlib.sha256(encoded).hexdigest(), json_hash)
                self.assertEqual(hashlib.sha256(compile_project(shot)).hexdigest(), blob_hash)

    def test_single_key_and_unrepresentable_auto_derivatives_stay_finite(self):
        shot = Project(keyframes=[camera(1, 10)])
        shot.set_camera_tangent(0, "x", "flat")
        self.assertEqual(shot.camera_tangent_slopes(0, "x"), (0, 0))
        self.assertEqual(shot.evaluate(2)["x"], 10)
        tiny = Project(keyframes=[camera(0), camera(1e-310, 1), camera(2, 10)])
        self.assertTrue(all(math.isfinite(value) for value in tiny.camera_tangent_slopes(1, "x")))
        self.assertEqual(tiny.camera_channel_samples("x").interpolation, "linear")
        self.assertEqual(CHANNEL_RECORD.unpack_from(compile_project(tiny), HEADER_BYTES + 16)[0], 1)
        with self.assertRaisesRegex(ValueError, "cannot be represented"):
            tiny.set_camera_tangent(1, "x", "flat")

    def test_authored_segments_reject_bridge_faults_without_clamping(self):
        shot = Project(keyframes=[camera(0), camera(2, 10)])
        before = shot.to_dict()
        for slope in (1e9, 1e308):
            with self.subTest(slope=slope), self.assertRaisesRegex(ValueError, "position range|too large"):
                shot.set_camera_tangent(0, "x", "broken", incoming=0, outgoing=slope)
            self.assertEqual(shot.to_dict(), before)
        # A steep but supported path stays authored; no arbitrary slope cap.
        shot.set_camera_tangent(0, "x", "linked", incoming=1e8, outgoing=1e8)
        self.assertEqual(shot.camera_tangent_slopes(0, "x"), (1e8, 1e8))
        self.assertGreater(shot.evaluate(.5)["x"], 1e7)
        # An endpoint's unused side is saved intent, not part of this segment.
        shot.set_camera_tangent(0, "x", "broken", incoming=1e308, outgoing=0)
        self.assertEqual(shot.evaluate(.5)["x"], 1.09375)
        boundary = Project(keyframes=[camera(0), camera(2)])
        boundary.set_camera_tangent(0, "x", "broken", incoming=0, outgoing=2e8)
        boundary.set_camera_tangent(1, "x", "broken", incoming=-2e8, outgoing=0)
        self.assertEqual(boundary.evaluate(1)["x"], 1e8)
        with self.assertRaisesRegex(ValueError, "position range"):
            boundary.set_camera_tangent(0, "x", "broken", incoming=0, outgoing=2e8 + 1)

    def test_unsafe_dormant_metadata_is_preserved_and_checked_on_smooth_activation(self):
        shot = Project(keyframes=[camera(0), camera(2, 10)], interpolation="linear")
        shot.set_camera_tangent(0, "x", "broken", incoming=0, outgoing=1e308)
        for mode in ("linear", "spline"):
            shot.interpolation = mode
            reopened = Project.from_dict(shot.to_dict())
            self.assertEqual(reopened.camera_tangent(0, "x"), CameraTangent("broken", 0, 1e308))
            self.assertEqual(reopened.evaluate(.5)["x"], 2.5)
        shot.interpolation = "smooth"
        with self.assertRaisesRegex(ValueError, "too large"):
            shot.validate()


if __name__ == "__main__":
    unittest.main()
