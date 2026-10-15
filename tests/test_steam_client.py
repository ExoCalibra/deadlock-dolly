"""Steam readiness failures must be found before editing game configuration."""
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from dolly.steam_client import SteamClientError, prepare_steam_client


class SteamClientTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.game = Path(folder.name)
        sdk = self.game / 'bin/win64/steam_api64.dll'
        sdk.parent.mkdir(parents=True)
        sdk.write_bytes(b'test library; never loaded')
        self.api = Mock()
        self.api.SteamAPI_IsSteamRunning.return_value = True
        self.api.SteamAPI_InitFlat.return_value = 0
        self.api.SteamAPI_SteamHTMLSurface_v005.return_value = 123
        self.api.SteamAPI_ISteamHTMLSurface_Init.return_value = True

    def check(self):
        with patch('dolly.steam_client.sys.platform', 'win32'), \
                patch('dolly.steam_client.ctypes.CDLL', return_value=self.api):
            return prepare_steam_client(self.game)

    def test_ready_client_initializes_html_and_restores_the_parent_environment(self):
        with patch.dict(os.environ, {'SteamAppId': 'other-app', 'SteamGameId': 'other-game'}):
            def initialize(_error):
                self.assertEqual(os.environ['SteamAppId'], '1422450')
                self.assertEqual(os.environ['SteamGameId'], '1422450')
                return 0
            self.api.SteamAPI_InitFlat.side_effect = initialize
            self.assertTrue(self.check()['html_ready'])
            self.assertEqual(os.environ['SteamAppId'], 'other-app')
            self.assertEqual(os.environ['SteamGameId'], 'other-game')
        self.api.SteamAPI_ISteamHTMLSurface_Shutdown.assert_called_once_with(123)
        self.api.SteamAPI_Shutdown.assert_called_once_with()

    def test_an_open_but_unresponsive_client_gives_recovery_guidance(self):
        self.api.SteamAPI_IsSteamRunning.return_value = False
        with self.assertRaisesRegex(SteamClientError, 'Exit.*Steam'):
            self.check()
        self.api.SteamAPI_InitFlat.assert_not_called()

    def test_failed_html_initialization_does_not_claim_the_client_is_ready(self):
        self.api.SteamAPI_ISteamHTMLSurface_Init.return_value = False
        with self.assertRaisesRegex(SteamClientError, 'HTML'):
            self.check()
        self.api.SteamAPI_Shutdown.assert_called_once_with()
        self.api.SteamAPI_ISteamHTMLSurface_Shutdown.assert_not_called()


if __name__ == '__main__':
    unittest.main()
