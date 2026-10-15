# In-game UI rework

The standard editor opens the reworked native interface with Camera, Follow,
Bone Picker, Look and Export tabs. Each tab uses one continuous surface.

Drag the main menu header at any time. Layout > Arrange panels enables sidebar
and timeline movement, section placement, and width/height resizing. Changes
persist separately from camera projects. Classic arrangement restores campaths
left, the menu in the middle and the timeline at the bottom. Reduce motion
disables optional transitions.

Campaths use the compact Camera / Arrive / Aspect / Bank table. Previous and
Forward select and view saved cameras around Seek here. Play cinematic prepares
the shot and starts automatically, with no extra keypress. The current official
replay-effect settling and recording preparation remain intact.

The replay timeline starts at full range for a newly loaded replay. It shows
only the selected player's kills in blue and deaths in red; hovering the name
shows full-replay totals. Selecting a player moves independent native freecam
near that player's current position without resuming, seeking or reloading the
replay. Unavailable targets are rejected. The bundled replay reader indexes the
recorded events in the background.

When an owned game session exits, the launcher returns and clears dead runtime
state while preserving the open shot and history. Compatibility contracts and
the official backend are based on 0.6.48-alpha (6b09617).
