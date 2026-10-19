"""Movie WAV capture parsing and conversion."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import wave
from unittest.mock import Mock

from dolly.movie_audio import MOVIE_START, MovieWave


class MovieWaveTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.game = Path(self.folder.name) / "Deadlock/game/bin/win64/deadlock.exe"
        self.game.parent.mkdir(parents=True)
        self.movie = MovieWave(Path(self.folder.name) / "shot.mp4", self.game)
        self.controller = Mock()
        self.controller.game_pid.return_value = 4321
        self.marker = Path(tempfile.gettempdir()) / "dolly_movie_audio_4321.ready"

    def tearDown(self):
        self.marker.unlink(missing_ok=True)

    def test_start_parses_the_engine_folder(self):
        self.marker.write_text("", encoding="ascii")
        self.controller.replay_tick_rate.return_value = 64.0
        self.controller._request.side_effect = [
            "",
            "Audio device starved 3 samples \r\n"
            "Started recording movie: movie/2026_10_19_12_00_00/dolly_audio_x.*: "
            "framerate 60.000000",
            "Syntax: demo_goto <tick>\r\n  Currently playing 45 of 1000 ticks.",
        ]
        self.movie.start(self.controller, 60)
        self.assertTrue(self.movie.started)
        self.assertAlmostEqual(self.movie.movie_engine_seconds, 45 / 64.0)
        self.assertEqual(
            self.movie.folder,
            Path(self.folder.name) / "Deadlock/game/citadel/movie/2026_10_19_12_00_00")

    def test_start_refuses_without_the_native_marker(self):
        self.marker.unlink(missing_ok=True)
        with self.assertRaisesRegex(RuntimeError, "does not support fixed-step audio"):
            self.movie.start(self.controller, 60)

    def test_finish_converts_the_wav_to_48k(self):
        self.marker.write_text("", encoding="ascii")
        self.controller.replay_tick_rate.return_value = 64.0
        self.controller._request.side_effect = [
            "",
            "Started recording movie: movie/2026_10_19_12_00_00/dolly_audio_x.*: "
            "framerate 60.000000",
            "Syntax: demo_goto <tick>\r\n  Currently playing 0 of 1000 ticks.",
        ]
        self.movie.start(self.controller, 60)
        assert self.movie.folder is not None
        self.movie.folder.mkdir(parents=True, exist_ok=True)
        source = self.movie.folder / f"{self.movie.name}.wav"
        with wave.open(str(source), "wb") as audio:
            audio.setnchannels(2)
            audio.setsampwidth(2)
            audio.setframerate(44100)
            audio.writeframes(b"\0\0\0\0" * 44100)
        self.controller._request.side_effect = [
            "Finishing movie: movie/2026_10_19_12_00_00/dolly_audio_x.* "
            "[60 frames @ 60.000000 == 1.000000 seconds]"
        ]
        try:
            target = self.movie.finish(self.controller, 0.25, Path(self.folder.name),
                                       start_engine_seconds=0.25, speed=0.5)
        except RuntimeError as exc:
            self.skipTest(f"FFmpeg unavailable: {exc}")
        self.assertTrue(target.is_file())
        with wave.open(str(target), "rb") as audio:
            self.assertEqual(audio.getframerate(), 48000)
            self.assertEqual(audio.getnchannels(), 2)
            self.assertGreaterEqual(audio.getnframes(), 11000)
            self.assertLessEqual(audio.getnframes(), 13000)


if __name__ == "__main__":
    unittest.main()
