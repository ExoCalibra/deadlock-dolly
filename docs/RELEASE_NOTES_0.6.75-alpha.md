### Deadlock Dolly v0.6.75-alpha

**0.6.75-alpha**

- **Stuck replay effects clear in one click.** *Before:* changing replay frames could leave Violet's paint, decals and screen post-processing from the old frame visible, and the Clear ragdolls button only removed ragdolls. *After:* the Scene appearance button is now **Clear stuck effects** and clears ragdolls, decals, screen post-processing and Violet's ink constructs without moving the camera or changing playback speed.

- **Mixed skin packs still load automatically.** *Before:* a skin pack that also contained interface, shader or post-processing files was skipped as a whole, so the VPK never registered. *After:* Dolly recognizes reviewed model, map, material, animation, scene and audio content inside the mixed mount and carries the pack automatically; pure UI/render packs are still refused.

- **Audio, campath and 6819 fixes remain.** *Before:* Dolly's isolated config reset audio levels, a longer effect track could leave an empty campath timeline tail, and the 6819 hotfix blocked normal editing. *After:* reviewed volume/mute/voip levels are carried, the campath timeline fits the authored camera range, and the 6819 camera, roster, follow, seek and native attach fixes remain.
