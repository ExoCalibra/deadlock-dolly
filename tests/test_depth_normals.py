"""Depth normal reconstruction fixtures (SourceMVM roadmap Phase 4).

Scenes are synthesized analytically per pixel: view-space planes and spheres
are intersected with the documented pinhole parameterization
(``P(t) = (ndc_x*t/sx, ndc_y*t/sy, -t)``, ``t`` = camera-axis distance), boxes
and creases combine exact per-pixel intersections with a z-buffer, and the
expected normals are the analytic surface normals. One fully hand-computed
5x5 plane pins the conventions independently of the generator, and a
two-camera world-space check pins the rotation handling.
"""

from __future__ import annotations

import math
import unittest

import numpy as np

from dolly.camera_bundle import parse_bundle
from dolly.depth_normals import reconstruct_normals, view_points, world_normals
from test_camera_bundle import bundle, record


def parsed_record(index: int = 0, **overrides):
    return parse_bundle(bundle([record(index, **overrides)])).records[0]


def _rotate_basis(yaw_deg: float, pitch_deg: float):
    yaw, pitch = math.radians(yaw_deg), math.radians(pitch_deg)

    def rotate(vector):
        x, y, z = vector
        x, y, z = x, y * math.cos(pitch) - z * math.sin(pitch), y * math.sin(pitch) + z * math.cos(pitch)
        return (x * math.cos(yaw) + z * math.sin(yaw), y, -x * math.sin(yaw) + z * math.cos(yaw))

    return (rotate((1.0, 0.0, 0.0)), rotate((0.0, 1.0, 0.0)), rotate((0.0, 0.0, 1.0)))


def rotated_record(index: int = 0, yaw_deg: float = 0.0, pitch_deg: float = 0.0,
                   position=(0.0, 0.0, 0.0)):
    columns = _rotate_basis(yaw_deg, pitch_deg)
    view = [0.0] * 16
    for axis in range(3):
        for component in range(3):
            view[component * 4 + axis] = columns[axis][component]
    for axis in range(3):
        view[12 + axis] = -sum(columns[axis][c] * position[c] for c in range(3))
    view[15] = 1.0
    forward = tuple(-component for component in columns[2])
    return parse_bundle(bundle([record(index, view=view, position=list(position),
                                       up=list(columns[1]), forward=list(forward))])).records[0]


def ray_directions(record, width: int, height: int):
    """Per-pixel forward ray direction; the distance ``t`` scales it exactly."""
    assert record.projection[14] == -1.0 and record.projection[15] == 0.0, \
        "fixture generator expects the standard projection family"
    ndc_x = 2.0 * (np.arange(width) + 0.5) / width - 1.0
    ndc_y = 1.0 - 2.0 * (np.arange(height) + 0.5) / height
    sx, sy = record.projection[0], record.projection[5]
    return np.stack([np.broadcast_to(ndc_x[None, :] / sx, (height, width)),
                     np.broadcast_to(ndc_y[:, None] / sy, (height, width)),
                     -np.ones((height, width))], axis=-1)


def plane_depth(directions, normal, offset):
    """Distances to the view-space plane ``normal . P = offset`` (front side)."""
    normal = np.asarray(normal, dtype=np.float64)
    denominator = directions @ normal
    distances = np.full(directions.shape[:2], np.inf)
    front = denominator < 0.0
    with np.errstate(divide="ignore", invalid="ignore"):
        candidate = offset / denominator
    use = front & np.isfinite(candidate) & (candidate > 0.0)
    distances[use] = candidate[use]
    return distances


def sphere_depth(directions, center, radius):
    """Distances to the front surface of a view-space sphere (inf = no hit)."""
    center = np.asarray(center, dtype=np.float64)
    a = np.sum(directions * directions, axis=-1)
    b = -2.0 * (directions @ center)
    c0 = float(center @ center) - radius * radius
    discriminant = b * b - 4.0 * a * c0
    distances = np.full(directions.shape[:2], np.inf)
    hit = discriminant > 0.0
    root = np.sqrt(np.where(hit, discriminant, 0.0))
    front = (-b - root) / (2.0 * a)
    back = (-b + root) / (2.0 * a)
    chosen = np.where(front > 0.0, front, back)
    use = hit & (chosen > 0.0)
    distances[use] = chosen[use]
    return distances


def face_over_plane(directions, normal, offset, face_distance, half_x, half_y):
    """A fronto-parallel face at ``face_distance`` over a background plane."""
    background = plane_depth(directions, normal, offset)
    point = directions * face_distance
    inside = (np.abs(point[..., 0]) <= half_x) & (np.abs(point[..., 1]) <= half_y)
    inside &= (face_distance < background) & np.isfinite(background)
    return np.where(inside, face_distance, background), inside


def two_plane_depth(directions, plane_a, plane_b):
    """Per-pixel nearest of two view-space planes; returns distances and mask."""
    distance_a = plane_depth(directions, plane_a[0], plane_a[1])
    distance_b = plane_depth(directions, plane_b[0], plane_b[1])
    a_wins = distance_a <= distance_b
    return np.where(a_wins, distance_a, distance_b), a_wins


def dilate(mask: np.ndarray, passes: int = 1) -> np.ndarray:
    out = mask.copy()
    for _ in range(passes):
        grown = out.copy()
        grown[1:, :] |= out[:-1, :]
        grown[:-1, :] |= out[1:, :]
        grown[:, 1:] |= out[:, :-1]
        grown[:, :-1] |= out[:, 1:]
        out = grown
    return out


def angular_errors_degrees(normals, expected) -> np.ndarray:
    normals = np.asarray(normals, dtype=np.float64)
    expected = np.broadcast_to(np.asarray(expected, dtype=np.float64), normals.shape)
    a = normals / np.linalg.norm(normals, axis=-1, keepdims=True)
    b = expected / np.linalg.norm(expected, axis=-1, keepdims=True)
    dots = np.clip(np.sum(a * b, axis=-1), -1.0, 1.0)
    return np.degrees(np.arccos(dots))


class DepthNormalsTests(unittest.TestCase):
    def test_view_point_mapping_known_pixels(self):
        camera = parsed_record()
        distances = np.full((4, 5), 10.0)
        points, valid = view_points(camera, distances)
        self.assertTrue(valid.all())
        # Pixel (0, 0): ndc = (-0.8, 0.75), cw = 10 -> (-8, 7.5, -10).
        self.assertTrue(np.allclose(points[0, 0], (-8.0, 7.5, -10.0)))
        # Pixel (x=2, y=3): ndc = (0, -0.75) -> (0, -7.5, -10).
        self.assertTrue(np.allclose(points[3, 2], (0.0, -7.5, -10.0)))
        invalid = distances.copy()
        invalid[1, 1] = np.inf
        points, valid = view_points(camera, invalid)
        self.assertFalse(valid[1, 1])
        self.assertTrue(np.isnan(points[1, 1]).all())

    def test_shifted_camera_points_and_slanted_normals_match_pixel_intrinsics(self):
        # A homogeneous scale of two, aspect 2.4, and a principal point shifted
        # -0.75px horizontally and -0.5px vertically. Generate the rays from
        # pixel-space focal lengths/principal point independently of view_points.
        projection = [1.5, 0, 3 / 64, 0, 0, 3.6, -2 / 48, 0,
                      0, 0, 0, 14, 0, 0, -2, 0]
        camera = parsed_record(projection=projection, inverse_z=[0, -.5, 1 / 14, 0])
        points, valid = view_points(camera, np.full((48, 64), 10.0))
        self.assertTrue(valid.all())
        np.testing.assert_allclose(points[0, 0], (-12.8125, 230 / 43.2, -10), atol=1e-10)
        x, y = np.meshgrid(np.arange(64) + .5, np.arange(48) + .5)
        directions = np.stack(((x - 31.25) / 24, -(y - 23.5) / 43.2,
                               -np.ones((48, 64))), axis=-1)
        normal = np.array([.35, .15, 1.0]) / np.linalg.norm([.35, .15, 1.0])
        distances = plane_depth(directions, normal, -25)
        frame = reconstruct_normals(camera, distances)
        self.assertTrue(frame.valid.all())
        errors = angular_errors_degrees(frame.normals, normal)
        self.assertLess(float(np.max(errors)), 1e-3)

    def test_front_plane_faces_the_camera(self):
        camera = parsed_record()
        directions = ray_directions(camera, 64, 48)
        distances = plane_depth(directions, (0.0, 0.0, 1.0), -30.0)
        frame = reconstruct_normals(camera, distances)
        self.assertEqual(frame.space, "view")
        self.assertTrue(frame.valid.all())
        self.assertTrue(np.allclose(frame.normals, (0.0, 0.0, 1.0), atol=1e-6))
        # Borders fall back to one-sided gradients; the interior stays central.
        self.assertTrue(frame.one_sided[0].all() and frame.one_sided[:, 0].all())
        self.assertFalse(frame.one_sided[5:-5, 5:-5].any())

    def test_hand_computed_tilted_plane(self):
        # View-space plane z = -0.25*y - 10, i.e. normal (0, 0.25, 1)/|..|.
        # The 5x5 grid's centre normal was derived by hand from explicit
        # per-pixel intersections. A 5-pixel grid has a far larger per-pixel
        # step than any real capture, so this fixture widens the compatibility
        # window explicitly (the default window is exercised elsewhere).
        camera = parsed_record()
        directions = ray_directions(camera, 5, 5)
        distances = plane_depth(directions, (0.0, 0.25, 1.0), -10.0)
        frame = reconstruct_normals(camera, distances, step_relative=0.2, step_absolute=1.0)
        expected = np.array([0.0, 0.25, 1.0]) / np.linalg.norm([0.0, 0.25, 1.0])
        for component, value in enumerate(expected):
            self.assertAlmostEqual(float(frame.normals[2, 2, component]), float(value), places=6)

    def test_slanted_plane_matches_analytic(self):
        camera = parsed_record()
        directions = ray_directions(camera, 96, 72)
        normal = np.array([0.35, 0.15, 1.0]) / np.linalg.norm([0.35, 0.15, 1.0])
        distances = plane_depth(directions, normal, -25.0)
        frame = reconstruct_normals(camera, distances)
        self.assertTrue(frame.valid.mean() > 0.95)
        errors = angular_errors_degrees(frame.normals, normal)
        self.assertLess(float(np.nanmax(errors[frame.valid])), 1e-3)

    def test_sphere_normals_match_analytic(self):
        camera = parsed_record()
        directions = ray_directions(camera, 128, 96)
        center = (0.0, 0.0, -60.0)
        distances = sphere_depth(directions, center, 25.0)
        frame = reconstruct_normals(camera, distances)
        valid = frame.valid
        # The sphere covers about a sixth of the frame; outside it rays miss.
        self.assertGreater(float(valid.mean()), 0.10)
        self.assertLess(float(valid.mean()), 0.25)
        points, _ = view_points(camera, distances)
        errors = angular_errors_degrees(frame.normals, points - np.asarray(center))
        # Away from the silhouette the two-pixel chord error is small; the
        # grazing ring naturally carries larger error and is bounded separately.
        ring = dilate(~valid, passes=2)
        interior = valid & ~ring
        self.assertLess(float(np.nanmax(errors[interior])), 1.0)
        self.assertLess(float(np.nanmax(errors[valid])), 15.0)

    def test_silhouette_keeps_faces_flat(self):
        # A fronto-parallel face over a fronto-parallel background: every valid
        # normal must stay (0, 0, 1); the compatibility window must stop the
        # gradient from smearing across the step.
        camera = parsed_record()
        directions = ray_directions(camera, 128, 96)
        distances, inside = face_over_plane(directions, (0.0, 0.0, 1.0), -60.0, 30.0, 20.0, 16.0)
        frame = reconstruct_normals(camera, distances)
        self.assertTrue(frame.valid.all())
        errors = angular_errors_degrees(frame.normals, (0.0, 0.0, 1.0))
        self.assertLess(float(np.nanmax(errors)), 1e-3)
        edge = dilate(inside ^ np.roll(inside, 1, axis=0) | (inside ^ np.roll(inside, 1, axis=1)))
        self.assertTrue(frame.one_sided[edge].any())

    def test_crease_between_tilted_faces(self):
        camera = parsed_record()
        directions = ray_directions(camera, 128, 96)
        normal_b = np.array([0.5, 0.0, 1.0]) / np.linalg.norm([0.5, 0.0, 1.0])
        offset_b = float(normal_b @ np.array([0.0, 0.0, -30.0]))
        distances, a_wins = two_plane_depth(directions, ((0.0, 0.0, 1.0), -30.0),
                                            (normal_b, offset_b))
        expected = np.where(a_wins[..., None], np.array([0.0, 0.0, 1.0]), normal_b)
        frame = reconstruct_normals(camera, distances)
        self.assertTrue(frame.valid.all())
        switch = a_wins != np.roll(a_wins, 1, axis=0)
        switch |= a_wins != np.roll(a_wins, 1, axis=1)
        band = dilate(switch, passes=2)
        errors = angular_errors_degrees(frame.normals, expected)
        self.assertLess(float(np.nanmax(errors[~band])), 0.5)
        self.assertEqual(int(np.isnan(frame.normals[frame.valid]).sum()), 0)

    def test_far_and_invalid_depth_are_masked(self):
        camera = parsed_record()
        directions = ray_directions(camera, 32, 32)
        distances = plane_depth(directions, (0.0, 0.0, 1.0), -30.0)
        distances[0:4, 0:4] = np.inf
        distances[4:8, 4:8] = np.nan
        distances[8:12, 8:12] = 0.0
        frame = reconstruct_normals(camera, distances)
        self.assertFalse(frame.valid[0:4, 0:4].any())
        self.assertFalse(frame.valid[4:8, 4:8].any())
        self.assertFalse(frame.valid[8:12, 8:12].any())
        self.assertTrue(np.isfinite(frame.normals[frame.valid]).all())
        self.assertTrue(np.isnan(frame.normals[~frame.valid]).all())
        # The ring around an invalid block loses its crossing neighbor and is
        # flagged as one-sided while staying valid.
        self.assertTrue(frame.one_sided[4, 1:3].any() or frame.one_sided[1:3, 4].any())

    def test_world_normals_agree_under_camera_rotation(self):
        world_normal = np.array([0.30, 0.10, 1.0]) / np.linalg.norm([0.30, 0.10, 1.0])
        world_offset = float(world_normal @ np.array([0.0, 0.0, -30.0]))
        cameras = [rotated_record(0, yaw_deg=0.0),
                   rotated_record(0, yaw_deg=40.0, pitch_deg=10.0, position=(3.0, 1.0, 0.0))]
        for camera in cameras:
            matrix = camera.view.matrix
            columns = np.array([[matrix[0], matrix[4], matrix[8]],
                                [matrix[1], matrix[5], matrix[9]],
                                [matrix[2], matrix[6], matrix[10]]])
            view_normal = columns @ world_normal
            view_offset = world_offset - float(world_normal @ np.asarray(camera.view.position))
            directions = ray_directions(camera, 96, 72)
            distances = plane_depth(directions, view_normal, view_offset)
            frame = reconstruct_normals(camera, distances, world=True)
            self.assertEqual(frame.space, "world")
            self.assertTrue(frame.valid.any())
            errors = angular_errors_degrees(frame.normals, world_normal)
            self.assertLess(float(np.nanmax(errors[frame.valid])), 0.1)

    def test_world_normals_roundtrip(self):
        camera = parsed_record()
        view = np.array([0.0, 0.0, 1.0])
        world = world_normals(camera, view[None, None, :])
        self.assertTrue(np.allclose(world[0, 0], (0.0, 0.0, 1.0)))

    def test_smoothing_reduces_noise_without_crossing_edges(self):
        camera = parsed_record()
        directions = ray_directions(camera, 128, 96)
        distances = plane_depth(directions, (0.0, 0.0, 1.0), -40.0)
        rng = np.random.default_rng(7)
        noisy = distances + rng.normal(0.0, 0.05, distances.shape)
        plain = reconstruct_normals(camera, noisy)
        smoothed = reconstruct_normals(camera, noisy, smoothing=2)
        self.assertEqual(smoothed.smoothing, 2)
        mask = plain.valid & smoothed.valid
        error_plain = angular_errors_degrees(plain.normals, (0.0, 0.0, 1.0))
        error_smoothed = angular_errors_degrees(smoothed.normals, (0.0, 0.0, 1.0))
        self.assertLess(float(np.mean(error_smoothed[mask])), float(np.mean(error_plain[mask])))
        # A step edge must not be crossed by smoothing: both faces are
        # fronto-parallel, so every valid normal stays exactly (0, 0, 1).
        stepped, _ = face_over_plane(directions, (0.0, 0.0, 1.0), -60.0, 30.0, 20.0, 16.0)
        edge_smoothed = reconstruct_normals(camera, stepped, smoothing=2)
        self.assertTrue(edge_smoothed.valid.all())
        edge_errors = angular_errors_degrees(edge_smoothed.normals, (0.0, 0.0, 1.0))
        self.assertLess(float(np.nanmax(edge_errors)), 1e-3)

    def test_invalid_inputs_are_rejected(self):
        camera = parsed_record()
        for distances in (np.zeros((0, 0)), [1.0, 2.0, 3.0]):
            with self.subTest(distances=distances):
                with self.assertRaises(ValueError):
                    reconstruct_normals(camera, distances)
        zero_scale = parsed_record(projection=[0, 0, 0, 0, 0, 1, 0, 0,
                                               0, 0, 0, 7, 0, 0, -1, 0])
        with self.assertRaises(ValueError):
            reconstruct_normals(zero_scale, np.full((4, 4), 10.0))
        with self.assertRaises(ValueError):
            reconstruct_normals(camera, np.full((4, 4), 10.0), step_relative=-1.0)
        with self.assertRaises(ValueError):
            reconstruct_normals(camera, np.full((4, 4), 10.0), smoothing=-1)


if __name__ == "__main__":
    unittest.main()
