"""Camera export tests"""

import json
import math
from pathlib import Path
import random
import re
import tempfile
import unittest

from dolly.camera_export import (angle_vectors, ae_rotation, ae_rotations, build_jsx, build_usda,
                                 comp_size, depth_of_field, export_jsx, export_usda, horizontal_fov,
                                 load_take, sample_camera, sample_camera_data, ae_vector,
                                 usd_rotation, usd_rotations)
from dolly.path import AttachKey, CvarTrack, Keyframe, Project, TrackKey


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
        take = sample_camera(shot, 30)
        self.assertEqual((len(take.frames), take.video_frames), (31, 31))
        self.assertEqual(take.frames[15].frame, 15)
        self.assertAlmostEqual(take.frames[15].time, .5)
        self.assertAlmostEqual(take.frames[15].position[0], 50)
        self.assertAlmostEqual(take.frames[-1].position[0], 100)

    def test_positions_follow_the_project_evaluator(self):
        shot = Project(keyframes=[camera(0, 0, 0, 0), camera(1.3, 400, -50, 90),
                                  camera(2.1, 500, 300, 40), camera(4, -20, 10, 0)])
        for frame in sample_camera(shot, 24).frames:
            pose = shot.evaluate(frame.time)
            self.assertEqual(frame.position, (pose["x"], pose["y"], pose["z"]))
            self.assertEqual(frame.angles, (pose["pitch"], pose["yaw"], pose["roll"]))

    def test_yaw_across_180_stays_continuous(self):
        shot = Project(keyframes=[camera(0, yaw=170), camera(1, yaw=-170)], interpolation="linear")
        rotations = ae_rotations(sample_camera(shot, 60).frames)
        for previous, current in zip(rotations, rotations[1:]):
            for a, b in zip(previous, current):
                self.assertLess(abs(b - a), 5)

    def test_captured_lens_drives_fov(self):
        shot = Project(keyframes=[camera(0), camera(1)], interpolation="linear")
        for key in shot.keyframes:
            key.lens_scale = math.tan(math.radians(40)) / key.aspect_ratio
        take = sample_camera(shot, 10)
        self.assertAlmostEqual(take.frames[4].fov, 80)
        self.assertEqual(take.warnings, [])

    def test_attach_keys_and_missing_lens_are_reported(self):
        attached = camera(1)
        attached.source, attached.attach = "attach", AttachKey(handle=5)
        warnings = sample_camera(Project(keyframes=[camera(0), attached]), 10).warnings
        self.assertEqual(len(warnings), 2)
        self.assertIn("attach", warnings[0].lower())

    def test_export_speed_stretches_the_camera_over_the_longer_video(self):
        shot = Project(keyframes=[camera(0, x=0), camera(1, x=100)], interpolation="linear")
        take = sample_camera(shot, 30, speed=.5) 
        self.assertEqual((len(take.frames), take.video_frames), (61, 61))
        self.assertAlmostEqual(take.frames[30].time, 1)
        self.assertAlmostEqual(take.frames[30].position[0], 50)
        self.assertAlmostEqual(take.frames[-1].position[0], 100)
        self.assertEqual(len(sample_camera(shot, 30, speed=2).frames), 16)

    def test_an_early_finish_ends_the_camera_with_the_video(self):
        shot = Project(keyframes=[camera(0, x=0), camera(1, x=100)], interpolation="linear")
        take = sample_camera(shot, 30, video_frames=10)
        self.assertEqual((len(take.frames), take.video_frames), (10, 10))
        self.assertAlmostEqual(take.frames[-1].position[0], 30)
        take = sample_camera(shot, 30, video_frames=40)
        self.assertEqual((len(take.frames), take.video_frames), (31, 40))
        self.assertIn("var FRAMES = 10;", build_jsx(shot, 30, video_frames=10)[0])
        self.assertIn("endTimeCode = 9", build_usda(shot, 30, video_frames=10)[0])

    def test_rejects_invalid_fps_and_empty_shots(self):
        with self.assertRaises(ValueError):
            sample_camera(Project(keyframes=[camera(0)]), 0)
        with self.assertRaises(ValueError):
            sample_camera(Project(), 30)
        with self.assertRaises(ValueError):
            sample_camera(Project(keyframes=[camera(0)]), 30, speed=0)
        with self.assertRaises(ValueError):
            sample_camera(Project(keyframes=[camera(0)]), 30, video_frames=0)


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

    def test_script_imports_the_recorded_video_beside_it(self):
        shot = Project(keyframes=[camera(0), camera(1)])
        script, _ = build_jsx(shot, 60, video='Dolly_Shot "ü".mp4')
        script.encode("ascii")
        self.assertIn('var VIDEO_FILE = "Dolly_Shot \\"\\u00fc\\".mp4";', script)
        self.assertIn("$.fileName", script)
        self.assertIn("item.mainSource.conformFrameRate = FPS;", script)
        self.assertIn("COMP_WIDTH = footage.width;", script)
        self.assertLess(script.index("comp.layers.add(footage)"), script.index("comp.layers.addNull()"))
        self.assertLess(script.index("COMP_WIDTH = footage.width;"), script.index("Math.tan(fovs[i]"))
        self.assertIn("var VIDEO_FILE = null;", build_jsx(shot, 60)[0])

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
        self.assertEqual(values("dollyKeys"), [[1, 0, 0, 0, 0], [2, 1, 100, -50, 0]])

    @staticmethod
    def write_camera_data(folder, rows, frames_written=10, **overrides):
        data = {"format": "deadlock-dolly-camera-track", "version": 1, "fps": 60, "fixed_step": True,
                "frames_written": frames_written,
                "fields": ["frame", "video_time", "phase", "x", "y", "z", "pitch", "yaw", "roll",
                           "horizontal_fov"],
                "frames": rows, **overrides}
        path = Path(folder) / "shot.mp4.camera-track.json"
        path.write_text(json.dumps(data), "utf-8")
        return path

    def test_camera_data_replaces_the_authored_shot(self):
        # An attach shot: the authored keys sit still, but the rendered camera moved.
        attached = camera(1, x=5000)
        attached.source, attached.attach = "attach", AttachKey(handle=5)
        shot = Project(keyframes=[camera(0, x=5000), attached])
        rows = [[frame, frame / 60, (frame - 3) / 60, 5000 + 10 * frame, 200, 64, 0, 90, 0, 80]
                for frame in range(3, 8)]
        with tempfile.TemporaryDirectory() as folder:
            camera_data = self.write_camera_data(folder, rows)
            script, warnings = build_jsx(shot, 60, camera_data=camera_data)

        def values(name):
            return json.loads(re.search(r"var " + name + r" = (\[.*?\]);\n", script).group(1))
        self.assertEqual(warnings, [])
        self.assertIn("var FRAMES = 10;", script)  # The whole video, including pre-roll.
        self.assertEqual(values("frameNumbers"), [3, 4, 5, 6, 7])
        self.assertEqual(values("ORIGIN"), [5030, -64, 200])
        self.assertEqual([p[0] for p in values("positions")], [0, 10, 20, 30, 40])
        self.assertEqual(values("fovs"), [80] * 5)
        self.assertEqual(values("rotations")[0], [0, 0, 0])

    def test_markers_come_from_the_recorded_camera_at_each_arrival(self):
        attached = camera(1, x=99999)  # Stored pose: where the free camera was at capture.
        attached.source, attached.attach = "attach", AttachKey(handle=5)
        shot = Project(keyframes=[camera(0, x=5000), camera(.5 + 1 / 120, x=-1), attached])
        # Three frames of pre-roll: frame 3 is the shot's first frame.
        rows = [[frame, frame / 60, (frame - 3) / 60, 5000 + 10 * frame, 200, 64, 0, 90, 0, 80]
                for frame in range(3, 64)]
        with tempfile.TemporaryDirectory() as folder:
            camera_data = self.write_camera_data(folder, rows, frames_written=64)
            script, _ = build_jsx(shot, 60, camera_data=camera_data)
            layer, _ = build_usda(shot, 60, camera_data=camera_data)
        keys = json.loads(re.search(r"var dollyKeys = (\[.*?\]);\n", script).group(1))
        self.assertEqual([key[0] for key in keys], [1, 2, 3])
        for key, (time, x) in zip(keys, ((.05, 0), (33.5 / 60, 305), (63 / 60, 600))):
            self.assertAlmostEqual(key[1], time, places=6)  # Video time, after the pre-roll.
            self.assertAlmostEqual(key[2], x, places=4)  # Real camera, not the stored pose.
        self.assertIn('doc = "Dolly key 3 @ 1.050s"', layer)
        self.assertIn("double3 xformOp:translate = (600, 0, 0)", layer)
        self.assertNotIn("99999", script + layer)

    def test_markers_skip_keys_the_recording_never_reached(self):
        shot = Project(keyframes=[camera(0), camera(1), camera(2)])
        rows = [[frame, frame / 60, frame / 60, frame, 0, 0, 0, 0, 0, 90] for frame in range(70)]
        with tempfile.TemporaryDirectory() as folder:
            take = load_take(shot, 60, self.write_camera_data(folder, rows, frames_written=70))
        self.assertEqual([marker.key for marker in take.markers], [1, 2])

    def test_markers_without_camera_data_leave_out_attached_and_unreached_keys(self):
        attached = camera(1, x=99999)
        attached.source, attached.attach = "attach", AttachKey(handle=5)
        shot = Project(keyframes=[camera(0), attached, camera(2, x=50), camera(3, x=80)],
                       interpolation="linear")
        take = load_take(shot, 30, speed=.5, video_frames=150)  # Finished at 5 s of 6.
        self.assertEqual([marker.key for marker in take.markers], [1, 3])
        self.assertAlmostEqual(take.markers[1].time, 4)  # Shot 2 s at half speed.
        self.assertEqual(take.markers[1].position, (50, 0, 0))
        self.assertIn("markers are left out", take.warnings[0])

    def test_camera_data_frames_follow_video_time_not_row_order(self):
        rows = [[0, 0.0, 0, 0, 0, 0, 0, 0, 0, 90], [1, 0.5, .5, 1, 0, 0, 0, 0, 0, 90]]
        with tempfile.TemporaryDirectory() as folder:
            take = sample_camera_data(self.write_camera_data(folder, rows, 2), 60)
        self.assertEqual([f.frame for f in take.frames], [0, 30])
        self.assertEqual(take.frames[1].position, (1, 0, 0))
        self.assertEqual((take.video_frames, take.warnings), (31, []))

    def test_invalid_camera_data_is_rejected(self):
        good = [[0, 0.0, 0, 0, 0, 0, 0, 0, 0, 90]]
        # "deadlock-dolly-camera" is the depth take's camera bundle, a different layout.
        cases = (dict(format="other"), dict(format="deadlock-dolly-camera"), dict(version=2),
                 dict(fields=["frame"]), dict(frames=[]),
                 dict(frames=[[0, 0.0, 0, 0, 0, 0, 0, 0, 0, 200]]),
                 dict(frames=[[0, 0.0, 0, 0, 0, 0, 0, 0, 0, float("nan")]]),
                 dict(frames=good * 2), dict(fps=None), dict(fps=True), dict(fps=0), dict(fps="60"))
        for overrides in cases:
            with self.subTest(overrides=overrides), tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(ValueError):
                    sample_camera_data(self.write_camera_data(folder, good, **overrides), 60)

    def test_camera_data_must_match_the_take_frame_rate(self):
        rows = [[0, 0.0, 0, 0, 0, 0, 0, 0, 0, 90], [1, 1 / 30, 1 / 30, 1, 0, 0, 0, 0, 0, 90]]
        with tempfile.TemporaryDirectory() as folder:
            data = self.write_camera_data(folder, rows, frames_written=2, fps=30)
            # Read at 60 fps, the 30 fps rows would land on every other frame.
            with self.assertRaisesRegex(ValueError, "recorded at 30 fps, not 60 fps"):
                sample_camera_data(data, 60)
            self.assertEqual([f.frame for f in sample_camera_data(data, 30.0).frames], [0, 1])

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


def usd_matrix(x, y, z):
    """USD rotateXYZ: R = Rz · Ry · Rx with standard right-handed matrices, degrees."""
    a, b, c = (math.radians(v) for v in (x, y, z))
    rx = [[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]]
    ry = [[math.cos(b), 0, math.sin(b)], [0, 1, 0], [-math.sin(b), 0, math.cos(b)]]
    rz = [[math.cos(c), -math.sin(c), 0], [math.sin(c), math.cos(c), 0], [0, 0, 1]]

    def mul(left, right):
        return [[sum(left[i][k] * right[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    return mul(mul(rz, ry), rx)


def usd_samples(layer, attribute):
    block = re.search(re.escape(attribute) + r"\.timeSamples = \{\n(.*?)\n\s*\}", layer, re.S).group(1)
    samples = {}
    for line in block.splitlines():
        frame, value = line.strip().rstrip(",").split(": ", 1)
        samples[int(frame)] = tuple(float(v) for v in value.strip("()").split(", "))
    return samples


class UsdTests(unittest.TestCase):
    def assertVector(self, actual, expected, places=7):
        for a, e in zip(actual, expected):
            self.assertAlmostEqual(a, e, places=places)

    def test_rotation_reproduces_camera_axes_for_random_poses(self):
        generator = random.Random(11)
        poses = [(0, 0, 0), (89, 0, 0), (-89, 45, 0), (90, 30, 10), (-90, -120, 5), (0, 180, 180)]
        poses += [(generator.uniform(-89, 89), generator.uniform(-360, 360), generator.uniform(-180, 180))
                  for _ in range(200)]
        for pose in poses:
            forward, right, up = angle_vectors(*pose)
            for candidate in usd_rotation(*pose):
                matrix = usd_matrix(*candidate)
                with self.subTest(pose=pose, candidate=candidate):
                    # A USD camera looks down its local -Z with +Y up, in Source world axes.
                    self.assertVector(column(matrix, 0), right)
                    self.assertVector(column(matrix, 1), up)
                    self.assertVector(column(matrix, 2), tuple(-v for v in forward))

    def test_level_camera_facing_source_forward(self):
        # Blender's convention for a level camera looking down +X.
        self.assertVector(usd_rotation(0, 0, 0)[0], (90, 0, -90))

    def test_yaw_across_180_stays_continuous(self):
        shot = Project(keyframes=[camera(0, yaw=170, roll=20), camera(1, yaw=-170, roll=-20)],
                       interpolation="linear")
        rotations = usd_rotations(sample_camera(shot, 60).frames)
        for previous, current in zip(rotations, rotations[1:]):
            for a, b in zip(previous, current):
                self.assertLess(abs(b - a), 5)

    def test_layer_keys_every_frame_in_source_axes(self):
        shot = Project(name='Quote " and \\ ü', interpolation="linear",
                       keyframes=[camera(0, x=12000, y=-8000, z=300), camera(1, x=12100, z=350)])
        layer, warnings = build_usda(shot, 10, width=1920, height=1080)
        self.assertTrue(layer.startswith("#usda 1.0\n"))
        layer.encode("ascii")
        for line in ('upAxis = "Z"', "metersPerUnit = 0.0254", "framesPerSecond = 10",
                     "timeCodesPerSecond = 10", "startTimeCode = 0", "endTimeCode = 10",
                     "double3 origin = (12000, -8000, 300)", 'string shot = "Quote \\" and \\\\ ?"',
                     "float horizontalAperture = 36", "float verticalAperture = 20.25"):
            self.assertIn(line, layer)
        translate = usd_samples(layer, "double3 xformOp:translate")
        self.assertEqual(sorted(translate), list(range(11)))
        self.assertEqual(translate[0], (0, 0, 0))
        self.assertEqual(translate[10], (100, 8000, 50))  # Offsets keep Source axes.
        self.assertEqual(len(usd_samples(layer, "float3 xformOp:rotateXYZ")), 11)
        self.assertIn("double3 xformOp:translate = (100, 8000, 50)", layer)  # Key 2 marker.
        self.assertEqual(len(warnings), 1)
        self.assertEqual(layer.count("{"), layer.count("}"))

    def test_focal_length_reproduces_the_horizontal_fov(self):
        shot = Project(keyframes=[camera(0), camera(1)], interpolation="linear")
        for key in shot.keyframes:
            key.lens_scale = math.tan(math.radians(40)) / key.aspect_ratio
        layer, _ = build_usda(shot, 4)
        for (focal,) in usd_samples(layer, "float focalLength").values():
            self.assertAlmostEqual(math.degrees(2 * math.atan(18 / focal)), 80, places=4)

    def test_camera_data_keys_its_own_video_frames(self):
        rows = [[frame, frame / 60, frame / 60, 10 * frame, 0, 0, 0, 0, 0, 90] for frame in range(3, 6)]
        with tempfile.TemporaryDirectory() as folder:
            data = ScriptTests.write_camera_data(folder, rows, frames_written=8)
            layer, warnings = build_usda(Project(keyframes=[camera(0), camera(1)]), 60, camera_data=data)
        self.assertEqual(warnings, [])
        self.assertIn("endTimeCode = 7", layer)
        self.assertEqual(sorted(usd_samples(layer, "double3 xformOp:translate")), [3, 4, 5])
        self.assertEqual(usd_samples(layer, "float focalLength")[3], (18,))

    def test_export_writes_the_layer(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "shot_camera.usda"
            export_usda(Project(keyframes=[camera(0), camera(1)]), path, 30)
            self.assertTrue(path.read_text("ascii").startswith("#usda 1.0"))
            self.assertEqual(list(Path(folder).iterdir()), [path])


def citadel_shot(**setup):
    """A 2 s shot whose Citadel focus pulls from 200 to 600 inches."""
    values = {"r_depth_of_field": 1, "r_citadel_depthoffield_enable": 1,
              "r_citadel_depthoffield_aperture_diameter": .5, **setup}
    return Project(keyframes=[camera(0), camera(2)], interpolation="linear",
                   setup_values={name: value for name, value in values.items() if value is not None},
                   tracks=[CvarTrack("r_citadel_depthoffield_focus_distance",
                                     [TrackKey(0, 200.0), TrackKey(2, 600.0)], "linear")])


class DepthOfFieldTests(unittest.TestCase):
    def test_citadel_lens_follows_the_shot_every_frame(self):
        shot = citadel_shot()
        lenses, warnings = depth_of_field(shot, sample_camera(shot, 10).frames)
        self.assertEqual((len(lenses), warnings), (21, []))
        self.assertEqual(lenses[0], (200, .5))
        self.assertAlmostEqual(lenses[10][0], 400)
        self.assertEqual(lenses[-1], (600, .5))

    def test_after_effects_camera_gets_the_lens_in_comp_pixels(self):
        script, warnings = build_jsx(citadel_shot(), 10)
        dof = json.loads(re.search(r"var dof = (\[.*?\]); //", script).group(1))
        self.assertEqual((dof[0], dof[-1]), ([200, .5], [600, .5]))
        for match_name in ("ADBE Camera Depth of Field", "ADBE Camera Focus Distance",
                           "ADBE Camera Aperture", "ADBE Camera Blur Level"):
            self.assertIn(match_name, script)
        self.assertNotIn("isn't", " ".join(warnings))

    def test_usd_camera_gets_focus_distance_and_f_stop(self):
        layer, _ = build_usda(citadel_shot(), 10)
        focus = usd_samples(layer, "float focusDistance")
        self.assertEqual((focus[0], focus[20]), ((200,), (600,)))
        # Default lens at 16:9: 106.26 degrees, focal length 13.5, so f/2.7 at a 0.5 inch aperture.
        for (stop,) in usd_samples(layer, "float fStop").values():
            self.assertAlmostEqual(stop, 13.5 / 10 / .5, places=5)

    def test_a_shot_without_depth_of_field_exports_none(self):
        shot = Project(keyframes=[camera(0), camera(1)])
        script, _ = build_jsx(shot, 10)
        self.assertIn("var dof = null;", script)
        self.assertNotIn("focusDistance", build_usda(shot, 10)[0])
        self.assertEqual(depth_of_field(shot, sample_camera(shot, 10).frames), (None, []))

    def test_switching_the_lens_off_holds_focus_and_stops_the_blur(self):
        shot = citadel_shot()
        shot.tracks.append(CvarTrack("r_citadel_depthoffield_enable",
                                     [TrackKey(0, 1.0), TrackKey(1, 0.0)], "step"))
        lenses, _ = depth_of_field(shot, sample_camera(shot, 10).frames)
        self.assertEqual(lenses[9], (380, .5))
        self.assertEqual(lenses[15], (380, 0))  # Focus holds where the lens switched off.
        stops = usd_samples(build_usda(shot, 10)[0], "float fStop")
        self.assertEqual(stops[15], (0,))

    def test_range_dof_and_unauthored_choices_are_reported(self):
        ranges = Project(keyframes=[camera(0), camera(1)],
                         setup_values={"r_depth_of_field": 1, "r_dof_override": 1})
        lenses, warnings = depth_of_field(ranges, sample_camera(ranges, 10).frames)
        self.assertIsNone(lenses)
        self.assertIn("Native range DOF isn't a lens", warnings[0])
        shot = Project(keyframes=[camera(0), camera(1)],
                       setup_values={"r_depth_of_field": 1, "r_citadel_depthoffield_enable": 1,
                                     "r_citadel_depthoffield_aperture_diameter": .5,
                                     "r_citadel_depthoffield_mode": 1})
        lenses, warnings = depth_of_field(shot, sample_camera(shot, 10).frames)
        self.assertEqual(lenses[0], (200, .5))
        self.assertEqual(len(warnings), 2)  # Unauthored focus, and the near-only mode.
        self.assertIn("near-only", build_jsx(shot, 10)[1][-1] + build_jsx(shot, 10)[1][-2])

    def test_recorded_frames_use_the_shot_time_they_rendered(self):
        rows = [[frame, frame / 10, max(0, frame - 5) / 10, 0, 0, 0, 0, 0, 0, 90] for frame in range(15)]
        with tempfile.TemporaryDirectory() as folder:
            data = ScriptTests.write_camera_data(folder, rows, frames_written=15, fps=10)
            take = load_take(citadel_shot(), 10, data)
        lenses, _ = depth_of_field(citadel_shot(), take.frames)
        self.assertEqual(lenses[5][0], 200)  # Half a second of pre-roll before the shot starts.
        self.assertAlmostEqual(lenses[14][0], 380)


if __name__ == "__main__":
    unittest.main()
