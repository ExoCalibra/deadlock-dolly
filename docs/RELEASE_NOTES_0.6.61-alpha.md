### Deadlock Dolly v0.6.61-alpha

**0.6.61-alpha**

- **Deadlock build 6796 support.** *Before:* Build 6796 was outside Dolly's reviewed camera and unlocker profiles. *After:* Native camera, Follow, fixed-step audio and the cvar unlocker work on the updated build.
- **Audio in slow-motion exports.** *Before:* Fixed-step exports were silent unless audio was muxed by hand. *After:* 0.25x/0.5x Color exports record game or reconstructed audio at the selected speed and full duration.
- **Timeline seeks keep Game Follow.** *Before:* Scrubbing with F9 Game Follow snapped the camera back to its pre-seek pose. *After:* The selected hero stays followed through the seek.
- **Reconstructed audio just works.** *Before:* Users had to install Source2Viewer and set an environment variable. *After:* Dolly offers a one-time verified helper download and caches it automatically; no manual setup.
