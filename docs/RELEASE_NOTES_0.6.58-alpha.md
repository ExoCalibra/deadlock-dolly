### Deadlock Dolly v0.6.58-alpha

**0.6.58-alpha**

- **Depth with temporal antialiasing.** *Before:* a valid subpixel camera offset could fail depth calibration and stop a take before its first frame. *After:* bounded temporal offsets are accepted and preserved in the paired camera data, while incompatible or conflicting projections still stop capture.

- **Clearer capture failures.** *Before:* different depth-readback and frame-pairing failures could appear as the same generic error. *After:* errors retain the underlying failure and distinguish missing or conflicting calibration, readback problems and mismatched frames.

- **Native hardening and replay setup.** *Before:* several native size calculations needed stronger overflow checks, and unusual Steam libraries or interrupted plugin cleanup could disrupt setup. *After:* the package includes checked arithmetic, safer diagnostics and the current discovery and cleanup fixes.

- **Current guides and credits.** *Before:* some guides described older controls, and the package lacked the consolidated contributor record. *After:* guides match the current editor, export and recovery workflows, with refreshed navigation, verified credits and an updated README demonstration.

## Depth capture

The repair accepts ordinary temporal projection offsets within one depth pixel
per axis. Color and depth still require the same validated render sample. The
captured projection is retained in `camera.json`; bundle validation and offline
reconstruction use those recorded offsets rather than treating them as zero.

This addresses a reproduced calibration rejection consistent with the reported
FSR2/TAA settings. The original diagnostic did not contain the failing GPU
buffers, so it does not establish that every reported readback failure has the
same cause. The affected user's fresh take remains the acceptance check.
Unsupported projections, conflicting samples, stale resources and failed
readback remain errors. No game-build compatibility checks are bypassed.

## Package and documentation

This Windows package brings the current native hardening, replay setup and
cleanup changes together with the updated guides. `Start_Here.txt`, the video,
layer and update guides, and the camera-control reference describe the current
workflow. Credits are included under `_internal/CREDITS.md` so older updaters
can install the complete package.

The README uses the Deadlock Editing Discord vanity invite and a version badge
that does not depend on GitHub's release-API token pool. Release descriptions
retain the bold version line so installed 0.6.51–0.6.54 clients can show the
update highlights.

## Validation boundary

Regression coverage includes accepted and rejected projection offsets,
unchanged depth values, camera reconstruction, readback diagnostics, frame
pairing and incomplete-output cleanup. The composed software-rendering and
encoder check exercises paired video, EXRs and camera metadata together.

These are offline checks. They do not establish live FSR2 behavior on the
affected user's GPU or replace inspection of the resulting take. See the
[current layer guide](LAYER_EXPORT.md) for capture and alpha limitations.
