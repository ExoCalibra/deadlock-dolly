### Deadlock Dolly v0.6.66-alpha

**0.6.66-alpha**

- **Skin and map mods load in Dolly again.** *Before:* the isolated editing session left every installed mod mount out, so skins and custom maps were missing for the whole session. *After:* content mods are mounted again while Dolly's reviewed editing configuration still supplies the session's settings; your own gameinfo is restored exactly on exit.

- **Render and interface mods stay out of your shots.** *Before:* mod mounts were all-or-nothing, so a visual override could fight Dolly's HUD hiding and capture, or every mod had to be ignored. *After:* Dolly checks each installed mount's content and skips Panorama, shader, particle, effect and startup-config overrides, naming every skipped mount and its reason in the session log.

## Mods in an editing session

Dolly reads the addon search paths already in your installed `gameinfo.gi` and
decides what may join its temporary session by looking at the mount's content,
never at a mod's name.

Carried: models, skins, custom maps, animations, sound, and material overrides
that live under `materials/models` or `materials/maps`. Skipped: Panorama/UI,
shaders, particles, effects, `cfg` startup files, other material overrides, and
anything Dolly cannot read. Packed mods are checked from their VPK directory
tree without reading payloads. Each skipped mount is named with its reason in
the session log and in `session.json`; unreadable or linked content is refused
rather than guessed at.

A mod manager's shared `citadel/addons` folder is one mount. If a render or
interface mod sits in that same folder, the whole mount is skipped so the
override cannot load. Dolly's temporary unlocker mount stays ahead of the mod
mounts, and the exact original gameinfo is restored on exit.

## Compatibility and limits

This update changes which installed mod mounts join a session. The temporary
file cleanup, shot preparation, graphics runtime check and diagnostics listing
from 0.6.65 are unchanged. It adds no new game build, camera dependency,
unlocker, graphics profile or export change, and it makes no new claim about any
rendering feature or effect.
