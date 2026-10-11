# Deadlock Dolly 0.6.40-alpha

Faster, steadier startup. Dolly now plays through Deadlock's recorded replay intro at high speed and restores normal speed before you edit, and it does less repeated work while opening a session.

## Changes

- **The replay intro before you edit is much shorter.** *Before:* after loading a replay, Dolly waited for the recording's own match-intro camera to finish at normal speed, which took about ten seconds every time you prepared a shot. *After:* that intro plays at speed through the ordinary replay path and the game returns to normal speed before the editor opens, so startup and each shot preparation reach the editor in roughly a third of the previous time. The recorded footage and the replay's frames are unchanged; nothing is seeked or skipped.
- **Less repeated work when opening and preparing a session.** *Before:* the large game module was re-read and re-verified for every check. *After:* the verification is cached and the replay-camera check is reused for the session, so opening the editor is lighter without weakening any build check.
- **Clearer startup timeouts.** *Before:* a startup step that timed out said only that it timed out. *After:* the message names how long it waited and points at diagnostics.
- **Lighter idle while paused.** *Before:* the paused-replay memory watchdog sampled the game process several times a second. *After:* it samples every few seconds, which is all its sixty-second window needs.

## Validation

The full Python suite passes: 1,993 tests, 22 skipped. One bounded local session recorded the startup timings on a real owned development session and completed with exact configuration restoration, no leftover deployment and exit code 0. The pre-show wait fell from about 9.6 seconds to about 2.7 seconds at startup and on shot preparation, with the replay speed restored to normal before the editor opened.

## Limits

This shortens the wait for the game's own replay intro; it does not remove it, because the intro is part of the recorded replay and skipping it has crashed Deadlock. The hideout map load and shader preload before the replay remains fully in the game's control. No replay footage, camera framing, capture or export behavior changed.

## Updating

Extract the Windows ZIP into a fresh folder and run Dolly.exe. Keep the previous installation until your workflow is checked. Python and Tcl/Tk are bundled.