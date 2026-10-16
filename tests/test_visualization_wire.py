"""Bounded transport and real portable-C++ parity for the optional path guide."""

import copy
import math
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

from dolly.path import Keyframe, Project
from dolly.visualization_wire import (
    ABI, HEADER, HEADER_BYTES, KEY_METADATA, MAGIC, MAPPING_BYTES, MAX_MARKERS, MAX_SAMPLES,
    build_visualization,
)


def shot(count=3):
    return Project(keyframes=[Keyframe(i, i * 100, i * i * 10, i * 30,
                                       i * 10, i * 45, 0, aspect_ratio=16 / 9)
                              for i in range(count)])


class VisualizationWireTests(unittest.TestCase):
    def test_layout_keeps_original_path_and_timestamps(self):
        from dolly.native_path import compile_project
        project = shot()
        original = copy.deepcopy(project.to_dict())
        blob = build_visualization(project, sequence=24, selected_camera=1)
        header = HEADER.unpack_from(blob)
        self.assertEqual(HEADER_BYTES, 64)
        self.assertEqual(header[:6], (MAGIC, 24, ABI, 1, 1, 3))
        self.assertEqual(header[7:], (2048, 64, 0, 0, 3 * KEY_METADATA.size, 2, 0))
        self.assertEqual(struct.unpack_from("<3d", blob, 64), (0, 1, 2))
        self.assertEqual(blob[88 + 3 * KEY_METADATA.size:], compile_project(project))
        self.assertEqual(project.to_dict(), original)

    def test_clearing_and_size_limits(self):
        for project, enabled in ((None, True), (Project(), True), (shot(), False)):
            blob = build_visualization(project, enabled=enabled)
            self.assertEqual(len(blob), 64)
            self.assertEqual(HEADER.unpack_from(blob)[3:7], (0, 0, 0, 0))
        blob = build_visualization(shot(4096), selected_camera=4095,
                                   sample_budget=2, marker_budget=MAX_MARKERS)
        self.assertLess(len(blob), MAPPING_BYTES)
        self.assertEqual(HEADER.unpack_from(blob)[7], MAX_SAMPLES)
        with self.assertRaises(ValueError):
            build_visualization(shot(4097))

    def test_rejects_bad_config_and_project(self):
        for kwargs in ({"sequence": 0}, {"sequence": 3}, {"sequence": True},
                       {"sequence": 0x100000000}, {"enabled": 1},
                       {"selected_camera": 3}, {"selected_camera": -1},
                       {"sample_budget": 4097}, {"sample_budget": 1},
                       {"marker_budget": 129}, {"marker_budget": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                build_visualization(shot(), **kwargs)
        with self.assertRaises(ValueError):
            build_visualization({})
        bad = shot()
        bad.keyframes[0].x = math.nan
        with self.assertRaises(ValueError):
            build_visualization(bad)

    def test_shot_revision_is_separate_from_transport_sequence_and_path_bytes(self):
        project = shot()
        first = build_visualization(project, sequence=20, revision=7)
        second = build_visualization(project, sequence=22, revision=8)
        self.assertEqual(HEADER.unpack_from(first)[9], 7)
        self.assertEqual(HEADER.unpack_from(second)[9], 8)
        self.assertEqual(first[64:], second[64:])
        self.assertEqual(HEADER.unpack_from(build_visualization(None, revision=9))[9], 9)
        for revision in (-1, 0x100000000, True, 1.5, math.nan, "1"):
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                build_visualization(project, revision=revision)


    def test_metadata_preserves_authored_angles_source_and_session(self):
        project = shot()
        project.keyframes[1].yaw = 359
        project.keyframes[1].curve_yaw = 721
        project.keyframes[1].lens_scale = .875
        blob = build_visualization(project, session_id=0xF123456789ABCDEF, revision=17)
        header = HEADER.unpack_from(blob)
        self.assertEqual(header[10:14], (0xF123456789ABCDEF, 3 * KEY_METADATA.size, 2, 0))
        values = KEY_METADATA.unpack_from(blob, 64 + 24 + KEY_METADATA.size)
        self.assertEqual(values[:7], (100, 10, 30, 10, 721, 0, 16 / 9))
        self.assertEqual(values[7:9], (0, 0))
        project.rotation_mode = "unwrapped"
        self.assertEqual(HEADER.unpack_from(build_visualization(project))[12], 3)
        for session in (-1, 1 << 64, True, .5, math.nan, "1"):
            with self.subTest(session=session), self.assertRaises(ValueError):
                build_visualization(project, session_id=session)

    def test_tangent_metadata_keeps_saved_intent_and_matches_automatic_evaluator(self):
        from dolly.native_path import compile_project
        project = shot()
        project.set_camera_tangent(1, "x", "broken", incoming=-12, outgoing=55)
        project.set_camera_tangent(1, "y", "flat")
        project.set_camera_tangent(2, "z", "linked", incoming=3, outgoing=3)
        original = copy.deepcopy(project)
        for interpolation in ("smooth", "linear", "spline"):
            with self.subTest(interpolation=interpolation):
                project.interpolation = interpolation
                blob = build_visualization(project)
                self.assertEqual(ABI, 4)
                self.assertEqual(KEY_METADATA.size, 136)
                self.assertEqual(HEADER.unpack_from(blob)[12], 2 if interpolation == "smooth" else 0)
                start = 64 + 3 * 8
                rows = [KEY_METADATA.unpack_from(blob, start + i * KEY_METADATA.size) for i in range(3)]
                self.assertEqual(rows[1][9:17], (3, 0, -12, 55, 1, 0, 0, 0))
                self.assertEqual(rows[2][17:21], (2, 0, 3, 3))
                for index in range(3):
                    if index != 1:
                        incoming, outgoing = project.camera_tangent_slopes(index, "x")
                        self.assertEqual(rows[index][9:13], (0, 0, incoming, outgoing))
                self.assertEqual(blob[start + 3 * KEY_METADATA.size:], compile_project(project))
        project.interpolation = original.interpolation
        self.assertEqual(project, original)


@unittest.skipUnless(shutil.which("g++"), "Portable viewer parity requires g++; Windows CI runs the native CMake test")
class VisualizationNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="dolly-viewer-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.runner = Path(cls.temp.name) / "visualization_tests"
        root = Path(__file__).resolve().parents[1]
        subprocess.run([shutil.which("g++"), "-std=c++17", "-O2", "-ffp-contract=off",
                        "-Wall", "-Wextra", "-pedantic", "-I", str(root / "native/include"),
                        str(root / "native/src/dolly_path.cpp"),
                        str(root / "native/src/dolly_visualization.cpp"),
                        str(root / "native/tests/visualization_tests.cpp"), "-o", str(cls.runner)],
                       check=True, capture_output=True, text=True)

    def test_projection_clipping_and_parser(self):
        result = subprocess.run([str(self.runner)], check=True, capture_output=True, text=True)
        self.assertIn("Native visualization tests passed", result.stdout)

    def test_legacy_very_large_shortest_angles_keep_native_guides_valid(self):
        project = shot()
        project.keyframes[0].curve_yaw = 1e20
        project.keyframes[1].curve_yaw = -1e20
        project.keyframes[2].curve_yaw = 3.6e12
        packet = Path(self.temp.name) / "huge-angle.dlyvis"
        packet.write_bytes(build_visualization(project, session_id=17, revision=3))
        result = subprocess.run([str(self.runner), str(packet)], check=True, capture_output=True, text=True)
        self.assertEqual(result.stdout.splitlines()[0], "65 3 0")

    def test_authored_spline_samples_match_playback(self):
        project = shot()
        project.keyframes[1].time = .25
        project.keyframes[2].time = 4
        packet = Path(self.temp.name) / "shot.dlyvis"
        packet.write_bytes(build_visualization(project, selected_camera=2))
        result = subprocess.run([str(self.runner), str(packet)], check=True, capture_output=True, text=True)
        rows = result.stdout.splitlines()
        self.assertEqual(rows[0], "65 3 2")
        times = [0] + [.25 * i / 32 for i in range(1, 33)] + [
            .25 + 3.75 * i / 32 for i in range(1, 33)]
        self.assertEqual(len(rows) - 1, len(times))
        for row, time in zip(rows[1:], times):
            pose = project.evaluate(time)
            for actual, field in zip(map(float, row.split()),
                                     ("x", "y", "z", "pitch", "yaw", "roll", "aspect_ratio")):
                self.assertAlmostEqual(actual, pose[field], places=9)
