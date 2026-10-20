### Deadlock Dolly v0.6.62-alpha

**0.6.62-alpha**

Support update for 0.6.61; all 0.6.61 features are included.

- **Players layer preflight.** *Before:* 120 FPS at 0.1x could create an empty Players folder after the capture missed shot frames. *After:* Dolly rejects engine clocks above 600 Hz before recording, removes an empty Players folder if a capture still fails, and points to a lower Video FPS or an Export speed closer to 1x.

- **Clear Windows Application Control errors.** *Before:* A blocked DollyNative.dll appeared as a generic native-helper load failure. *After:* Dolly identifies WinError 4551, names Windows Smart App Control or an Application Control policy, and explains the unblock/allow steps.

- **Silent reconstructed-audio setup.** *Before:* Reconstructed audio launched Source2Viewer and FFmpeg once per sound asset, and each child opened a console window; a busy export looked like it was spawning cmd.exe continuously. *After:* Those child processes run hidden, so extraction no longer covers the desktop with console windows.

## Support follow-up

This release is the support follow-up to 0.6.61. The native camera, Follow,
fixed-step game and reconstructed audio, 6796 profile and cvar unlocker are
unchanged. Players captures that request an engine clock above 600 Hz are now
refused before the Color take starts instead of leaving an empty layer folder.
The new Application Control message is shown when Windows blocks the native
helper. Reconstructed-audio extraction remains fully local and still verifies
the pinned Source2Viewer helper.
