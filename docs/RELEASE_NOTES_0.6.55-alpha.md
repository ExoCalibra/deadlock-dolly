### Deadlock Dolly v0.6.55-alpha

**0.6.55-alpha**

- **Choose players from Dolly again.** *Before:* Dolly's timeline refused player selection on the current Deadlock build with a camera-profile review error. *After:* select and switch heroes directly from Dolly's replay timeline.

- **Smooth Follow slide transitions.** *Before:* following a sliding hero could pull the camera toward the map origin as the slide started or stopped. *After:* Dolly Follow keeps the camera with the hero through those transitions.

- **Update highlights appear.** *Before:* releases using the normal version heading could show no highlights inside Dolly. *After:* the update notice reads both the published heading and bold version lines, so supported release descriptions appear in the app.

## Follow on the current Deadlock build

Player selection and the Follow slide correction are reviewed for Deadlock
6793/6794. Selecting heroes through Dolly's timeline and following slide
transitions have been confirmed in a live editing session. The correction runs
while Dolly Follow is active and preserves the game's normal camera framing.

## Depth, EXR and normals groundwork

Existing paired depth/EXR exports and their per-frame camera files remain
available. Live paired-depth takes have passed cross-frame depth/projection
consistency checks, and sampled EXR frames produce consistent reconstructed
normals. The mapping conventions are documented in [camera bundles](CAMERA_BUNDLE.md).

Normal reconstruction and the float EXR reader remain offline groundwork in the
source. This release adds no Normals export option. The grey depth video remains
a preview; use float EXR frames for per-pixel depth calculations.

## Updating and release assets

Extract the complete **Deadlock_Dolly_0.6.55-alpha_Windows_x64.zip** into a fresh
folder and run **Dolly.exe**, keeping **_internal** beside it. Installed versions
can use **Update now** after publication.

Attach only the Windows ZIP to the release. The Source ZIP and checksum files
remain local build records; developers can use the repository or release tag.
Use **v0.6.55-alpha** on the tested main-branch commit and mark the public release
**Latest**, with GitHub's pre-release box unchecked. Publishing remains manual.
