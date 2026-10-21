# Dolly program icon — 0.2.2

The exact image reattached by the user is preserved byte-for-byte as
`logo-original.png`. Its SHA-256 is
`8edbc0fb726e16876345a861b16591cc9fc99cf30aef7ecacbd2e4c2ad478a2f`.
No redesign, image generation, repainting, cropping or background change was
performed for this release. The white backing is already in the supplied file.

`dolly.png` is a 256 px resampling for Tk fallback. `dolly.ico` contains 16, 20,
24, 32, 40, 48, 64, 128 and 256 px images, all encoded as 32-bit BGRA DIBs with
40-byte BITMAPINFOHEADERs, double-height fields and DWORD-aligned AND masks.
Every decoded frame is pixel-identical to its corresponding source resampling.

This bitmap encoding avoids the PNG-in-ICO incompatibility in older Tk 8.6
Windows readers. It is a packaging conversion, not a change to the logo.
The editor needs no Pillow dependency; icons are ready to use.

The artwork is separate from the source-code license. No ownership or
additional redistribution rights are asserted here.

## Editing game configuration

`editing/gameinfo.gi` uses stock configuration verified against build 6807
Steam depot content. Dolly's scoped changes disable standard user config
reads/writes, keep legacy settings lookup in its isolated USRLOCAL root and
disable the specific early-development warning for the editing session. Normal
intro continuation and hero announcements retain their existing behavior.
The launcher adds only its own temporary mounts, with clean defaults for
both Game and Mod lookups and an owned relative write directory.

`editing/cfg/` contains the current stock configuration/input defaults plus
Dolly's empty autoexec/config entry points. `cfg-manifest.json` records every
payload hash and stock provenance; `profile.json` pins that manifest, gameinfo,
video baseline and the reviewed installed modules/server. Refresh these pins
only with corresponding semantic compatibility evidence. The separate video
baseline imports no competitive quality values, upscaler or render scale.

These are game configuration data, not Dolly source code. The Dolly license
does not confer rights to Valve content. Runtime confirmation and visual checks
remain separate from stock-byte and offline module proof.
