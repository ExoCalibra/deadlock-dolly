# Deadlock Dolly 0.6.42-alpha

Dolly can now always be closed after the game, including when Deadlock was closed from its own window first.

## Changes

- **Closing Dolly after the game is closed now works.** *Before:* if you closed Deadlock from its own window (for example right-clicking it on the taskbar), then closed Dolly, Dolly showed "Launch the local replay from Dolly first. Connections to separately launched games are disabled." and stayed open, so you had to force it shut. *After:* Dolly closes cleanly. The steps that can no longer be run without a game are skipped, and the important cleanup still happens.
- **Restoration and cleanup are unaffected.** Dolly still restores its temporary game changes and hands off removal of its temporary plugin files, exactly as before, whenever the game exits.

## Validation

The full Python suite passes: 2,008 tests, 22 skipped. The close path was exercised directly with a game process that has already exited and pending in-console restores: `close()` returns without raising and still restores the game configuration and hands off cleanup.

## Limits

When the game has already closed, changes that only exist inside the running game (HUD and camera settings) cannot be written back, since there is nothing to write to. They are only session-level and are not saved to disk, so this leaves nothing behind. The on-disk configuration and temporary files are still restored and removed.

## Updating

Extract the Windows ZIP into a fresh folder and run Dolly.exe, or let Dolly update itself. Keep the previous installation until your workflow is checked. Python and Tcl/Tk are bundled.