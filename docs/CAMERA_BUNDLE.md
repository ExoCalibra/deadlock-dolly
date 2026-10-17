# Camera bundle (camera.json)

A paired depth take carries a `camera.json` beside its depth master and EXR
sequence. It records, for every admitted output frame, the camera calibration
the renderer **actually used** for the captured scene sample — not a fresh
estimate from the authored path. Compositors use it to line up a 3D scene with
the recorded plates.

- Location: the depth master's own directory (`<video>.depth/`, or
  `<take>/depth/` for layered takes).
- Written only when the take completes: a cancelled or failed take keeps no
  bundle, so a partial take can never masquerade as a complete one.
- Frame alignment: `frame` is the zero-based encoded color frame index, matching
  the EXR file names and the depth manifest's order. `sample` and
  `capture_pts_100ns` carry Dolly's capture identity; encoded video timing may
  differ from the capture timestamp (same caveat as the depth manifest).
- The bundle pairs with the **depth master's size**, which can be below the
  color recording when the game renders the scene at an internal resolution;
  the header carries both (`width`/`height` and `color_width`/`color_height`).

## Format version 1

```json
{
  "format": "deadlock-dolly-camera",
  "version": 1,
  "complete": true,
  "frames": 30,
  "width": 2560,
  "height": 1440,
  "color_width": 2560,
  "color_height": 1440,
  "units": "positive camera-axis game units",
  "records": [
    {
      "frame": 0,
      "sample": 0,
      "replay_time": 12.5,
      "capture_pts_100ns": 0,
      "state": "complete",
      "view": [16 numbers],
      "position": [3 numbers],
      "up": [3 numbers],
      "forward": [3 numbers],
      "projection": [16 numbers],
      "inverse_z": [4 numbers],
      "viewport": [0, 1],
      "near": 7,
      "far": null
    }
  ]
}
```

`far: null` means the far plane is at infinity (an infinite projection).

## Conventions

Both matrices are stored **row-major** (index `i·4 + j` is row `i`, column `j`),
but they are applied with different multiplicands — exactly as the engine's
per-view constants do. Do not assume one convention for both.

- **`view`** — world → view, 4×4 affine, applied as a **row vector**:
  `v_view = [x y z 1] · V`, so `v_view[j] = (world − position) · column j`
  (the translation row is −position·M, which validation checks). Rows 0–2 hold
  the basis with a trailing `0`; row 3 holds the translation with a trailing
  `1`. The columns of the 3×3 part are the camera axes in world space:
  column 1 is `up` and column 2 is `backward` (`forward` = −column 2); column 0
  is the remaining orthonormal axis (its chirality follows the game's
  convention — do not assume a cross-product order). `position` is the camera's
  world position.
- **`projection`** — view → clip, 4×4, applied as a **column vector**:
  `clip[i] = Σ_j P[i][j] · [v_view, 1][j]`. `[0][0]` and `[1][1]` are the
  horizontal and vertical scale; the lower-right 2×2
  (`[2][2] [2][3]; [3][2] [3][3]`) maps `(vz, 1)` → `(clip_z, clip_w)`.
  `inverse_z = [a, b, c, d]` holds that 2×2's ordinary matrix inverse,
  row-major. Non-oblique projections only (`[2][0] [2][1] [3][0] [3][1]` are
  zero: no Z/W dependence on X/Y).
- **Clip → device**: `ndc = (clip.x/clip.w, clip.y/clip.w, clip.z/clip.w)`,
  then `device_z = viewport_min + ndc_z · (viewport_max − viewport_min)`.
- **Distance**: `linear_z = (device_z − viewport_min) / (viewport_max − viewport_min)`,
  `distance = −(a·linear_z + b) / (c·linear_z + d)` with
  `inverse_z = [a, b, c, d]`. Positive values are camera-axis distance in game
  units; `near` and `far` are the linearized clip range (`far` may be infinite).
  The convention is reversed-Z-friendly: read the direction from the data, do
  not assume it.
- **Pixel**: `x = (ndc_x + 1)/2 · width`, `y = (1 − ndc_y)/2 · height`
  (origin at the top-left of the depth master). This mapping is documented for
  reconstruction; live verification against a known object is still pending.

`state` is `complete` when `view`/`position`/`up`/`forward` were captured from
the same validated per-view constants as the projection, or `projection-only`
when the view side was not available for that frame (the bundle then carries
`"complete": false`). Frame identities (`frame`, `sample`, `capture_pts_100ns`)
still apply to a `projection-only` record.

## Reading it

`dolly/camera_bundle.py` loads and validates the file and can project a world
point through a record (`load_bundle`, `validate_bundle`, `project_point`).
`dolly/export_audit.py` checks a bundle against its manifest after a take.

## Provenance and limits

Values come from the engine's per-view constants sampled at the scene draw of
the captured frame (the reviewed `PerViewConstantBuffer_t` layout). The
projection's horizontal/vertical scale is part of that same reviewed layout; the
pixel mapping above is documented but not yet validated in-game. Effects that
change the camera after the scene pass (DOF, post) and attachment motion are
covered insofar as the sampled constants are the ones the scene was rendered
with — the record describes the captured render, not the authoring timeline.
