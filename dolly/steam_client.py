"""Prepare Steam's client/HTML connection before mounting an editing session."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import sys
import threading

from .launch_errors import LaunchError
from .runtime import external_program_environment

_LOCK = threading.Lock()


class SteamClientError(LaunchError):
    """Steam exists but cannot service the game's startup connection."""


def prepare_steam_client(game_dir: Path) -> dict:
    sdk = Path(game_dir) / 'bin/win64/steam_api64.dll'
    if sys.platform != 'win32' or not sdk.is_file():
        return {'available': False}
    with _LOCK, external_program_environment():
        previous = {name: os.environ.get(name) for name in ('SteamAppId', 'SteamGameId')}
        api = None
        initialized = html_ready = False
        surface = None
        try:
            os.environ.update(SteamAppId='1422450', SteamGameId='1422450')
            api = ctypes.CDLL(str(sdk))
            api.SteamAPI_IsSteamRunning.restype = ctypes.c_bool
            api.SteamAPI_InitFlat.argtypes = [ctypes.c_void_p]
            api.SteamAPI_InitFlat.restype = ctypes.c_int
            api.SteamAPI_SteamHTMLSurface_v005.restype = ctypes.c_void_p
            api.SteamAPI_ISteamHTMLSurface_Init.argtypes = [ctypes.c_void_p]
            api.SteamAPI_ISteamHTMLSurface_Init.restype = ctypes.c_bool
            api.SteamAPI_ISteamHTMLSurface_Shutdown.argtypes = [ctypes.c_void_p]
            api.SteamAPI_ISteamHTMLSurface_Shutdown.restype = ctypes.c_bool
            api.SteamAPI_Shutdown.restype = None
            if not api.SteamAPI_IsSteamRunning():
                raise SteamClientError('Steam is open but its client connection is unavailable. '
                                       'Use Exit in Steam, reopen Steam and sign in, then launch Dolly again.')
            error = ctypes.create_string_buffer(1024)
            result = api.SteamAPI_InitFlat(error)
            if result != 0:
                detail = error.value.decode('utf-8', errors='replace')
                raise SteamClientError('Steam could not initialize the Deadlock connection. '
                                       'Use Exit in Steam, reopen Steam and sign in, then retry. ' + detail)
            initialized = True
            surface = api.SteamAPI_SteamHTMLSurface_v005()
            html_ready = bool(surface) and bool(api.SteamAPI_ISteamHTMLSurface_Init(surface))
            if not html_ready:
                raise SteamClientError('Steam\'s HTML interface is unavailable; Deadlock cannot finish startup. '
                                       'Use Exit in Steam, reopen Steam and sign in, then retry Dolly.')
            return {'available': True, 'running': True, 'html_ready': True}
        except (OSError, AttributeError) as exc:
            raise SteamClientError('Could not check Deadlock\'s Steam client. Verify the game files in Steam, '
                                   'then retry Dolly. ' + str(exc)) from exc
        finally:
            try:
                if html_ready:
                    api.SteamAPI_ISteamHTMLSurface_Shutdown(surface)
            finally:
                try:
                    if initialized:
                        api.SteamAPI_Shutdown()
                finally:
                    for name, value in previous.items():
                        if value is None:
                            os.environ.pop(name, None)
                        else:
                            os.environ[name] = value
