### Deadlock Dolly v0.6.71-alpha

**0.6.71-alpha**

- **Works with Deadlock builds 6814, 6815 and 6817.** *Before:* after the 6814/6815/6817 updates, Dolly could not initialize its editor on the new builds. *After:* Dolly recognizes them, initializes the unlocker, loads a replay and opens the paused camera editor normally.

- **Camera, follow and effects refreshed.** *Before:* the 6814 update moved the camera/preload/follow code and particle wrappers, and the previous anchors would fail or misbehave. *After:* Dolly uses the reviewed 6814/6815/6817 client profile, follow anchors, observer schema and unlocker table; replays recorded on 6812/6813 keep working.

- **Attach and bones can find players again.** *Before:* the player roster was empty on 6817, so attach/bones reported that no players were in the loaded replay. *After:* Dolly reads the reviewed entity list and falls back to an identity scan, so the player list fills and attach/bones works.
