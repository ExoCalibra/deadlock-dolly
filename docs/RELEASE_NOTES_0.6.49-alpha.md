# Deadlock Dolly 0.6.49-alpha

A refreshed in-game workspace, with the UI rework contributed by
[@tbhtho](https://github.com/tbhtho) in [PR #20](https://github.com/cravvnn/deadlock-dolly/pull/20).

## Changes

- **A clearer editing workspace.** *Before:* camera and shot controls shared the older panel layout. *After:* Camera, Follow, Bone Picker, Look and Export have dedicated tabs, alongside a compact Campaths list and replay timeline. The timeline shows the selected player's kills in blue and deaths in red.
- **Panels that fit your screen.** *Before:* hiding Dolly could leave other panels visible. *After:* F8 hides or restores the main panel, Campaths and timeline together, while keeping path guides and the framing grid available. Drag either the main panel or Campaths header at any time; use **Layout > Arrange panels** for resizing and timeline placement. Your layout is remembered, and **Classic arrangement** restores the standard arrangement.
- **Choose what Capture does to playback.** *Before:* capturing a camera paused the replay. *After:* the in-game Capture keeps playback running by default. Enable **Pause after capture**, beside Resume/Pause on the timeline, to pause after each capture instead. The choice is saved and also applies to in-game Replace and the capture shortcut.
- **Player selection moves the free camera.** *Before:* selecting a hero could fail with an availability error. *After:* the paused replay's timeline selector checks the player's current position before moving freecam near them. If the hero is absent or their view is still settling, Dolly leaves the camera and replay unchanged and shows a status notice.
- **Support for Deadlock build 6785.** Updated compatibility for the October 14 game update.
- **Replay preparation handles a brief pause delay.** *Before:* a temporary difference between the replay and camera view could stop preparation with "The replay did not pause at the shot start during effect settling." *After:* Dolly lets the pause settle within the existing time limit, then checks the exact shot start before recording. A wrong starting tick still stops the export, and Stop still cancels preparation.

The hideout's **Loading shaders** notice also has clearer text and spacing, centered in the lower part of the screen. F9 still opens Deadlock's own replay controls, and Dolly retains its established startup sequence.

## Known limitations

Some replay characters and scenery can still appear dark or black; this separate issue remains unresolved. This update does not extend the existing Players/Depth export guarantees. Other machines, replays and long recordings may behave differently from the bounded local checks.

## Updating

Extract the Windows x64 ZIP into a fresh folder and run **Dolly.exe**, or use Dolly's updater once this release is published. Python, Tcl/Tk and the encoder are bundled.
