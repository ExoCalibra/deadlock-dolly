"""Minidump crash diagnosis for diagnostics exports (no debugger needed)."""
import struct
import tempfile
from pathlib import Path
import unittest

from dolly import crash_dumps


def build_dump(modules, address, *, access=(0, 0x60), code=0xC0000005, thread=7):
    header_size = 16
    directory_size = 24
    directory_rva = header_size
    exception_size = 8 + 4 + 4 + 8 + 8 + 4 + 4 + 15 * 8
    module_list_size = 4 + len(modules) * 108
    exception_rva = directory_rva + directory_size
    module_rva = exception_rva + exception_size
    names_rva = module_rva + module_list_size
    name_blob = bytearray()
    entries = []
    cursor = names_rva
    for base, image, name in modules:
        encoded = name.encode("utf-16-le")
        entries.append((base, image, cursor))
        block = struct.pack("<I", len(encoded)) + encoded
        name_blob += block
        cursor += len(block)
    header = b"MDMP" + struct.pack("<III", 0xA793, 2, directory_rva)
    directory = (struct.pack("<III", 6, exception_size, exception_rva)
                 + struct.pack("<III", 4, module_list_size, module_rva))
    info = struct.pack("<15Q", access[0], access[1], *([0] * 13))
    exception = (struct.pack("<II", thread, 0)
                 + struct.pack("<IIQQII", code, 0, 0, address, 2, 0) + info)
    module_list = bytearray(struct.pack("<I", len(modules)))
    for base, image, name_rva in entries:
        module_list += struct.pack("<QIIII", base, image, 0, 0, name_rva)
        module_list += b"\0" * (108 - 24)
    return (header + directory + exception + bytes(module_list) + bytes(name_blob))


class CrashDumpTests(unittest.TestCase):
    def test_faulting_module_offset_and_null_read_are_reported(self):
        data = build_dump([(0x10000000, 0x1000, r"C:\game\client.dll"),
                           (0x20000000, 0x2000, r"C:\game\engine2.dll")],
                          0x10000123)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "crash.mdmp"
            path.write_bytes(data)
            report = crash_dumps.analyse(path)
        self.assertEqual(report["faulting_module"], "client.dll")
        self.assertEqual(report["module_offset"], "0x123")
        self.assertEqual(report["exception_code"], "0xC0000005")
        self.assertEqual(report["access"], "read")
        self.assertEqual(report["access_address"], "0x60")
        self.assertEqual(report["thread"], 7)

    def test_write_fault_and_unknown_module_are_reported(self):
        data = build_dump([(0x10000000, 0x1000, "client.dll")], 0x90000000,
                          access=(1, 0xDEAD))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "crash.mdmp"
            path.write_bytes(data)
            report = crash_dumps.analyse(path)
        self.assertIsNone(report["faulting_module"])
        self.assertEqual(report["access"], "write")
        self.assertEqual(report["access_address"], "0xDEAD")

    def test_malformed_or_truncated_dumps_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.mdmp"
            for data in (b"NOPE", b"MDMP" + b"\0" * 8, b"MDMP" + b"\xff" * 28):
                with self.subTest(data=data[:8]):
                    path.write_bytes(data)
                    with self.assertRaises(ValueError):
                        crash_dumps.analyse(path)


if __name__ == "__main__":
    unittest.main()
