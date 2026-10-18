### Deadlock Dolly v0.6.60-alpha

**0.6.60-alpha**

- **Cameras for After Effects and Blender.** *Before:* Matching 3D overlays to Dolly footage needed a separate camera workflow. *After:* Optional JSX and USD exports bring the recorded camera into your editor.

- **Recording-matched camera data.** *Before:* Camera exports were unavailable. *After:* Dolly checks every frame and the recording identity, protects existing files and keeps your video if camera export fails.

- **Depth cameras preserved.** *Before:* Calibrated cameras served the depth workflow. *After:* Paired depth takes can also feed both camera exporters while preserving depth reconstruction and the recent seek and Players fixes.

## Camera exports for After Effects and USD

Enable **Export After Effects camera (.jsx)**, **Export USD camera (.usda)** or
both before recording. Dolly saves an animated camera beside the video when the
recording finishes. This supports camera paths, single bone cameras and Player
POV, without requiring a depth recording. @SamuelCurrid contributed the original
exporters, recorded camera sampling and UI in [PR #25](https://github.com/cravvnn/deadlock-dolly/pull/25).
See [Export the camera](VIDEO_AND_RESHADE.md#export-the-camera) for import steps.

After Effects footage errors no longer discard the camera import. The script
keeps the camera and explains how to add a compatible video copy if needed.

Camera export is off by default. When requested, each encoded video frame must
have camera data belonging to that recording. Missing, partial or mismatched
camera data is reported in the log; Dolly keeps the saved video. Existing camera
files are never overwritten. Camera metadata collection is bounded and conversion
runs on the operation worker.

Paired depth takes use the validated renderer camera bundle after checking it
against the recorded track. External cameras use the stable projection; temporal
jitter remains in the depth bundle for depth reconstruction. Both apps use one
camera sample per encoded frame, conforming footage to the chosen FPS rather than
claiming original wall-clock playback for variable-timestamp recordings.

The export contains the camera and shot key markers. It does not extract map or
player meshes, animation or materials. Depth-of-field values come from authored
settings; Native DOF is an approximation and matching blur may need adjustment.

## Existing fixes

The replay packet-boundary seeking, Stop-state reset and Players viewport framing
fixes from 0.6.59 remain in this version.
