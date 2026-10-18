# Shipped visual fixes — reference, do NOT re-propose

Maintainer reference with versioned implementation and validation evidence.
For current operation and controls, use the [user documentation](../README.md).
Recorded results apply to the revisions described below.

Status: **fixed, shipped and visually accepted by Andrew**. Raised twice now, so
this file exists to stop future chats from re-opening them as bugs. Treat them
as closed unless a *game update* regresses them (see "Update-fragility" at the
end).

All four live in the same area: what the game draws/does with a **selected
player's** camera state while Dolly owns the free camera after F9 → F8.

## 1. Death desaturation / grayscale + damage vignette

- **Symptom:** after F9-select and F8, the selected hero's death grayscale and
  red damage vignette appeared on Dolly's camera.
- **Fix:** `native/src/native_gameplay_effects_win.hpp` hooks the selected-player
  post-process render-weight function and returns **zero** weight for the
  `Damaged` and `Killed` event vectors while Dolly owns a healthy camera.
  Event records, other effects and scene grading are untouched.
- **Anchors (reviewed client `cb831d12…`, image size `0x3cd0000`):**
  controller RVA `0x2df4cf0`; weight function `FUN_1807ed690` (`0x7ed690`);
  render caller return `0x7f734d`. Vector headers at `+0x20`, stride `0x28`;
  rows stride `0x20`. Only the first two vectors (Damaged, Killed) are filtered.
- **F9 / Player POV / release / fault / expired heartbeat:** original weights
  pass through.
- **Evidence:** `analysis/stability-20260925/DEATH-FILTER-20260926.md`
  (paired live run `death-pair-02`; Dolly max damage/death weights 0/0 vs
  F9/game 1.0, same Priest target). Shipped 0.5.46-alpha.

## 2. Red hurt / low-health screen-particle border

- **Symptom:** separate from #1 — the red hit-flash and low-health *pulse*
  borders remained (they are a screen-space particle layer, not the scalar
  post-process event).
- **Fix:** `native/src/native_gameplay_effects_win.hpp` hooks the render-graph
  render-option lookup and returns `0` **only for that exact call** while Dolly
  owns a healthy camera. Function bytes and call bytes are checked before
  install; every other lookup passes through unchanged.
- **Anchors:** option lookup RVA `0x576fd0`; the specific call at `0x5a72ff`,
  return `0x5a7304`. Zero at that call skips the screen-particle render setup and
  the Blit Screen Space Particles composite.
- **Scope of the filter:** hides the whole player screen-particle layer
  (including other effects that use that layer). World particles, Dolly
  particles, scene grading and unrelated render options are **not** targeted.
  Particle simulation/creation stay intact, so active overlays resume when game
  ownership returns (F9/Player POV/release/fault/expired heartbeat).
- **Evidence:** `analysis/stability-20260925/RED-SCREEN-20260926.md`
  (live paired run `red-screen-pair-01`; Dolly weights 0/0 vs F9 1.0). Shipped
  0.5.46-alpha. The particle assets and the frozen particle library were not
  edited.

## 3. Selected-player spectator mode carrying effects

- **Symptom:** after F9 selection, native pose ownership could leave
  `citadel_spectator_mode = 3` (PlayerView), so the selected-player spectator
  state survived into Dolly's camera.
- **Fix:** `Controller._detach_spectator_view` snapshots the current mode and
  selects/verifies **Free Cam (mode 1)** *after* the native camera captures its
  seed. Used for manual camera entry, saved-camera selection, timeline seeks,
  effects preview, capture re-arm and native path playback. Player POV
  preparation/playback does **not** call it. F9 restores the previous mode; Stop
  restores the saved value through the existing exact UI restoration path.
- **Spectator mode meanings:** `0` Directed, `1` Free Cam, `2` Hero Chase,
  `3` PlayerView.
- **Evidence:** `analysis/stability-20260925/SELECTION-FIX-20260926.md`
  (runs `selection-01`, `selection-fixed-01`). Shipped 0.5.46/0.5.47-alpha.

## 4. Lens / FOV following the watched player

- **Symptom:** after F9-select, the free-cam FOV followed the watched player's
  aim/zoom transitions.
- **Fix:** native lens/spectator pinning in `native/src/bridge_win.cpp` — Dolly
  holds the chosen lens while it controls the camera. Validated FOV constant
  `106.26` over ticks 20.6K–32K.
- **Evidence:** `HANDOFF-camera-fov-death-20260926.md`.

## Related, also already handled

- The spectator FOV/desaturation/auto-target **cvars** were the wrong lever and
  are treated as legacy: `citadel_camera_spectator_auto_target_view`,
  `citadel_death_replay_enabled`, `spec_replay_on_death`, `spec_replay_enable`
  (see `HANDOFF-camera-fov-death-20260926.md`). The shipped fixes above do **not**
  depend on them. If these are suggested again as the fix, point here.

## 4. The game-side UI override pack (not an unfinished experiment)

- **What ships:** `native/assets/ui/pak02_dir.vpk`, built from `native/ui_override`
  by `tools/build_ui_override.py`, hash-pinned in `dolly/launcher.py`
  (`UI_OVERRIDE_PACK_SHA256`) and mounted beside the confetti pack in **every
  native-camera session only** (console-camera sessions keep the stock UI).
- **What it changes:** it replaces five of the game's own resources - the hideout
  HUD layout, the shader-prewarm layout, and three stylesheets. Its three visible
  effects are the Dolly loading card at top center, the Deadlock client-status
  watermark hidden (`#DefaultStatus .GameLogoIcon`), and the dev
  match/server debug stats hidden (`#ClientServerDebugStats`). The watermark and
  debug-stat suppression were validated when the pack was introduced (0.6.22);
  the card was added and accepted in 0.6.52.
- **Do not re-open as "the Panorama experiment leaked into the product."** The
  source comment in `citadel_prewarm_assets_status.xml` still reads
  "Private opt-in Dolly Panorama loading experiment V2" from the prototype that
  produced the card. The card was deliberately promoted into the normal product;
  the label is historical, and the pack is unchanged since 0.6.52.
- **Real remaining work:** these are same-path stock replacements, so a Deadlock
  UI update must refresh both the sources and `STOCK_UI_SHA256` in
  `dolly/panorama_assets.py`, or Dolly refuses to launch native mode (fail-closed).

## Update-fragility (the only open, optional item)

All of #1–#3 are gated to the exact reviewed client SHA-256 plus verified
instruction/call bytes. A future client update can therefore disable them until a
new reviewed profile is produced — that is **deliberate fail-closed behavior**,
not a defect. The optional hardening is to re-anchor the render-option and
weight-function hooks to the render-option **interface/vtable** instead of exact
bytes (see `DOLLY-GHIDRA-IMPROVEMENT-MAP.md` §6). That is durability work; it is
**not** another "fix the red screen" task.
