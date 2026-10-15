# In-game UI rework

The standard editor opens the reworked native interface with Camera, Follow,
Bone Picker, Look and Export tabs. Each tab uses one continuous surface.
The established Dolly launch, Steam checks and replay startup sequence are
retained.

F8 opens or closes the main menu, campaths sidebar and timeline together. Opening
them again restores their positions and sizes. Camera path guides and the framing
grid remain available while flying with the panels closed. F9 still returns to
Deadlock's own replay controls.

Starting a cinematic uses the existing flight handoff and hides the workspace;
F8 can show all three panels again during playback without interrupting the
shot. The separate, temporary Hide UI checkbox is no longer needed.

Drag the main menu or campaths header at any time; both show the four-arrow move
cursor when hovered or dragged. Layout > Arrange panels enables timeline
movement, section placement, and width/height resizing. Changes
persist separately from camera projects. Classic arrangement restores campaths
left, the menu in the middle and the timeline at the bottom. Reduce motion
disables optional transitions.

Campaths use the compact Camera / Arrive / Aspect / Bank table. Previous and
Forward select and view saved cameras around Seek here. Play cinematic prepares
the shot and starts automatically, with no extra keypress. The current official
replay-effect settling and recording preparation remain intact.

The timeline's **Pause after capture** checkbox sits beside Resume/Pause. Leave
it off to keep the replay running when capturing cameras, or turn it on to pause
after each capture. The choice is remembered between sessions and applies to
the in-game Capture/Replace buttons and capture shortcut.

The replay timeline starts at full range for a newly loaded replay. It shows
only the selected player's kills in blue and deaths in red; hovering the name
shows full-replay totals. Selecting a player moves independent native freecam
near that player's current position without resuming, seeking or reloading the
replay. Unavailable targets are rejected. The bundled replay reader indexes the
recorded events in the background.
If a hero is absent or their view is still settling, Dolly keeps the camera and
replay unchanged and shows a status notice.

When an owned game session exits, the launcher returns and clears dead runtime
state while preserving the open shot and history. Compatibility contracts and
the official backend are based on 0.6.48-alpha (6b09617).
