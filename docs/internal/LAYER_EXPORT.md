# Layer export: renderer and research notes

For current controls, output files and limitations, use the
[Layer export guide](../LAYER_EXPORT.md). This page is technical background,
followed by explicitly historical frame-capture observations. Older prototype
names and open questions below are not current UI instructions.

## Current backend

The capture path observes reviewed DirectX 11 scene draws and retains the
scene depth target with its per-view constants. The depth-stencil target bound
at final Present is not assumed to contain scene depth: late interface passes
can clear or replace it.

The selector checks the reviewed texture name, the target's own viewport and
reversed depth-writing state. It tracks immediate and deferred draws and
associates recorded metadata with command lists. Incompatible writes, clears,
multiple unresolved targets and missing or conflicting camera calibration
reject the sample. Size or shader-slot identity alone is insufficient proof
that a constant buffer describes the captured scene.

The projection reader checks the viewport, inverse-Z block, view basis,
position and structural matrix entries. X/Y temporal projection offsets are
accepted within one depth pixel per axis, normalized by homogeneous clip-W
scale with a float-rounding margin. The sampled offsets remain in the camera
bundle. Cross-axis terms and oblique Z/W dependence remain rejected. A
successful Color recording does not establish compatibility for every
TAA/upscaling configuration.

Relevant implementation:

- `native/src/dolly_depth_scene_win.cpp` and `dolly_depth_hooks_win.cpp`:
  scene observation, command-list tracking and sample selection.
- `native/src/dolly_depth.cpp`: calibration, D24/D32 conversion, normalized
  previews and single-channel float-Z OpenEXR writing.
- `native/src/dolly_depth_readback_win.cpp`: three bounded staging slots for
  depth and calibration copies, mapped row handling and sample identity.
- `native/src/dolly_video_win.cpp`: paired Color/depth admission, readback,
  frame ordering and FFmpeg encoding.
- `native/src/dolly_depth_sequence_win.cpp`: owned output directory,
  manifests, EXRs and final camera bundle.

## Pairing and files

Color and depth copies are submitted at the same capture boundary. A CPU frame
is published only after the matching readbacks are ready; their sample IDs
must agree. Missing calibration, conflicting per-view bindings or a mismatch
stops the take. The current paired depth export requires the FFmpeg backend;
the built-in Windows Media Foundation encoder is not a paired-depth route.

The depth sequence lives in the Color file's parent under `depth/`, inside
the take folder created by the desktop exporter. It writes a 10-bit ProRes
`depth.mov`, `manifest.json`, optional `exr/00000000.exr` frames and, on
successful finalization, `camera.json`. The reduced grayscale preview is
encoded afterward by the desktop; a preview-encoding failure does not invalidate
the completed depth master.

Depth retains the scene target's own dimensions. Manifest version 3 records
those separately from the Color dimensions. EXR names use encoded Color-frame
indices, and the metadata retains source sample, replay time and capture PTS.
Capture time is not necessarily the encoded video's timing.

The readback queue permits up to 128 MiB across its three four-byte depth
staging images. This is a separate limit from the Color recorder's
8192-per-axis bound. Full-resolution 5K and 8K scene depth exceed that queue
budget. Current depth capture also temporarily sets render scale to 100%;
that setting does not alter the chosen antialiasing/upscaling mode.

Existing output directories are refused. Failed/cancelled native paired output
is removed; a resize/resource reset can finalize a completed matching prefix,
excluding pending GPU copies. Fixed-step depth fails on backpressure timeout.
Separate Players scratch folders and failed matte intermediates have their
own preservation rules; see the user guide before deleting capture data.

## Camera bundle and offline reconstruction

[Camera bundle](../CAMERA_BUNDLE.md) documents `camera.json`, its matrix
conventions and frame identities. The same reader that calibrates depth retains
the view, projection, position and camera axes. Two buffers with the same
inverse-Z coefficients but different view/projection matrices are conflicting
calibrations, not candidates to resolve by binding order.

A finalized bundle may be marked partial if complete view records are
unavailable or metadata was truncated. Failed or cancelled native sequences
do not keep a final bundle. `dolly/camera_bundle.py` reads, validates and
reprojects records; `dolly/export_audit.py` cross-checks available bundle and
manifest data without requiring camera bundles from older takes.

`dolly/depth_exr.py` reads Dolly's single-channel float-Z EXRs directly.
The numerical distances, including positive infinity for the far plane, must
not be replaced with decoded 10-bit MOV luma for reconstruction.

`dolly/depth_normals.py` is an offline reconstruction foundation. It computes
view/world normals from depth and matching calibration, masks invalid samples
and limits gradients/smoothing across depth discontinuities. Synthetic
geometry checks do not establish matching game shading normals. There is no
Normals capture option in the current Export UI.

## Players, World and Effects

Players uses native scene-object ownership: scene object to scene node to
owner entity. Supported player-owned draws and equipment are retained while
the world remains available for occlusion. A generic `SkinnedObject` filter
would also include NPCs and miss player-owned objects in other scene classes,
so it is not the Players capture implementation.

World and Effects use reviewed scene-class keep-lists in
`dolly/layer_modes.py`. World is a scene-class isolation, not a reconstruction
of an arbitrary clean plate. Effects records black and white MP4 takes and
derives alpha during post-processing. Bloom settings are changed temporarily
for that matte pair and restored afterward. Separate reruns cannot prove
identical particles or temporal history, even with fixed simulation timing.

Players has real captured coverage alpha from one ownership pass, but this
does not establish full coverage of shadows, reflections, translucent effects
or all renderer techniques. Inspect the actual result. Per-player isolation
and general translucent-effect reconstruction remain separate work.

## Historical capture observations: September 12, 2026

Two supplied DX11 captures were inspected with RenderDoc 1.46. Both contained
a 2560 x 1440, single-sample D24S8 scene depth target separate from the target
bound at Present. The latter was cleared during late interface passes. These
captures motivated the scene-draw observer; their resource IDs are not runtime
identifiers.

The captured `PerViewConstantBuffer_t` values included
`g_vInvProjLowerRight2x2 = (0, -1, 1/7, 0)` and viewport depth range `[0, 1]`.
For that projection, positive camera-axis distance was approximately `7/z`.
These values describe those captures, not defaults for other cameras or builds.

A local single-frame float OpenEXR proof decoded byte-for-byte to its source
float buffer. The observation established numerical conversion for that
sample. It did not, by itself, establish live recording, moving-camera
alignment, hero classification or general renderer compatibility. Subsequent
backend and capture work must be assessed against its own source and evidence,
rather than treating an early open question as a current feature gap.

The inspected stencil values on actors were not a verified hero-only mask.
Deleting visible hero pixels also cannot recover the world behind them.
Transparent particles, glow and complete class-specific rendering require
separate evidence beyond an opaque-depth image or an ordinary diagnostic ZIP.

## References

- [HLAE Source 2 streams](https://github.com/advancedfx/advancedfx/wiki/Source2:mirv_streams)
  describes depth streams and an additional-render depth-matte example. Its
  documented CS2 behavior does not verify Deadlock player filtering.
- [DX11 OMGetRenderTargets](https://learn.microsoft.com/en-us/windows/win32/api/d3d11/nf-d3d11-id3d11devicecontext-omgetrendertargets)
  reports currently bound targets; it does not identify the correct earlier
  scene resource.
- [RenderDoc](https://github.com/baldurk/renderdoc) provides frame inspection
  of GPU resources and draw calls.
