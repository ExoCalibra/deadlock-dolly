# Deadlock Dolly 0.6.48-alpha

Replay-effect settling for native camera-path playback and exports.

## Changes

- **Cleaner replay effects at the shot start.** *Before:* seeking could stack flashes, rings, and glow on a character as playback or recording began. *After:* Dolly runs a short normal replay lead-in before native camera-path shots, lets transient effects settle, and pauses at the original shot start before playing the camera path.
- **Preparation stays outside the export.** *Before:* setup frames could enter a camera-path Color export. *After:* recording begins after settling, reuses the prepared start without another seek, and admits frames from the camera path. Saved keys, shot timing, export speed, and FPS stay unchanged. Stop can cancel preparation before recording starts.

The lead-in targets two seconds and holds the opening camera while the replay advances. Dolly's authored effects begin with the shot. Frozen/manual captures and Player POV retain their existing behavior. Starts without enough prior replay history, a verified clock, or the required native/engine controls retain the existing preparation behavior.

## Validation

Matched local replay comparisons reproduced increased effect stacking after repeated seeking. Normal lead-in removed the excess glare and rings in the observed Deadman Danny scene while preserving normal zipline and buff effects.

Two bounded 30-frame Color exports at 120 FPS and half speed verified the first camera-path frame, selected timing, zero dropped frames, clean decoding, and unchanged saved projects. Cancellation before recording created no capture file. The accepted session restored all 43 saved configurations, cleared runtime restoration state, removed its deployment, and exited normally. The previously observed Steam networking shutdown assertion remains present; no new game crash or assertion appeared.

Source regressions and the release's native, portable editor, updater, packaged encoder, and frozen conversion-worker checks pass. The hardware encoder stress check remains excluded. The newly built portable binary has not been separately exercised in a live game session.

## Known limitations

This is a Dolly preparation mitigation, not an upstream replay-engine repair or a proven vertex-buffer fix. Other heroes and effect families may behave differently; new Players/Depth output and Player POV were not separately live validated for this mitigation. Repeated seeking in the ordinary game replay viewer can still stack effects.

Some replay characters and scenery can still appear dark or black. That separate issue remains unresolved. Saved-shot queuing remains deferred; the previous conversion controls, custom scratch folders, and remembered export destinations remain included.

## Updating

Extract the Windows x64 ZIP into a fresh folder and run Dolly.exe, or use Dolly's updater once this release is published. Python, Tcl/Tk, and the encoder are bundled.
