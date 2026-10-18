# High-resolution screenshots

[Documentation](README.md) · [User guide](USER_GUIDE.md)

A screenshot is a clean still of the current paused view, built for
thumbnails: the normal game frame plus a players-only matte you can use as a
mask in Photoshop.

## Taking one

1. Open a replay in Dolly, pause it and frame the shot with the Dolly camera.
   You can start from free camera, Game Follow or a saved view. Finish or
   cancel **Bone Picker** before starting the screenshot.
2. Click **Take screenshot** on the desktop **Export** tab, or
   **Screenshot (hero + plate)** on the in-game **F8 → Export** tab.
3. Leave the game alone while Dolly records. It runs a lossless Color pass
   (with depth when selected), then a Players pass, and assembles the still.
   The status line and log show the folder when it is done.

The still is written to a new `Dolly_Still_<shot>_<timestamp>` folder beside the
Export tab's output file. If its output directory is unavailable, Dolly uses
your Pictures folder, or your home folder if Pictures is unavailable.

| File | Contents |
| --- | --- |
| `plate.png` | The normal game frame, 8-bit RGB. |
| `hero_alpha.png` | Players-only coverage matte, 16-bit grayscale. White is hero. |
| `hero_rgba.png` | The plate with that matte as its alpha, 16-bit RGBA: a ready cut-out. |
| `hero_isolated.png` | The Players layer rendered on its own, with straight alpha and an 8-bit preview tonemap. Its colors need not match the plate. |
| `depth.exr` | Float scene depth in game units (optional, **Include depth (EXR)**). |

"Hero" means every player pawn and its equipment (weapons, attachments,
carried objects). NPCs, creeps and the world are excluded, and scenery in
front of a hero still occludes it.

### Photoshop

Open `plate.png`, then load `hero_alpha.png` as a layer mask (or
**Select → Load Selection** from it). `hero_rgba.png` already has that mask
applied. Use `hero_isolated.png` when the plate's edge pixels carry too much
background color.

## Resolution

Stills are saved at the game's capture size, like video export. To render
larger than your monitor, pick a **Render size (next launch)** on the
Screenshot card (up to 7680 × 4320), then close the game and open the replay
again. Dolly saves `-windowed -noborder -w <width> -h <height>` in its own
replay launch settings; it does not change Steam's launch options. Choose
**Game window (no change)** to remove that size override from Dolly's settings.

The window then extends past the screen edges while you edit; this is
expected. Rendering at 8K is heavy: expect lower editing frame rates and
substantial temporary space during the Players pass. **Export → Encoder &
quality → Players scratch folder** chooses an existing local folder; blank
uses the output directory. The card shows the current game-window size.

Depth has a separate GPU readback budget. The offered 5K and 8K sizes exceed
the current depth budget at full render scale: clear **Include depth (EXR)**
for those sizes, or use 4K or lower when you need depth. Color and Players
still require enough GPU memory, disk space and a supported game build.

## How it works

The still is a short fixed-step layered export of a held camera pose: 12
frames at 60 FPS and 0.05× replay speed, so the replay advances about a
hundredth of a second. Dolly chooses zero-based frame index 8 (the ninth
frame) for the outputs to allow frame history to settle; this does not guarantee
identical particles, animation or temporal effects across separate passes.
The captured camera pose is held rather than continuing live Follow or bone
motion. Depth passes force 100% render scale for the take, then restore it.

## Troubleshooting

- **Take screenshot is disabled:** launch a replay through Dolly and wait for
  the native editor; finish any recording first.
- **Bone Picker is open:** finish or cancel it before taking the screenshot.
- **"Players capture did not finish cleanly":** the players layer is tied to
  the reviewed game build. After a Deadlock update it can stop working until
  Dolly's compatibility data is updated.
- **Depth failed:** clear **Include depth (EXR)** for a Color/Players still,
  or reduce the capture size. The current renderer also checks depth source
  and projection compatibility; 100% render scale does not make every
  antialiasing/upscaling mode compatible.
- **Recording requires an even-sized backbuffer:** choose an even render size.
- If a still fails, its folder is kept with the raw takes for diagnosis.

The Players matte covers the visible player-owned draws captured by the
supported renderer. It does not include every transparent effect, glow,
reflection or shadow around a hero. The [layer guide](LAYER_EXPORT.md)
describes those limits. Successful assembly removes the intermediate video,
depth sequence and Players take; the files listed above are the still outputs.

## Credits

See [Dolly credits and contributors](https://github.com/cravvnn/deadlock-dolly/blob/main/CREDITS.md)
for the people, projects and tools behind Dolly.
