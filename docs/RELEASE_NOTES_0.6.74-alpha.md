### Deadlock Dolly v0.6.74-alpha

**0.6.74-alpha**

- **Skin packs load without a hidden setting.** *Before:* a skin pack that also contained interface, shader or post-processing files was skipped as a whole, so the VPK never registered. *After:* Dolly recognizes reviewed model, map, material, animation, scene and audio content inside the mixed mount and carries the pack automatically; pure UI/render packs are still refused. The mixed-pack checkbox remains for packs with no recognized skin content.

- **Audio and campath timeline fixes remain.** *Before:* Dolly's isolated config reset audio levels, and a longer effect track could leave an empty campath timeline tail that looked like an extra camera. *After:* the active profile's reviewed volume/mute/voip levels are carried, and the campath timeline fits the authored camera range.

- **6819 camera and attach fixes remain.** *Before:* the 6819 hotfix and empty player roster blocked normal editing. *After:* the 6819 camera, preload, follow, seek, confetti, stock provenance and native attach/bones roster fixes remain in this build.
