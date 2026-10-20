### Deadlock Dolly v0.6.63-alpha

**0.6.63-alpha**

- **Check Native Depth of Field before use.** *Before:* Native DOF support was harder to diagnose, and the support check could miss a newly selected game folder. *After:* Dolly checks the installed shader and material indexes, explains missing or unreadable files, and offers a local support report from the selected install.

- **Pause shots more reliably.** *Before:* Pausing a fixed-step shot could make Dolly mistake an ordinary render sample for a replay jump and stop the export. *After:* Dolly checks fresh paused views and the stable replay clock against the position recorded before its Pause command. Real timeline jumps and changed replays still stop the shot.

- **Recover interrupted exports.** *Before:* A failed shot could leave Players capture armed, and stopping could discard its last eligible image. *After:* Dolly waits for the matching capture to stop, retains an image already prepared for that stop, and reports the original failure with restoration status. Completed takes and Players scratch data are kept; uncertain recovery remains pending.

- **Keep error dialogs visible.** *Before:* An error could open outside the monitor or leave the wrong window enabled behind a Save dialog. *After:* Dolly keeps error controls on the owner's monitor, restores a minimized owner, and preserves the correct modal ownership and keyboard focus.

## Native Depth of Field support

The File menu's Native DOF support check uses the selected Deadlock installation,
including before the first replay launch. It reads the installed shader and
material indexes and reports missing or unreadable entries without copying game
files or exposing the installation's absolute path in the support report.

Dolly uses the shipped shader path when the optional shader compiler is
unavailable. A failed or unreadable check stays refused on later applications;
it cannot silently become permission to enable the pass. A ready index check
does not verify shader payload integrity, every permutation, or rendered pixels.
If the checkerboard persists after a ready result, export diagnostics so the
actual failed shader request can be investigated.

## Paused replay clock

Dolly records the selected replay's clock before issuing its own Pause command
during an authored shot. Confirmation requires fresh rendered views and a stable
paused replay clock, checked independently of a single rendered tick sample.
The playback monitor uses that owned pause result rather than treating an
ordinary difference between the render and replay clocks as a timeline jump.
Backward or forward seeks, replay or session changes, unreadable state and
cancelled operations retain their existing guards.

## Interrupted export recovery

A failure reported by the camera playback monitor now reaches the recording
worker. Dolly clears queued layer passes, cancels associated audio and stops the
interrupted recording. It attempts camera, recording and scene restoration only
while the owned replay can be verified, then reports the original playback error
with any remaining recovery work. It does not automatically repeat a failed
recovery on every interface update.

Players cancellation waits for a terminal status belonging to that capture's
request before releasing its recording reservation. An incomplete Players pass
is treated as cancelled, not as successful output. If stop acknowledgement is
missing or stale, the pending state stays visible rather than allowing another
capture to overlap it. Completed earlier takes and interrupted Players scratch
data are retained for inspection.

## Final Players image handoff

A Players stop can arrive after an image is prepared but before Present hands
it to readback. Dolly retains that eligible image for the same capture and
sample while stop finishes, then drains the existing writer before closing.
Late or mismatched images remain refused, and timeouts and strict frame-count
checks stay in force. This addresses one stop-ordering failure; it does not
establish a fix for every "missed shot frames" report.

## Error dialog visibility and ownership

Error windows use the actual owner's monitor work area, restore a minimized
owner, and keep their buttons accessible when the owner is off screen or the
message is long. Copy error details keeps the complete message. When another
modal window such as a Save dialog is open, the error uses that window as its
owner and restores only the enabled state it changed. Closing the error returns
keyboard focus to the appropriate existing control.

## Remaining investigation

This release does not establish a fix for the reported Violet ability 2 or
Mystic Regen particles in extra export layers. The exact layer and FPS/speed
remain unspecified, and no affected replay and event were available for a
matched comparison. Players captures player-owned geometry; Effects covers
particle-system scene classes and estimates alpha from separate black/white
takes. Neither output promises every visible ability contribution. Existing
replay-effect settling remains in place; extra-layer particle fidelity and
black map props still need their own reproductions and visual checks.

Fully empty or offscreen Players views remain under investigation: a valid
transparent scene must be distinguished from missing or unsupported draw
coverage. Capture still refuses missing or mismatched frames.

This is a support update to 0.6.62-alpha. Its prior camera, audio and reviewed
Deadlock compatibility support are retained.
