# Deadlock Dolly 0.6.50-alpha

This update fixes the recording controls and the misleading camera-clearing error.

## Changes

- **Visible recording controls.** *Before:* a paused replay could leave the recorder open while Finish recording was only available on Export. *After:* Finish recording stays visible on every editor tab, with a saving status during finalization.
- **Safe camera clearing.** *Before:* Clear All could appear available while recording and raise a misleading playback error. *After:* camera edits stay locked until the take finishes, and queued Clear requests keep the cameras intact without an error popup.

Pausing the replay or reaching the last camera does not finish a normal video take. Use **Finish recording**, wait for saving to complete, then edit or clear cameras. **Stop / restore** continues to control playback and restoration.

## Updating

Extract the complete Windows x64 ZIP into a fresh folder and run **Dolly.exe**, or use the updater after this release is published. Keep **_internal** beside **Dolly.exe**.
