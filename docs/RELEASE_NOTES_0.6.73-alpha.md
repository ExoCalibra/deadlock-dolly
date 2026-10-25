### Deadlock Dolly v0.6.73-alpha

**0.6.73-alpha**

- **Mixed skin packs can load in Dolly.** *Before:* a skin pack that also contained interface, shader or post-processing files was skipped as a whole, so the skins never appeared. *After:* enable **Load mixed mod packs** in Settings and the pack is carried into the editing session; it stays off by default because those extra files can change captures or override Dolly's interface hiding.

- **Your audio levels stay yours.** *Before:* Dolly's isolated editing configuration started with empty audio convars, so a quiet game mix could come back at default/max volume. *After:* Dolly copies the active profile's reviewed volume, mute and voip levels into the editing session while keeping performance and interface settings isolated.

- **The campath timeline no longer grows an empty tail.** *Before:* after playback or recording, the camera timeline could fit the longer effect-track duration, leaving a zoomed-out empty end that looked like an extra camera. *After:* it fits the authored camera range, so only real cameras remain on the path timeline.

- **6819 camera and attach fixes remain.** *Before:* the 6819 hotfix and empty player roster blocked normal editing. *After:* the 6819 camera, preload, follow, seek, confetti and native attach/bones roster fixes from 0.6.72 remain in this build.
