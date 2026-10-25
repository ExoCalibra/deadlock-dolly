### Deadlock Dolly v0.6.72-alpha

**0.6.72-alpha**

- **Works with Deadlock build 6819.** *Before:* after the 6819 hotfix, Dolly refused the new client and could not initialize its editor. *After:* Dolly recognizes 6819, initializes the unlocker, loads a replay and opens the paused camera editor normally; the reviewed 6814/6815/6817 builds remain supported.

- **Camera, follow and effects refreshed.** *Before:* the 6819 hotfix moved the camera, preload, follow, gameplay-effect and particle wrappers, so the 6817 anchors and unlocker tuple no longer matched. *After:* Dolly uses the reviewed 6819 client profile, follow anchors, observer schema, confetti row and unlocker tuple; replays recorded on 6812/6813 keep working.

- **Attach and bones keep their player list.** *Before:* the native player roster could be empty, so attach/bones reported that no players were in the loaded replay. *After:* Dolly reads the reviewed entity list and falls back to an identity scan, so the player list fills and attach/bones works.
