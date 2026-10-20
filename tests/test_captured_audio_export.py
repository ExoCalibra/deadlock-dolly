"""Native voice-log pairing and source WAV deduplication."""
import csv
from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import wave

from tools.export_captured_audio import _convert_asset, export


class CapturedAudioExportTests(unittest.TestCase):
    def test_asset_conversion_children_are_hidden(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            viewer = root / "Source2Viewer-CLI.exe"
            ffmpeg = root / "ffmpeg.exe"
            destination = root / "jump.wav"
            calls = []

            def fake_run(command, **options):
                calls.append((command, options))
                if command[0] == str(viewer):
                    raw = Path(command[command.index("-o") + 1])
                    raw.write_bytes(b"fake audio")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch("tools.export_captured_audio.subprocess.run", side_effect=fake_run):
                _convert_asset("sounds/jump.vsnd", destination, vpk=root / "assets.vpk",
                               viewer=viewer, ffmpeg=ffmpeg, temporary=root)
            self.assertEqual([command[0] for command, _ in calls],
                             [str(viewer), str(ffmpeg)])
            expected = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self.assertTrue(all(options.get("creationflags") == expected
                                for _, options in calls))

    def test_two_uses_one_source_wav_and_distinct_stops(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            log = root / "voices.csv"
            log.write_text(
                "# qpc_frequency=1000; capture_start_qpc=1000; capture_start_tick=100; "
                "capture_start_engine_seconds=1.0\n"
                "kind,qpc_ticks,demo_tick,engine_seconds,voice_slot,voice_id,soundevent,vsnd_path\n"
                'start,1100,106,1.1,3,40,"Player.Jump","sounds/jump.vsnd"\n'
                'start,1150,109,1.15,4,41,"Player.Jump","sounds/jump.vsnd"\n'
                'stop,1250,115,1.25,3,40,"",""\n'
                'stop,1400,124,1.4,4,41,"",""\n'
                "# dropped=0; capture_end_qpc=2000\n", encoding="utf-8")
            calls = []

            def fake_convert(asset, destination, **_options):
                calls.append(asset)
                with wave.open(str(destination), "wb") as out:
                    out.setnchannels(1)
                    out.setsampwidth(2)
                    out.setframerate(48000)
                    out.writeframes(b"\0\0" * 480)

            with patch("tools.export_captured_audio._convert_asset", fake_convert):
                result = export(log, root / "output", vpk=root / "assets.vpk",
                                viewer=root / "viewer", ffmpeg=root / "ffmpeg")
            self.assertEqual(calls, ["sounds/jump.vsnd"])
            self.assertEqual((result["voice_starts"], result["voice_stops_matched"],
                              result["exported_unique_wavs"]), (2, 2, 1))
            with (root / "output" / "audio_usage.csv").open(newline="", encoding="utf-8") as source:
                rows = list(csv.DictReader(source))
            self.assertEqual([row["stop_seconds"] for row in rows],
                             ["0.250000000", "0.400000000"])
            self.assertEqual(rows[0]["source_wav"], rows[1]["source_wav"])


if __name__ == "__main__":
    unittest.main()
