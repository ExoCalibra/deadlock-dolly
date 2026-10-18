### Deadlock Dolly v0.6.59-alpha

**0.6.59-alpha**

- **Replay seeking.** *Before:* seeking between recorded replay ticks could leave the editor waiting for a timeout. *After:* replay controls choose a recorded tick in the requested direction and report where they stopped.

- **Players layer framing.** *Before:* a smaller internal render viewport could leave players shrunken inside the exported frame. *After:* the Players image fills its output canvas while preserving scenery occlusion.

## Replay controls

Absolute replay-timeline and relative replay seeks now use the completed replay
file's verified packet boundaries. Backward seeks choose a preceding recorded
tick; forward seeks choose a following recorded tick. Available exact targets
stay exact. The status message reports an adjustment instead of presenting the
requested tick as the actual position.

Unsupported or unavailable packet indices retain the existing exact-seek
verification. A replay-file length that differs from the loaded replay is
rejected. Replay identity, stable paused-state checks, camera restoration and
cancellation remain in place. A new seek also clears the previous Stop flag
without ignoring cancellation during the new operation.

## Players capture

An upscaler can render into a viewport smaller than its scene texture allocation.
Players capture now maps that active region across the exported image instead
of including the unused texture padding around it. It retains the original
player draw, material values and scenery depth test. Normal full-sized captures
keep their existing copy path.

Unsupported, multiple, out-of-bounds or changing viewports are rejected. The
framing correction does not reproduce the game's temporal antialiasing history,
upscaler filtering or post-processing, and does not promise identical edges in
the Color and Players passes.

## Validation boundary

Offline regressions reproduce the seek timeout on a missing replay tick and
the smaller Players image inside a larger canvas. Coverage includes camera
restoration, cancellation, Stop followed by a new seek, active-viewport mapping,
original render-state preservation and scenery occlusion. A software-rendered
fixture also passes through Players MOV encoding and independent decoding.

The affected users' original replay diagnostics and take were not available.
Their fresh retests remain necessary to confirm these changes address their
particular reports. See the [layer guide](LAYER_EXPORT.md) for output limits.
