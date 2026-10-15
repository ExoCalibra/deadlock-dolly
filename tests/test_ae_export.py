"""After Effects camera export tests"""

import json
import math
from pathlib import Path
import random
import re
import tempfile
import unittest

from dolly.ae_export import (angle_vectors, ae_rotation, build_jsx, comp_size, export_jsx,
                             horizontal_fov, sample_camera, ae_vector)
from dolly.path import AttachKey, Keyframe, Project


def camera(time, x=0, y=0, z=0, pitch=0, yaw=0, roll=0, aspect=16 / 9):
    return Keyframe(time, x, y, z, pitch, yaw, roll, aspect_ratio=aspect)


def ae_matrix(x, y, z):
    """R = Rx · Ry · Rz with standard right-handed matrices, angles in degrees."""
    a, b, c = (math.radians(v) for v in (x, y, z))
    rx = [[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]]
    ry = [[math.cos(b), 0, math.sin(b)], [0, 1, 0], [-math.sin(b), 0, math.cos(b)]]
    rz = [[math.cos(c), -math.sin(c), 0], [math.sin(c), math.cos(c), 0], [0, 0, 1]]

    def mul(left, right):
        return [[sum(left[i][k] * right[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    return mul(mul(rx, ry), rz)


def column(matrix, index):
    return tuple(matrix[row][index] for row in range(3))


class CoordinateTests(unittest.TestCase):
    def assertVector(self, actual, expected, places=7):
        for a, e in zip(actual, expected):
            self.assertAlmostEqual(a, e, places=places)

    def test_source_axes_map_to_after_effects_axes(self):
        self.assertEqual(ae_vector(1, 0, 0), (1, 0, 0))  # forward stays +X
        self.assertEqual(ae_vector(0, 0, 1), (0, -1, 0))  # up is AE -Y
        self.assertEqual(ae_vector(0, 1, 0), (0, 0, 1))  # left is AE +Z

    def test_rotation_reproduces_camera_axes_for_random_poses(self):
        generator = random.Random(7)
        poses = [(0, 0, 0), (89, 0, 0), (-89, 45, 0), (90, 30, 10), (-90, -120, 5), (0, 180, 180)]
        poses += [(generator.uniform(-89, 89), generator.uniform(-360, 360), generator.uniform(-180, 180))
                  for _ in range(200)]
        for pose in poses:
            forward, right, up = angle_vectors(*pose)
            for candidate in ae_rotation(*pose):
                matrix = ae_matrix(*candidate)
                with self.subTest(pose=pose, candidate=candidate):
                    self.assertVector(column(matrix, 2), ae_vector(*forward))
                    self.assertVector(column(matrix, 0), ae_vector(*right))
                    self.assertVector(column(matrix, 1), tuple(-v for v in ae_vector(*up)))

    def test_level_camera_facing_source_left_is_a_y_rotation(self):
        # Source yaw 90 looks along +Y (left), which is AE +Z: the AE default view.
        x, y, z = ae_rotation(0, 90, 0)[0]
        self.assertVector((x, y, z), (0, 0, 0))

    def test_default_lens_is_source_90_degrees_at_4_by_3(self):
        self.assertAlmostEqual(horizontal_fov(.75, 4 / 3), 90)
        self.assertAlmostEqual(horizontal_fov(.75, 16 / 9), 106.2602047, places=6)
        with self.assertRaises(ValueError):
            horizontal_fov(100, 4)

    def test_comp_size_follows_standard_aspect(self):
        self.assertEqual(comp_size(16 / 9), (1920, 1080))
        self.assertEqual(comp_size(21 / 9), (1920, 822))


class SamplingTests(unittest.TestCase):
    def test_samples_every_frame_through_the_shot_end(self):
        shot = Project(keyframes=[camera(0, x=0), camera(1, x=100)], interpolation="linear")
        samples, _ = sample_camera(shot, 30)
        self.assertEqual(len(samples), 31)
        self.assertAlmostEqual(samples[15]["time"], .5)
        self.assertAlmostEqual(samples[15]["position"][0], 50)
        self.assertAlmostEqual(samples[-1]["position"][0], 100)

    def test_positions_follow_the_project_evaluator(self):
        shot = Project(keyframes=[camera(0, 0, 0, 0), camera(1.3, 400, -50, 90),
                                  camera(2.1, 500, 300, 40), camera(4, -20, 10, 0)])
        samples, _ = sample_camera(shot, 24)
        for sample in samples:
            pose = shot.evaluate(sample["time"])
            self.assertEqual(sample["position"], ae_vector(pose["x"], pose["y"], pose["z"]))

    def test_yaw_across_180_stays_continuous(self):
        shot = Project(keyframes=[camera(0, yaw=170), camera(1, yaw=-170)], interpolation="linear")
        samples, _ = sample_camera(shot, 60)
        for previous, current in zip(samples, samples[1:]):
            for a, b in zip(previous["rotation"], current["rotation"]):
                self.assertLess(abs(b - a), 5)

    def test_captured_lens_drives_fov(self):
        shot = Project(keyframes=[camera(0), camera(1)], interpolation="linear")
        for key in shot.keyframes:
            key.lens_scale = math.tan(math.radians(40)) / key.aspect_ratio
        samples, warnings = sample_camera(shot, 10)
        self.assertAlmostEqual(samples[4]["fov"], 80)
        self.assertEqual(warnings, [])

    def test_attach_keys_and_missing_lens_are_reported(self):
        attached = camera(1)
        attached.source, attached.attach = "attach", AttachKey(handle=5)
        _, warnings = sample_camera(Project(keyframes=[camera(0), attached]), 10)
        self.assertEqual(len(warnings), 2)
        self.assertIn("attach", warnings[0].lower())

    def test_rejects_invalid_fps_and_empty_shots(self):
        with self.assertRaises(ValueError):
            sample_camera(Project(keyframes=[camera(0)]), 0)
        with self.assertRaises(ValueError):
            sample_camera(Project(), 30)


class ScriptTests(unittest.TestCase):
    def test_script_embeds_one_value_per_frame_and_escapes_the_name(self):
        shot = Project(name='Quote " and </script> ü', keyframes=[camera(0), camera(2, x=10)])
        script, _ = build_jsx(shot, 30)
        script.encode("ascii")
        self.assertIn('var SHOT_NAME = "Quote \\" and </script> \\u00fc";', script)
        self.assertIn("var FRAMES = 61;", script)
        self.assertIn("var COMP_WIDTH = 1920;", script)
        fovs = re.search(r"var fovs = \[(.*?)\];", script).group(1).split(",")
        self.assertEqual(len(fovs), 61)
        self.assertEqual(script.count("{"), script.count("}"))

    def test_positions_are_offsets_from_the_first_frame(self):
        shot = Project(keyframes=[camera(0, x=12000, y=-8000, z=300), camera(1, x=12100, y=-8000, z=350)],
                       interpolation="linear")
        script, _ = build_jsx(shot, 10)

        def values(name):
            return json.loads(re.search(r"var " + name + r" = (\[.*?\]);\n", script).group(1))
        self.assertEqual(values("ORIGIN"), [12000, -300, -8000])
        positions = values("positions")
        self.assertEqual(positions[0], [0, 0, 0])
        self.assertEqual(positions[-1], [100, -50, 0])
        self.assertEqual(values("dollyKeys"), [[0, 0, 0, 0], [1, 100, -50, 0]])

    def test_export_writes_the_script(self):
        shot = Project(keyframes=[camera(0), camera(1)])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "shot_camera.jsx"
            warnings = export_jsx(shot, path, 60, width=3840, height=2160)
            text = path.read_text("ascii")
            self.assertIn("var COMP_WIDTH = 3840;", text)
            self.assertIn("var COMP_HEIGHT = 2160;", text)
            self.assertEqual(len(warnings), 1)
            self.assertEqual(list(Path(folder).iterdir()), [path])


if __name__ == "__main__":
    unittest.main()
