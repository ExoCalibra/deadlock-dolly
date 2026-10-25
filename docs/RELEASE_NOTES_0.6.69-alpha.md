### Deadlock Dolly v0.6.69-alpha

**0.6.69-alpha**

- **Player following works on current builds.** *Before:* selecting a player in the replay timeline could fail with "The selected player controller changed. Select the player again." or an empty-roster message. *After:* Dolly follows the selected player on Deadlock 6813, using the verified live identity when the player roster is unavailable.

- **Early ticks explain themselves.** *Before:* selecting a player before the match had spawned heroes showed the same controller error. *After:* Dolly says the player has no hero at this tick, leaves the camera unchanged, and asks you to scrub forward to the match start and select again.

- **Non-ASCII install paths open normally.** *Before:* when Dolly or the Windows profile was under a non-ASCII folder (for example a Cyrillic OneDrive folder), the editing configuration check failed with "Deadlock's USRLOCAL search path could not be confirmed" and the replay never opened. *After:* Dolly decodes the console path with the active Windows code page, so the check passes and the replay opens normally.
