"""Execution-environment helpers; the Wine guard must stay inert on Windows."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from dolly import runtime


class WineDetectionTests(unittest.TestCase):
    def test_wine_version_is_empty_off_windows(self):
        with patch.object(runtime.os, "name", "posix"):
            self.assertEqual(runtime.wine_version(), "")

    def test_wine_version_is_empty_when_wine_is_not_installed(self):
        # Real Windows ntdll has no wine_get_version export, so asking for it
        # raises; the helper answers "" instead of failing, which is what keeps
        # every Wine-only branch out of a Windows session.
        ntdll = Mock(spec=[])  # spec with no attributes: any lookup raises
        with patch.object(runtime.os, "name", "nt"), \
                patch.object(runtime.ctypes, "WinDLL", return_value=ntdll, create=True):
            self.assertEqual(runtime.wine_version(), "")

    def test_wine_version_reports_the_running_wine(self):
        ntdll = SimpleNamespace(wine_get_version=Mock(return_value=b"wine-11.0"))
        with patch.object(runtime.os, "name", "nt"), \
                patch.object(runtime.ctypes, "WinDLL", return_value=ntdll, create=True):
            self.assertEqual(runtime.wine_version(), "wine-11.0")


if __name__ == "__main__":
    unittest.main()
