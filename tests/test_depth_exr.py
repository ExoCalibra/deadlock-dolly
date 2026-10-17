"""Reader tests for the depth EXR frames.

The fixture was written by the native writer itself (the ``depth_tests``
executable with a fixture path): a 3x2 frame carrying
``{7, 14, 70000.125, 1e20, +inf, 28}``, so the Python reader is checked
against the authoritative producer, not against a second Python writer.
"""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np

from dolly.depth_exr import DepthExrError, read_distances

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "depth-frame.exr"


class DepthExrTests(unittest.TestCase):
    def test_reads_the_native_fixture_exactly(self):
        values = read_distances(FIXTURE)
        self.assertEqual(values.shape, (2, 3))
        self.assertEqual(values.dtype, np.float32)
        expected = np.array([[7.0, 14.0, 70000.125], [1e20, np.inf, 28.0]], dtype=np.float32)
        self.assertTrue(np.array_equal(values, expected))

    def test_rejects_unsupported_or_damaged_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            cases = {
                "missing": None,
                "empty": b"",
                "truncated": FIXTURE.read_bytes()[:64],
                "bad magic": struct.pack("<i", 12345) + FIXTURE.read_bytes()[4:],
                "bad version": FIXTURE.read_bytes()[:4] + struct.pack("<i", 7) + FIXTURE.read_bytes()[8:],
            }
            for name, payload in cases.items():
                with self.subTest(name=name):
                    path = folder / "case.exr"
                    if payload is None:
                        if path.exists():
                            path.unlink()
                    else:
                        path.write_bytes(payload)
                    with self.assertRaises(DepthExrError):
                        read_distances(path)


if __name__ == "__main__":
    unittest.main()
