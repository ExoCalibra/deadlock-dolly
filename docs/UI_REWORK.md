# In-game editor

The main panel has five tabs: **Camera**, **Follow**, **Bone Picker**, **Look**
and **Export**. Your saved cameras are in **Campaths** on the left, with the
timeline and playback controls below.

The UI rework and saved layouts were contributed by
[@tbhtho](https://github.com/tbhtho).

## Show or hide the panels

Press **F8** to hide the main panel, Campaths and the timeline together. Press it
again to bring them back in the same positions and sizes. Path guides and the
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
  sections within a tab.
- **Classic arrangement** puts Campaths on the left, the main panel in the
  middle and the timeline at the bottom.
- **Reset sections in this tab** restores the section order for the current tab.
- **Reduce motion** turns off optional UI transitions.

Layout changes save automatically, separately from your camera projects.

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

## Find a player or a replay moment

A newly loaded replay starts with the full timeline in view. Dolly reads the
replay events in the background, then shows the selected player's kills in blue
and deaths in red. Hover their name for full-replay totals. Click an event marker
to seek to it; zoom in to separate markers that are close together.

To move the free camera near a player, pause the replay and use the arrows beside
their name, or click the name to return to that player. Detach a Bone Picker
camera first if one is active. This moves the free camera without changing the
replay tick or resuming playback. If the hero is absent or their view is still
settling, Dolly leaves the camera where it is and shows a status message.

When you close the game, Dolly returns to the launcher and keeps your open shot
and editing history.
