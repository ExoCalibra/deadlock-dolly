# In-game editor

The main panel has five tabs: **Camera**, **Follow**, **Bone Picker**, **Look**
and **Export**. Your saved cameras are in **Campaths** on the left, with the
timeline and playback controls below.

Fresh layouts put Campaths in the upper left and the main panel in the upper
right, leaving space above for ReShade's startup banner. Saved main-panel and
Campaths arrangements take priority over these defaults. Outside Arrange, the
timeline stays near the bottom of the screen while keeping its custom width
and horizontal position.

The UI rework and saved layouts were contributed by
[@tbhtho](https://github.com/tbhtho).

## Show or hide the panels

Press **F8** to hide the main panel, Campaths and the timeline together. Press it
again to bring them back in their current layout. Path guides and the
framing grid can stay visible with the panels hidden; path guides hide during
playback.

Starting **Play cinematic** hides the panels automatically. You can press F8 to
bring them back while the shot keeps playing. **F9** opens Deadlock's own replay
controls.

## Arrange your workspace

Drag the main panel or Campaths by its header. The four-arrow cursor shows where
you can grab it; you do not need to turn on an arrangement mode first.

Open **Layout** for the other layout controls:

- **Arrange panels** lets you move the timeline, resize panels and rearrange
  sections within a tab. Leaving Arrange reattaches the timeline near the bottom
  of the screen, keeping its width and horizontal position.
- **Classic arrangement** restores the default upper-left Campaths, upper-right
  main panel and bottom timeline.
- **Reset sections in this tab** restores the section order for the current tab.
- **Reduce motion** turns off optional UI transitions.

Layout changes save automatically in your user profile, separately from camera
projects and the app folder, so installing an update keeps them. Completed
moves, resizes and layout choices save promptly. Dolly retains a valid backup
and restores it if the latest layout file is damaged after a crash.

Panel arrangements, timeline width and horizontal position, the main panel's
tab and curve-view choices are remembered. The timeline fits its Replay or
Campaths controls, grows for Curves and adjusts to viewport changes. It starts on **Replay** in each new
session. Switching tabs or hiding the panels with F8 keeps your current view
during that session. The temporary original-curve snapshot is not saved.

Cards beside one another share a row height. Shorter cards keep space below their
controls; text and buttons keep their normal spacing. Narrow windows stack the
cards, and longer pages scroll inside the panel.

## Capture and view cameras

In-game **Capture** keeps the replay running by default. To pause after each
capture, check **Pause after capture** beside **Resume/Pause** on the timeline.
Dolly remembers your choice between sessions. It also applies to in-game
**Replace** and the capture shortcut.

Campaths lists each saved camera's arrival time, aspect ratio and bank. While
paused, use **Previous** and **Forward** to view the cameras on either side of
the current selection. **Seek here** applies the selected point on the Campaths
timeline, or seeks to the selected tick when the timeline is in Replay mode.

**Play cinematic** prepares and starts the shot. You do not need to press Play
again when preparation finishes.

## Finish a recording before editing cameras

Pausing the replay or reaching the last camera leaves a normal video recording
open. Use **Finish recording** in the main panel's footer; it stays available on
every tab while recording. Wait for **Finalizing video...** to finish saving.
Camera edits, including **Clear All**, become available again afterward.

**Stop / restore** controls playback and restoration. Use **Finish recording**
to close and save the video take.

For a shot with one attached camera, **Replay seconds** chooses the length of
that take. Recording keeps the single camera intact, so you can choose another
duration for the next take. A shot with multiple cameras keeps its authored
timing.

## Edit camera curves

Choose **Curves** on the bottom timeline, then open **Position**, **Rotation** or
**Framing**. Position has X, Y and Z; Rotation has Pitch, Yaw and Roll; Framing
controls Aspect Ratio. Switching channels keeps your selected camera and time
window. Each channel keeps its own value scale.

Click a point to select its camera. Drag the selected point vertically to change
its value, or drag the number and Ctrl+click to type. Hold **Alt** during a graph
drag to align with a nearby value on the immediately preceding or following
camera. Release to apply; **right-click** cancels an active graph or numeric
adjustment. The camera's arrival time stays the same, and each completed gesture
is one Undo step. Use **Seek here** or **Play cinematic** to check the result.

Use the mouse wheel to zoom time and right-drag to pan when no adjustment is
active. **Fit all** brings the
whole shot and its visible values back into view, including cameras on another
page of Campaths. It changes the view, not your camera values or Undo history.
New camera ranges fit the full path, including shots shorter than one second.
An accepted value outside the plot expands its value range so the key remains
accessible; deliberate time zoom and panning are retained for in-range edits.

Check **Stack graphs** to see groups together. **Graphs** chooses which groups
are visible; it replaces the group tabs while stacked. The plots share a time
ruler and playhead, with separate value scales. Choose X, Y or Z, or Pitch, Yaw
or Roll, with the buttons beside each graph title. A compact dropdown takes
their place when the panel is too narrow. At least one graph stays visible.

**Replay** and **Campaths** keep their existing navigation controls. In Curves,
open **More** for previous/next camera, Redo and FOV. The main Camera, Follow,
Bone Picker, Look and Export tabs remain available; scroll their contents when
the graphs need more space. **Stop / restore** and **Finish recording** stay
outside that scrolling area.
In a narrow Curves panel, dropdowns replace the mode and single-view group tabs;
**View** contains **Fit all** and **Update original**.

Check **Show original** to pin the current curves as a read-only snapshot. They
appear as faded dashed lines behind the solid current curves. This snapshot
stays fixed through edits and Undo; **Update original** replaces it with the
current curves. It does not restore camera values. Opening or creating another
shot clears the snapshot. It is temporary and is not saved in the project.

Curve edits work on free-camera keys while paused. For a camera attached to a
player or bone, use its attachment offsets instead. Rotation curves change the
authored rotation override; they preserve the captured angles. The desktop
Camera page uses the same Position / Rotation / Framing organization, with
stacked graphs and an original snapshot. Its path interpolation and rotation
reset controls remain available. Both editors use the normal shot save and
undo history.

## Find a player or a replay moment

A newly loaded replay starts with the full timeline in view. Dolly reads the
replay events in the background, then shows the selected player's kills in blue
and deaths in red. Hover their name for full-replay totals. Click an event marker
to seek to it; zoom in to separate markers that are close together.

To follow a player, pause the replay and use the arrows beside their name, or
click the name to select that player again. Detach a Bone Picker camera first
if one is active. Selecting a player does not change the tick or resume playback.
Replay seeks and tick steps keep that participant selected and resolve their
current hero after the seek. Choose **Fly camera** to leave Follow and compose a
fixed view. If the hero is absent, Dolly shows a status message and never moves
the camera to a guessed or stale target.

When you close the game, Dolly returns to the launcher and keeps your open shot
and editing history.

## Desktop controls

The desktop always shows Replay, Camera, Look, Export, Controls and Settings.
The sidebar has a **Controls** page for shortcuts, camera look sensitivity
and movement speed. Search for an action or its current shortcut, then click the
shortcut button and press its replacement. Review it before choosing **Save shortcut**.
A conflict leaves the existing shortcuts in place. **Clear** removes one binding;
**Reset** restores its default. The ReShade shortcut uses the same editor.

The desktop Camera table and graphs share one outer scroll region. The table
keeps its own scrolling when it has more cameras than it can show. Closed
selectors let the wheel scroll the page without changing their value; curve
plots keep wheel zoom and right-drag panning.
