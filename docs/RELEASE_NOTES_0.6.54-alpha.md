### Deadlock Dolly v0.6.54-alpha

- **Startup that waits out a slow shader rebuild.** *Before:* the first hideout load after a Deadlock update could stop at exactly 120 seconds with "Timed out after 120s waiting for verified map and shader preload completion", leaving the game open and Dolly looking stuck. *After:* Dolly keeps verifying for as long as the game reports real preload progress, says how long it has waited and which shader batch it last saw, and only gives up after the preload goes quiet or runs past fifteen minutes.
- **Per-frame camera data for paired depth takes.** *Before:* matching CG or effects to a depth take meant eyeballing the camera. *After:* every paired depth take also writes a camera file with the exact per-frame camera the shot was rendered with — view and projection, depth range and frame identity — ready for a compositor or a 3D scene.
- **Camera files are checked with the take.** *Before:* nothing verified that a take's camera information was complete. *After:* the export audit validates the camera file against its take, and a cancelled or partial take never keeps one.
- **The float EXR choice can't be lost.** *Before:* ticking the depth sequence's float EXR frames before Depth itself was on silently dropped the tick in-game, and publishing from the desktop then failed. *After:* both editors grey the EXR control out until Depth is on, so the choice is never accepted and then discarded.

## Replay startup on a slower machine

Deadlock compiles shaders in batches and only reports a batch when it finishes,
so a single batch can run for over a minute on a slower machine. A Deadlock
update also discards the compiled shader cache, which makes the first hideout
load rebuild all of it. Dolly's verified startup now treats that as work in
progress: while the reviewed preload still holds its job, the wait continues and
Replay reports it, including the last batch and the time spent.

If the preload goes quiet, or keeps running past fifteen minutes without ever
reporting readiness, Dolly stops and offers to load the selected replay without
the preload check. The game session stays open either way, and the manual
**Connect**, **Initialize unlocker** and **Load replay** order remains available;
that path never required the preload check. Nothing is written to the game.

## Camera files for paired depth takes

A paired depth take now writes `camera.json` beside its frames. For every
recorded frame it carries the exact camera the shot was rendered with: view and
projection matrices, camera position and orientation, field of view, the depth
range and near/far mapping, the render resolution and scale, and the frame
identity. The stored conventions are documented in
[camera bundles](CAMERA_BUNDLE.md); the export audit checks a take against its
camera file during a take and on its own with
`python -m dolly.export_audit <folder>`. Cancelled or failed takes keep no
camera file.

The pixel mapping between a depth frame and that camera data is documented and
covered by fixtures and GPU readback tests, but it has not been confirmed on a
live capture yet.

## Depth notes

Float EXR frames of the depth sequence are read directly. The grey `depth.mov`
preview stays 10-bit quantized, so it is not the input for per-pixel depth math;
use the float EXR frames when the sequence option is available.

Game Follow is still held back on Deadlock build 6793 until its camera rig is
re-checked against the live game, and Dolly reports that instead of running
against unverified offsets. Depth normal reconstruction and the float EXR reader
ship as internal groundwork: they are not exposed as a capture option yet.

## Updating and release assets

Extract the complete **Deadlock_Dolly_0.6.54-alpha_Windows_x64.zip** into a fresh
folder and run **Dolly.exe**, keeping **_internal** beside it. Existing installed
versions can use Dolly's updater after publication; **Update now** is required
before downloading or installing.

That Windows ZIP is the release's only attached file. The
**Deadlock_Dolly_0.6.54-alpha_Source.zip** and **SHA256SUMS.txt** are built beside
it and kept locally as build records; source is public, so developers use the tag
or the repository. Use tag **v0.6.54-alpha** on the tested main-branch commit and
mark the public release **Latest**, with GitHub's pre-release box unchecked.
Publishing remains a manual step; pushing the source does not publish a release.

See the [in-game editor guide](UI_REWORK.md) for the controls and the
[changelog](CHANGELOG.md) for the complete change list. Paired depth takes now
also write a camera file; the existing depth and layer guarantees are otherwise
unchanged.