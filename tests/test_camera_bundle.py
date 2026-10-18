"""Camera bundle format, validation and reprojection fixtures.

The known-camera fixtures use the reviewed per-view layout: an identity view
looking down −Z, a perspective with near clip 7 and an infinite far plane, and
the horizontal/vertical scale set to 1. Expected pixels are computed by hand in
the assertions (not by calling the implementation twice).
"""

from __future__ import annotations

import json
import math
import struct
import tempfile
import unittest
from pathlib import Path

from dolly.camera_bundle import (
    FORMAT,
    VERSION,
    CameraBundleError,
    linearize,
    load_bundle,
    parse_bundle,
    project_point,
    validate_against_manifest,
    validate_bundle,
)


def f32(value: float) -> float:
    """Round a number through binary32, like the sampled constants do."""
    return struct.unpack("<f", struct.pack("<f", value))[0]


def identity_view() -> dict:
    return {
        "view": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
        "position": [0, 0, 0],
        "up": [0, 1, 0],
        "forward": [0, 0, -1],
    }


def standard_projection(near: float = 7.0) -> list:
    return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, near, 0, 0, -1, 0]


def standard_inverse(near: float = 7.0) -> list:
    return [0.0, -1.0, 1.0 / near, 0.0]


def record(index: int = 0, **overrides) -> dict:
    data = {
        "frame": index,
        "sample": index,
        "replay_time": 1.25 + index,
        "capture_pts_100ns": index * 333333,
        "state": "complete",
        "projection": standard_projection(),
        "inverse_z": standard_inverse(),
        "viewport": [0, 1],
        "near": 7,
        "far": None,
    }
    data.update(identity_view())
    data.update(overrides)
    return data


def partial_record(index: int = 0, **overrides) -> dict:
    data = record(index, state="projection-only", **overrides)
    for key in ("view", "position", "up", "forward"):
        data.pop(key)
    return data


def bundle(records: list, **overrides) -> dict:
    data = {
        "format": FORMAT,
        "version": VERSION,
        "complete": True,
        "frames": len(records),
        "width": 100,
        "height": 50,
        "color_width": 100,
        "color_height": 50,
        "records": records,
    }
    data.update(overrides)
    return data


class BundleParsingTests(unittest.TestCase):
    def test_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "camera.json"
            path.write_text(json.dumps(bundle([record(0), record(1)])), encoding="utf-8")
            loaded = load_bundle(path)
        self.assertEqual(loaded.frames, 2)
        self.assertEqual([item.frame for item in loaded.records], [0, 1])
        self.assertTrue(loaded.complete)
        self.assertEqual(loaded.width, 100)
        self.assertIsNone(loaded.records[0].far)
        self.assertEqual(loaded.records[0].state, "complete")
        self.assertIsNotNone(loaded.records[0].view)

    def test_unknown_extra_keys_are_tolerated(self):
        loaded = parse_bundle(bundle([record(0)], note="producer extension"))
        self.assertEqual(len(loaded.records), 1)

    def test_rejects_wrong_format_and_version(self):
        for mutate in ({"format": "other"}, {"version": 2}, {"version": "1"}):
            with self.subTest(mutate=mutate):
                with self.assertRaises(CameraBundleError):
                    parse_bundle(bundle([record(0)], **mutate))

    def test_rejects_malformed_input(self):
        cases = {
            "not an object": [],
            "records missing": {"format": FORMAT, "version": VERSION, "complete": True,
                                "frames": 0, "width": 1, "height": 1,
                                "color_width": 1, "color_height": 1},
            "records not list": {**bundle([record(0)]), "records": {"frame": 0}},
            "missing projection": bundle([{key: value for key, value in record(0).items()
                                           if key != "projection"}]),
            "short projection": bundle([record(0, projection=[1, 0, 0])]),
            "non-finite": bundle([record(0, projection=[math.inf] + standard_projection()[1:])]),
            "unknown state": bundle([record(0, state="sampled")]),
            "viewport inverted": bundle([record(0, viewport=[0.5, 0.4])]),
            "viewport out of range": bundle([record(0, viewport=[-0.1, 1.0])]),
            "negative near": bundle([record(0, near=-1)]),
            "far before near": bundle([record(0, near=7, far=2)]),
            "view fields on partial": {**bundle([partial_record(0)]),
                                       "records": [{**partial_record(0), "view": [1] * 16}]},
            "missing far": bundle([{key: value for key, value in record(0).items()
                                    if key != "far"}]),
            "zero width": bundle([record(0)], width=0),
            "missing frames": bundle([record(0)], frames=None),
        }
        for name, payload in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(CameraBundleError):
                    parse_bundle(payload)


class ReprojectionTests(unittest.TestCase):
    def test_identity_camera_known_points(self):
        loaded = parse_bundle(bundle([record(0)]))
        item = loaded.records[0]
        center = project_point(loaded, item, (0, 0, -7))
        self.assertAlmostEqual(center.x, 50.0, places=9)
        self.assertAlmostEqual(center.y, 25.0, places=9)
        self.assertAlmostEqual(center.device_z, 1.0, places=9)
        self.assertAlmostEqual(center.distance, 7.0, places=9)
        offset = project_point(loaded, item, (1, 0, -14))
        self.assertAlmostEqual(offset.x, (1.0 + 1.0 / 14.0) * 50.0, places=9)
        self.assertAlmostEqual(offset.device_z, 0.5, places=9)
        self.assertAlmostEqual(offset.distance, 14.0, places=9)
        above = project_point(loaded, item, (0, 1, -7))
        self.assertAlmostEqual(above.y, (1.0 - 1.0 / 7.0) * 25.0, places=9)

    def test_rotated_view_known_points(self):
        rotation = {
            "view": [0, 0, 1, 0, 0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 0, 1],
            "position": [0, 0, 0],
            "up": [0, 1, 0],
            "forward": [-1, 0, 0],
        }
        loaded = parse_bundle(bundle([record(0, **rotation)]))
        self.assertEqual(validate_bundle(loaded), [])
        item = loaded.records[0]
        front = project_point(loaded, item, (-7, 0, 0))  # along the camera forward
        self.assertAlmostEqual(front.x, 50.0, places=9)
        self.assertAlmostEqual(front.y, 25.0, places=9)
        self.assertAlmostEqual(front.distance, 7.0, places=9)
        raised = project_point(loaded, item, (-7, 1, 0))
        self.assertAlmostEqual(raised.y, (1.0 - 1.0 / 7.0) * 25.0, places=9)

    def test_behind_and_at_the_camera_are_not_projectable(self):
        loaded = parse_bundle(bundle([record(0)]))
        item = loaded.records[0]
        self.assertIsNone(project_point(loaded, item, (0, 0, 7)))
        self.assertIsNone(project_point(loaded, item, (0, 0, 0)))

    def test_moved_camera_records_track_the_same_point(self):
        # The camera shifts along +X between records; the same world point must
        # move left on screen exactly as the translation predicts.
        records = []
        for index, shift in enumerate((0.0, 1.0, 3.0)):
            data = record(index)
            data["view"] = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -shift, 0, 0, 1]
            data["position"] = [shift, 0, 0]
            records.append(data)
        loaded = parse_bundle(bundle(records))
        self.assertEqual(validate_bundle(loaded), [])
        for index, shift in enumerate((0.0, 1.0, 3.0)):
            projected = project_point(loaded, loaded.records[index], (0, 0, -7))
            self.assertAlmostEqual(projected.x, (1.0 - shift / 7.0) * 50.0, places=9)
            self.assertAlmostEqual(projected.y, 25.0, places=9)
            self.assertAlmostEqual(projected.distance, 7.0, places=9)

    def test_collinear_world_points_stay_collinear_on_screen(self):
        # A projective map sends lines to lines; an axis swap or sign error
        # breaks this, so the plane fixture catches broken pixel mappings.
        loaded = parse_bundle(bundle([record(0)]))
        item = loaded.records[0]
        line = [(-3.0, 0.0, -10.0), (0.5, 2.0, -10.0), (4.0, 4.0, -10.0)]
        pixels = [project_point(loaded, item, point) for point in line]
        for projected in pixels:
            self.assertIsNotNone(projected)
        (x0, y0), (x1, y1), (x2, y2) = ((projected.x, projected.y) for projected in pixels)
        twice_area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        self.assertAlmostEqual(twice_area, 0.0, places=6)

    def test_forward_and_inverse_agree_for_distances(self):
        loaded = parse_bundle(bundle([record(0)]))
        item = loaded.records[0]
        for distance in (7.0, 14.0, 700.0, 7000.0):
            with self.subTest(distance=distance):
                projected = project_point(loaded, item, (0, 0, -distance))
                self.assertAlmostEqual(projected.distance, distance, places=6)

    def test_float32_sampled_values_stay_in_tolerance(self):
        near = f32(7.0)
        payload = record(0, projection=[f32(value) for value in standard_projection(near)],
                         inverse_z=[f32(value) for value in standard_inverse(near)], near=near)
        loaded = parse_bundle(bundle([payload]))
        self.assertEqual(validate_bundle(loaded), [])
        projected = project_point(loaded, loaded.records[0], (0, 0, -7))
        self.assertAlmostEqual(projected.distance, 7.0, places=4)

    def test_subpixel_projection_offsets_preserve_depth_and_pixel_shift(self):
        projection = [2 * value for value in standard_projection()]
        projection[2], projection[6] = f32(3 / 2560), f32(2 / 1440)
        loaded = parse_bundle(bundle([record(
            projection=projection, inverse_z=[value / 2 for value in standard_inverse()])],
            width=2560, height=1440, color_width=3840, color_height=2160))
        self.assertEqual(validate_bundle(loaded), [])
        item = loaded.records[0]
        self.assertEqual(item.projection, tuple(projection))
        projected = project_point(loaded, item, (0, 0, -14))
        self.assertAlmostEqual(projected.x, 1280 - .75, places=6)
        self.assertAlmostEqual(projected.y, 720 + .5, places=6)
        self.assertAlmostEqual(projected.device_z, .5, places=9)
        self.assertAlmostEqual(projected.distance, 14, places=9)

    def test_projection_only_records_cannot_project(self):
        payload = partial_record(0)
        loaded = parse_bundle(bundle([payload], complete=False, partial_reason="missing-view"))
        self.assertEqual(validate_bundle(loaded), [])
        self.assertIsNone(project_point(loaded, loaded.records[0], (0, 0, -7)))
        self.assertEqual(validate_bundle(loaded, require_complete=True),
                         ["bundle is not complete"])


class LinearizeTests(unittest.TestCase):
    def test_known_rule(self):
        inverse = standard_inverse()
        self.assertAlmostEqual(linearize(inverse, 0, 1, 1.0), 7.0, places=9)
        self.assertAlmostEqual(linearize(inverse, 0, 1, 0.5), 14.0, places=9)

    def test_edges(self):
        inverse = standard_inverse()
        self.assertEqual(linearize(inverse, 0, 1, 0.0), math.inf)
        self.assertIsNone(linearize(inverse, 0, 1, -0.1))
        self.assertIsNone(linearize(inverse, 0, 1, 1.5))
        self.assertIsNone(linearize(inverse, 0.5, 0.5, 0.5))
        self.assertIsNone(linearize([1, 1, 0, 1], 0, 1, 0.5))


class ValidationTests(unittest.TestCase):
    def test_valid_bundle_passes(self):
        loaded = parse_bundle(bundle([record(0), record(1)]))
        self.assertEqual(validate_bundle(loaded), [])

    def test_projection_offsets_are_bounded_by_one_depth_pixel(self):
        for axis, pixels in ((2, 2560), (6, 1440)):
            for scale in (.5, 1, 2):
                for shift in (-1, .5, 1, 1.001, 123):
                    with self.subTest(axis=axis, scale=scale, shift=shift):
                        projection = [scale * value for value in standard_projection()]
                        projection[axis] = f32(2 * scale * shift / pixels)
                        loaded = parse_bundle(bundle([record(
                            projection=projection,
                            inverse_z=[value / scale for value in standard_inverse()])],
                            width=2560, height=1440, color_width=1920, color_height=1080))
                        issues = validate_bundle(loaded)
                        if abs(shift) <= 1:
                            self.assertEqual(issues, [])
                        else:
                            self.assertTrue(any('jitter' in issue for issue in issues), issues)
        for index in (1, 3, 4, 7, 8, 9, 12, 13):
            with self.subTest(malformed_index=index):
                projection = standard_projection()
                projection[index] = 123
                issues = validate_bundle(parse_bundle(bundle([record(projection=projection)])))
                self.assertTrue(any('oblique' in issue for issue in issues), issues)

    def test_tampering_is_flagged(self):
        cases = {
            "frame count": (bundle([record(0)], frames=5), "record count"),
            "non-sequential frames": (bundle([record(0), record(1, frame=3)]), "not sequential"),
            "sample order": (bundle([record(0), record(1, sample=0)]), "strictly increasing"),
            "zero scale": (bundle([record(0, projection=[0] + standard_projection()[1:])]),
                           "scale is zero"),
            "oblique": (bundle([record(0, projection=standard_projection()[:1] + [0.01]
                                   + standard_projection()[2:])]), "oblique"),
            "inverse mismatch": (bundle([record(0, inverse_z=[0, -1, 0.2, 0])]),
                                 "does not invert"),
            "non-orthonormal view": (bundle([record(0, view=[2, 0, 0, 0, 0, 1, 0, 0,
                                                             0, 0, 1, 0, 0, 0, 0, 1])]),
                                     "orthonormal"),
            "up disagrees": (bundle([record(0, up=[0, 0, 1])]), "up/forward"),
            "translation mismatches": (bundle([record(0, view=[1, 0, 0, 0, 0, 1, 0, 0,
                                                               0, 0, 1, 0, 5, 0, 0, 1])]),
                                       "translation"),
            "partial record in complete bundle":
                (bundle([record(0), partial_record(1)]), "projection-only"),
            "incomplete without reason": (bundle([partial_record(0)], complete=False),
                                          "no partial_reason"),
            "complete with reason":
                (bundle([record(0)], partial_reason="missing-view"), "carries a partial_reason"),
            "more records than frames":
                (bundle([record(0), partial_record(1)], complete=False, frames=1,
                        partial_reason="truncated"), "more records than frames"),
        }
        for name, (payload, needle) in cases.items():
            with self.subTest(name=name):
                loaded = parse_bundle(payload)
                issues = validate_bundle(loaded)
                self.assertTrue(any(needle in issue for issue in issues),
                                f"expected an issue containing {needle!r}, got {issues}")

    def test_manifest_cross_check(self):
        loaded = parse_bundle(bundle([record(0), record(1)]))
        manifest = {"frames": 2, "complete": True, "width": 100, "height": 50}
        self.assertEqual(validate_against_manifest(loaded, manifest), [])
        self.assertTrue(validate_against_manifest(
            loaded, {"frames": 3, "complete": True, "width": 100, "height": 50}))
        self.assertTrue(validate_against_manifest(
            loaded, {"frames": 2, "complete": True, "width": 99, "height": 50}))
        partial = parse_bundle(bundle([partial_record(0)], complete=False,
                                      partial_reason="missing-view"))
        self.assertTrue(validate_against_manifest(
            partial, {"frames": 1, "complete": True, "width": 100, "height": 50}))
        self.assertEqual(validate_against_manifest(loaded, "not a manifest"),
                         ["manifest is not an object"])


if __name__ == "__main__":
    unittest.main()
