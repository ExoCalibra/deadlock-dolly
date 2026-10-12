# Deadlock Dolly 0.6.43-alpha

When a replay fatal-crashes Deadlock while it loads, Dolly now reports the real reason instead of implying a build mismatch that may not exist.

## Changes

- **Clear guidance when a replay crashes Deadlock.** *Before:* if a recording fataled Deadlock while it loaded, Dolly always said "A replay that this game build cannot reconstruct… Try the latest replay recorded on this build", even when the replay was recorded on your exact build, so the advice did not fit. *After:* Dolly reads your installed build from the game's own console output and compares it with the replay's recorded build. When they match it tells you the recording itself is the problem (for example an incomplete or private/experimental recording) and to try another replay or re-record it; when they differ the original build-mismatch guidance is kept.
- **The installed build is recorded in diagnostics.** Startup evidence and the exported report now include the installed build number, so a support ZIP shows both the game's build and the replay's recorded build.
- **The crash message still names the selected replay.** File, recorded build and map remain in the message.

## Validation

The full Python suite passes: 2,014 tests, 22 skipped. The build-banner parser and both message paths are covered by `tests/test_console.py` and `tests/test_auto_startup.py`.

## Limits

Dolly cannot make an incompatible recording play; it only explains why Deadlock fataled. A replay recorded in a custom, modified or experimental lobby can still fatal the game regardless of the message.

## Updating

Extract the Windows ZIP into a fresh folder and run Dolly.exe, or let Dolly update itself. Keep the previous installation until your workflow is checked. Python and Tcl/Tk are bundled.
