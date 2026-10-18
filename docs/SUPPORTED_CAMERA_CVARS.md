# Supported camera cvars

[Documentation](README.md) · [User guide](USER_GUIDE.md)

These 14 effect controls support fixed values and animated tracks in Native
mode. Framing uses the separate camera aspect curve. The installed game
must pass Dolly's module/type checks. Console-only camera variables are not
promised to update with every rendered frame.

| Command | Input | Curves |
| --- | --- | --- |
| `r_citadel_depthoffield_enable` | 0 or 1 | Step |
| `r_citadel_depthoffield_focus_distance` | 0–10000 | Step, Linear, Smooth |
| `r_citadel_depthoffield_aperture_diameter` | 0–3 | Step, Linear, Smooth |
| `r_citadel_depthoffield_sensor_size` | 0.5–3 | Step, Linear, Smooth |
| `r_citadel_depthoffield_mode` | 0, 1 or 2 | Step |
| `r_citadel_depthoffield_debug` | 0 or 1 | Step |
| `r_depth_of_field` | 0 or 1 | Step |
| `r_dof_override` | 0 or 1 | Step |
| `r_dof_override_ranges` | 4 numbers: near blurry, near crisp, far crisp, far blurry | Step, Linear, Smooth |
| `r_dof_override_near_blurry` | Finite float32; negative values allowed | Step, Linear, Smooth |
| `r_dof_override_near_crisp` | Finite float32; negative values allowed | Step, Linear, Smooth |
| `r_dof_override_far_crisp` | Finite float32; negative values allowed | Step, Linear, Smooth |
| `r_dof_override_far_blurry` | Finite float32; negative values allowed | Step, Linear, Smooth |
| `r_dof_override_tilt_to_ground` | Finite float32; negative values allowed | Step, Linear, Smooth |

`r_aspectratio`: author it on the camera framing curve, from 0.5 to 4.
This is synchronized with the native camera; do not duplicate it as an
effect track or fixed shot variable.

## Range DOF

The in-game **F8 → Look → Depth of field** card exposes the range and tilt
controls. Capture a camera first, pause the replay and stop playback. **Enable DOF**
activates both required switches and initializes a missing/empty range track
with the same values as the desktop preset. Switching off and on preserves
existing focus pulls. **Individual focus overrides** expands the four separate
range cvars; **Ground tilt** is beside the main focus ranges. The separate
**Citadel DOF** card exposes the game's other DOF controls.
Edits apply on release at the held camera without seeking; animated channels receive a key at the
playhead, and other channels become fixed shot values. Unauthored controls
display defaults, rather than readback of arbitrary external console changes.

On the desktop Look page, click **+ Range DOF**. The preset enables
`r_depth_of_field` and `r_dof_override`, and adds a range track. Edit each
key as four numbers separated by spaces, for example:

```text
-100 0 180 2000
```

The order is **near blurry, near crisp, far crisp, far blurry**. All four
components use the same shot time and are applied together through one
native typed setter call. Each component interpolates independently.
Four zeros (`0 0 0 0`) disables the direct range override and lets the
game use its other range settings. Stop restores the complete original
value unless an explicit restore value was entered.

Available controls depend on the installed game's reviewed native profile and
typed cvar bindings. An older accepted profile may expose only the original
seven controls; accepting a camera profile does not bypass the effect checks.
The six range/tilt numeric controls have no declared game limits; Dolly
requires finite float32 values. Their actual appearance depends on the
game render pass and graphics settings. This does not guarantee an
anti-aliasing improvement over the Citadel DOF controls.

Vector tracks require a project format that supports four-component values.
Other authored features can select a newer format, so do not manually change a
shot's format number. The [JSON companion](SUPPORTED_CAMERA_CVARS.json) lists
types, component counts, bounds and the original verification fingerprints;
the running editor checks the current installed-game profile separately.

## Credits

See [Dolly credits and contributors](https://github.com/cravvnn/deadlock-dolly/blob/main/CREDITS.md)
for the people, projects and tools behind Dolly.
