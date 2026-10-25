### Deadlock Dolly v0.6.65-alpha

**0.6.65-alpha**

- **Launch again after Deadlock writes a crash report.** *Before:* the game's own assertion reports were left inside Dolly's temporary plugin folder, and the next launch stopped with "Temporary plugin directory contains an extra file or folder" until that folder was deleted by hand. *After:* game-written report files are removed with the session, and anything else Dolly does not recognize is kept untouched without ever blocking the next launch.

- **Prepare a shot on a slower replay load.** *Before:* reloading the replay for a shot gave up after 45 seconds, so a large replay or a slower machine failed with "Timed out waiting for the fresh replay's initial update" while the replay was still loading. *After:* Dolly keeps waiting for up to two minutes, tells you the replay is still loading, and still stops on a real stall or when you cancel.

- **Quieter graphics profile checks.** *Before:* most sessions warned that some graphics values could not be checked, because Deadlock hides two render CVARs from the console. *After:* those hidden CVARs are recorded separately without a warning; a real mismatch still warns.

## Published package

This file is the exact body of the published 0.6.65 release. Its Windows asset
is `Deadlock_Dolly_0.6.65-alpha_Windows_x64.zip`, 225 579 083 bytes,
SHA-256 `40f856decff824a03f1fe3727a2af73c4864618512ba8fe567920ab66337b04b`.

The temporary-file cleanup in that package also preserves any unrecognised file
without blocking the next launch, and its diagnostics export lists the temporary
mount's entry names. Neither was announced as a separate highlight.
