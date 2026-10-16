"""Prepared graph channels retain playback arithmetic and validation semantics."""
import copy
from dataclasses import FrozenInstanceError, replace
import math
import unittest
from unittest.mock import patch

from dolly.curve import sample_channel
from dolly.path import AttachKey, CvarTrack, Keyframe, Project, TrackKey
from dolly import path as path_model


def shot():
    return Project(keyframes=[
        Keyframe(0, -4, 30, 2, 8, 359, -359, aspect_ratio=1.78, lens_scale=.85),
        Keyframe(.17, 90, -7, 20, -12, 1, -1, aspect_ratio=.9, lens_scale=None,
                 curve_pitch=23.123456789012345, curve_yaw=721, curve_roll=-721),
        Keyframe(2.7, -20, 18, -15, 4, -170, 170, aspect_ratio=3.4, lens_scale=1.25),
        Keyframe(9, 8, 2, 6, 11, 540, -540, aspect_ratio=2.39, lens_scale=.92)],
        setup_values={"r_dof_override_ranges": (2, 3, 5, 8)},
        tracks=[CvarTrack("r_dof_focus_distance", [TrackKey(0, 1), TrackKey(12, 200)])])


class CameraChannelSamplesTests(unittest.TestCase):
    def test_prepared_channels_match_playback_exactly_across_all_curve_policies(self):
        project = shot()
        timestamps = [-1, 0, .03125, .17, .55555555555555, 2.7, 6.25, 9, 12]
        for key in project.keyframes[1:]:
            timestamps.extend((math.nextafter(key.time, -math.inf), math.nextafter(key.time, math.inf)))
        for interpolation in ("linear", "smooth", "spline"):
            for lens in ("linear", "smooth", "step"):
                for rotation in ("shortest", "unwrapped"):
                    project.interpolation, project.lens_interpolation = interpolation, lens
                    project.rotation_mode = rotation
                    for channel in ("x", "y", "z", "pitch", "yaw", "roll", "fov", "aspect_ratio", "lens_scale"):
                        prepared = project.camera_channel_samples(channel)
                        for timestamp in timestamps:
                            with self.subTest(interpolation=interpolation, lens=lens, rotation=rotation,
                                              channel=channel, time=timestamp):
                                self.assertEqual(prepared.evaluate(timestamp), project.evaluate(timestamp)[channel])

    def test_graph_batch_validates_whole_project_once_and_skips_unrelated_evaluation(self):
        project = shot()
        original = copy.deepcopy(project)
        with patch.object(project, "validate", wraps=project.validate) as validate, \
                patch.object(project, "evaluate", side_effect=AssertionError("Full evaluation in graph batch")):
            values = sample_channel(project, "yaw", .03, 8.8, 256)
            self.assertEqual(validate.call_count, 1)
            self.assertEqual(len(values), 258)  # Regular samples plus the two interior authored keys.
        self.assertEqual(project, original)
        for timestamp, value in values:
            self.assertEqual(value, original.evaluate(timestamp)["yaw"])

    def test_preparation_does_not_accept_invalid_unrelated_project_data(self):
        project = shot()
        project.tracks[0].keys[0].value = math.nan
        with self.assertRaises(ValueError):
            sample_channel(project, "x", 0, 9, 256)
        project = shot()
        project.keyframes[0].aspect_ratio = 0
        with self.assertRaises(ValueError):
            project.camera_channel_samples("x")

    def test_spline_batch_prepares_derivatives_once_instead_of_once_per_timestamp(self):
        project = shot()
        project.interpolation = "spline"
        with patch("dolly.path._spline_tangents", wraps=path_model._spline_tangents) as derivatives:
            values = sample_channel(project, "x", 0, 9, 256)
        self.assertGreater(len(values), 256)
        self.assertEqual(derivatives.call_count, 1)

    def test_prepared_snapshot_is_immutable_and_detached_from_later_edits(self):
        project = shot()
        prepared = project.camera_channel_samples("yaw")
        original = [prepared.evaluate(t) for t in (0, .1, 1, 9)]
        project.keyframes[0].yaw = -720
        project.keyframes[1].curve_yaw = 95
        project.interpolation = "linear"
        project.rotation_mode = "unwrapped"
        self.assertEqual([prepared.evaluate(t) for t in (0, .1, 1, 9)], original)
        self.assertNotEqual(project.camera_channel_samples("yaw").evaluate(.1), original[1])
        with self.assertRaises(FrozenInstanceError):
            prepared.interpolation = "linear"
        self.assertIsInstance(prepared.times, tuple)
        self.assertIsInstance(prepared.values, tuple)
        self.assertIsInstance(prepared.tangents, tuple)

    def test_step_graph_retains_both_sides_of_every_authored_boundary(self):
        project = shot()
        project.lens_interpolation = "step"
        values = dict(sample_channel(project, "aspect_ratio", 0, 9, 11))
        for previous, key in zip(project.keyframes, project.keyframes[1:]):
            self.assertEqual(values[math.nextafter(key.time, -math.inf)], previous.aspect_ratio)
            self.assertEqual(values[key.time], key.aspect_ratio)

    def test_single_key_and_attached_key_camera_channels_still_match_playback(self):
        project = shot()
        project.keyframes = [replace(project.keyframes[1], time=0, source="attach",
                                     attach=AttachKey(handle=3, point="eyes"))]
        for channel in ("x", "pitch", "yaw", "roll", "aspect_ratio"):
            prepared = project.camera_channel_samples(channel)
            for timestamp in (-1, 0, 15):
                self.assertEqual(prepared.evaluate(timestamp), project.evaluate(timestamp)[channel])

    def test_close_key_finite_linear_fallback_is_identical_to_playback(self):
        project = Project(keyframes=[Keyframe(0, 1e308, 2, 3, 0, 0, 0),
            Keyframe(1e-300, -1e308, 2, 3, 0, 0, 0), Keyframe(1, 3, 2, 3, 0, 0, 0)])
        for interpolation in ("smooth", "spline"):
            project.interpolation = interpolation
            prepared = project.camera_channel_samples("x")
            for timestamp in (0, 5e-301, 1e-300, .5, 1):
                self.assertEqual(prepared.evaluate(timestamp), project.evaluate(timestamp)["x"])

    def test_invalid_time_and_unavailable_channel_are_not_silently_plotted(self):
        project = shot()
        for timestamp in (True, math.nan, math.inf, "1"):
            with self.subTest(timestamp=timestamp), self.assertRaises(ValueError):
                project.camera_channel_samples("x").evaluate(timestamp)
        project.keyframes = [replace(key, lens_scale=None) for key in project.keyframes]
        for channel in ("lens_scale", "missing"):
            with self.subTest(channel=channel), self.assertRaises(KeyError):
                project.camera_channel_samples(channel)


if __name__ == "__main__":
    unittest.main()
