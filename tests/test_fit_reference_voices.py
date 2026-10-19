"""Engine-time fitting for the frame-locked movie WAV."""
from __future__ import annotations

import csv
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

try:
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly
    from tools.fit_reference_voices import fit
except ImportError:  # pragma: no cover - the audio test extra is optional
    np = sf = resample_poly = fit = None


@unittest.skipUnless(np is not None, "numpy/scipy/soundfile audio test extra is not installed")
class EngineTimeFitTests(unittest.TestCase):
    def test_slowed_source_is_placed_at_its_engine_time(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sources = root / "sources"
            (sources / "sounds").mkdir(parents=True)
            sample_rate = 48000
            time = np.arange(sample_rate) / sample_rate
            tone = 0.4 * np.sin(2 * np.pi * 440 * time)
            source = np.column_stack([tone, tone]).astype(np.float32)
            sf.write(sources / "sounds" / "test.wav", source, sample_rate, subtype="FLOAT")
            # The reference is the same source at half speed, placed at 1 s.
            slow = resample_poly(source, 2, 1, axis=0).astype(np.float32)
            reference = np.zeros((4 * sample_rate, 2), dtype=np.float32)
            at = sample_rate
            reference[at:at + len(slow)] = slow * 0.5
            reference_path = root / "reference.wav"
            sf.write(reference_path, reference, sample_rate, subtype="FLOAT")
            state = root / "state.csv"
            columns = ["perf_counter", "qpc_ticks", "voice_slot", "voice_id", "slot_20",
                       "raw_14", "state_b_0", "state_b_1", "raw_00", "raw_04", "raw_08"]
            with state.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=columns)
                writer.writeheader()
                writer.writerow({name: "0" for name in columns})
            row = {
                "start_seconds": "0", "stop_seconds": "2", "start_tick": "0",
                "stop_tick": "64", "start_engine_seconds": "10.0",
                "stop_engine_seconds": "11.0", "start_qpc": "0", "stop_qpc": "0",
                "voice_slot": "0", "voice_id": "1", "soundevent": "test",
                "source_volume": "1", "source_rate_parameter": "0", "source_x": "0",
                "source_y": "0", "source_z": "0", "source_vsnd": "sounds/test.vsnd",
                "source_wav": "sounds/test.wav", "stop_reason": "voice_released",
            }
            with (sources / "audio_usage.csv").open("w", newline="",
                                                     encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(row))
                writer.writeheader()
                writer.writerow(row)
            output = root / "fitted"
            report = fit(SimpleNamespace(
                source_dir=sources, reference_wav=reference_path, reference_json=None,
                state_csv=state, output=output, clip_offset=0.0, clip_duration=4.0,
                passes=2, engine_start=9.5, speed=0.5,
            ))
            self.assertGreater(report["correlation"], 0.99)
            with (output / "fitted_usage.csv").open(newline="", encoding="utf-8") as stream:
                fitted = list(csv.DictReader(stream))
            self.assertEqual(len(fitted), 1)
            self.assertAlmostEqual(float(fitted[0]["start_seconds"]), 1.0, places=2)
            self.assertAlmostEqual(float(fitted[0]["end_seconds"]), 3.0, places=2)
            self.assertAlmostEqual(float(fitted[0]["playback_rate"]), 0.5, places=3)
            self.assertAlmostEqual(float(fitted[0]["gain_left"]), 0.5, places=2)


if __name__ == "__main__":
    unittest.main()
