# Deadlock Dolly 0.6.39-alpha

Two export-reliability fixes: a large export no longer reports "still finishing" while the encoder is still finalizing, and Export diagnostics no longer fails when the prefilled archive name already exists.

## Changes

- **Large exports wait as long as the encoder does.** *Before:* the desktop wait for finalization gave up after 30 seconds, so a big or drop-heavy take could report "The video recorder is still finishing" while the MP4 was still being written. *After:* the wait matches the native encoder's own 120-second finalization budget, so completed takes are reported as completed.
- **Export diagnostics no longer fails on an existing archive.** *Before:* the Export dialog prefills `dolly-diagnostics.zip` in Downloads, and reusing that name while the previous archive was still open raised a raw `[Errno 13] Permission denied`. *After:* Dolly picks a free numbered filename instead, and never overwrites an archive you still have open.

## Validation

The full Python suite passes: 1,987 tests, 22 skipped. One bounded live session recorded a real-time 2560x1440 60 fps take through the native recorder and completed with exact configuration restoration, no leftover deployment and exit code 0; it confirmed the finalization wait and the export path on a clean session. No game build compatibility profiles, capture geometry or encoder selection changed.

## Limits

These changes only affect how long Dolly waits for an already-running finalization and how the diagnostics archive is named. A take that the encoder itself fails to finalize still reports an error. The reported case of camera "jumping" during a heavy export was not reproducible on a clean session with this build; that symptom needs the affected user's saved shot and its sidecar to diagnose.

## Updating

Extract the Windows ZIP into a fresh folder and run Dolly.exe. Keep the previous installation until your workflow is checked. Python and Tcl/Tk are bundled.