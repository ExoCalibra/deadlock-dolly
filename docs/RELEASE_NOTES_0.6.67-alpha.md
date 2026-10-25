### Deadlock Dolly v0.6.67-alpha

**0.6.67-alpha**

- **Works with Deadlock build 6812.** *Before:* the game updated to 6812 and Dolly could not start an editing session on it. *After:* Dolly recognizes 6812, initializes the unlocker, loads a replay and opens the paused camera editor normally.

- **Unsupported encoders are refused safely.** *Before:* choosing Software H.264 (x264) with the bundled FFmpeg could stop the recorder on its first frame and leave the game held. *After:* Dolly checks the configured FFmpeg before recording, refuses encoders it cannot provide, and restores the game if a recorder fails.

- **One format for the whole take.** *Before:* the format came only from the encoder, layer takes could fail with "must end in .mkv", and a typed extension was rejected after a shot was prepared. *After:* one Format choice (MP4, MKV or MOV) sets the color take and every layer take, the mattes and audit follow it, and an incompatible encoder switches to Auto.

- **Fewer interrupted takes.** *Before:* a single console stall or a brief disk slowdown could throw away a whole export or Players take. *After:* one transient console reply is retried, and a refused Players frame is retried for a short bounded window before stopping.

## Formats and master files

The Format choice applies to the color take and its layer takes, including the
black and white matte passes. The depth master and the alpha masters
(`players.mov`, `effects.mov`) keep their ProRes `.mov` pipeline formats, because
the editing and depth workflows expect them.

MP4 and MOV use the selected encoder normally; MKV works with the hardware and
software encoders as well as Lossless FFV1. The built-in Windows Media
Foundation writer can only create MP4, so choosing MKV or MOV with it switches
the encoder to Auto. If the configured FFmpeg does not provide the selected
encoder, Dolly refuses the take before the replay is reloaded.

## Diagnostics

An exported diagnostics report now names the faulting module, offset and access
type/address from the newest Deadlock crash dump, so a game-side crash can be
identified without installing a debugger.

## Compatibility and limits

This update adds Deadlock build 6812 compatibility (client profile, preload,
replay camera, unlocker and confetti) and changes layer file naming, the export
format control, encoder selection and two transient-retry behaviors. Camera
and unlocker anchors were verified live on 6812; earlier reviewed profiles are
retained.
