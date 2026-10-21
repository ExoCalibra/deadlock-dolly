### Deadlock Dolly v0.6.64-alpha

**0.6.64-alpha**

- **Support the latest Nurse Harrow hotfix.** *Before:* the game updates changed Dolly's camera and unlocker fingerprints. *After:* Dolly includes reviewed build 6807 camera dependencies and its matching server unlocker, preserving the earlier reviewed profiles. Unknown native layouts still require review.

- **Start with clean editing settings.** *Before:* competitive graphics, saved commands and addon mounts could affect a Dolly session, and the older editing baseline also contained visual performance overrides. *After:* Dolly starts from verified stock configuration, mounts its own reviewed default scripts and uses a separate settings folder for each session. Normal-play configs stay untouched; saved Dolly graphics profiles apply only inside that session.

- **Continue through startup.** *Before:* the early-development notice could return in a clean session and block the hideout intro. *After:* Dolly disables that notice only for its own session and keeps normal intro continuation automatic. Hero announcements stay available; **Check startup again** repeats the normal checks if another screen needs attention.

- **Make Console Legacy a useful fallback.** *Before:* its primary startup still depended on native camera fingerprints and private client startup readers. *After:* choosing Console opens the manual Startup controls through the normal launcher. Configuration and unlocker checks remain independent requirements; an unsupported native client does not automatically disable this route.

## Clean editing sessions

The bundled gameinfo and stock defaults match build 6807's installed Steam depot
content and manifest. Their payloads are unchanged from the reviewed 6801 baseline. It retains stock fog and shadow configuration. Dolly adds
the user-config read/write guard and directs legacy settings lookup to its own
USRLOCAL directory. Its temporary mount supplies current stock defaults and
empty user startup scripts with priority for both Game and Mod lookups.

Dolly's process receives a separate settings directory under its session logs.
It does not replace Steam's normal-play `video.txt`, saved ConVars, bindings or
autoexec. Device/display identity may be copied read-only; render scale starts
at 100% and upscaling is off in the clean baseline. Explicit Display launch
options take priority over copied resolution/window settings.
Quality values follow the current stock High preset, with distance-field AO
kept at the current engine default rather than requesting an unverified override.

**Clean Dolly settings (default)** is the default graphics choice. Named Dolly
profiles remain available for intentional quality changes, applied only to the
separate folder. In-game settings changes belong to that Dolly session. Normal
game bindings start from stock defaults; Dolly's own saved Controls remain in use.

Before opening the replay, Dolly reads back the engine's user-config guard and
the entire USRLOCAL search-path listing. It refuses an unconfirmed or additional
settings root. Preparing files alone does not count as runtime confirmation.

Engine-recorded game audio is collected from the same owned editing session.
Audio cleanup removes only that recording's WAV and preserves unrelated files.

The user's exact original gameinfo bytes are journaled before the temporary
swap and restored through the existing startup/exit/recovery path. Older Dolly
graphics journals still recover their original files, with conflict protection.
Keep logs while recovery is pending. Unclassified files in a temporary session
folder are retained rather than deleted.

## Startup and Console Legacy

Dolly disables Deadlock's early-development notice inside its temporary editing
configuration and automatically advances the normal **Press any key to Start**
intro. Normal-play preferences stay untouched. Hero announcements and other
prompts remain available; dismiss those in the game. Dolly waits for the actual
intro and preload. If startup pauses for attention,
choose **Check startup again** to recheck the existing session; Dolly does not
relaunch the game or treat elapsed time as readiness.

For **Console (legacy)**, wait for the hideout and use **Connect → Initialize
unlocker → Load replay → Check camera support** in Startup controls. This path
uses console camera controls and does not enable native recording or layers.

The editing-configuration contract checks its own engine, settings and filesystem
dependencies, the reviewed unlocker server, and current stock content recorded
in Steam's installed content manifests. It does not require ordinary competitive configs
to match stock. A changed or unavailable dependency still stops launch with a
specific reason; Console is not a promise of compatibility with every game patch.

## Compatibility and limits

Compatibility remains tied to exact reviewed modules and their individual
consumers. A camera check does not certify every rendering feature or effect.
The previously open empty/offscreen Players capture, extra-layer particle
consistency and Frozen clock investigations are not declared fixed here.
Experimental prop creation and private renderer queue diagnostics retain their
existing build restrictions.

The After Effects and USD camera-export workflows, previous export recovery
fixes, authored shots and Dolly settings remain part of this version. This
update does not add map, material or editable-particle scene export.
