# 0.6.49-alpha walkthrough

Historical walkthrough for 0.6.49-alpha. Use the
[current in-game editor guide](UI_REWORK.md) for today's controls and
[documentation index](README.md) for the complete workflow.

About three minutes. Bracketed lines are screen directions, not narration.

[Open the in-game editor and move through the five tabs.]

This update brings a new in-game UI to Deadlock Dolly, contributed by @tbhtho
on GitHub. Camera, Follow, Bone Picker, Look and Export now have their own
tabs. Your saved cameras are on the left in Campaths, with the replay timeline
and playback controls underneath.

[Drag the main panel and Campaths by their headers, then open Layout.]

You can grab either panel by its header and move it whenever you need more
room. The four-arrow cursor shows where to drag. Turn on Arrange panels to
resize the panels, move the timeline or rearrange sections inside a tab.
Dolly saves your layout for next time. Classic arrangement puts the panels
back in their usual places, and Reduce motion turns off the optional
transitions.

[Capture a camera while the replay plays. Enable Pause after capture and capture again.]

Capture keeps the replay running by default, so you can collect camera
positions while the action continues. If you prefer to stop after each one,
check Pause after capture beside Resume on the timeline. Dolly remembers
that choice. It also applies to Replace and the capture shortcut.

[Pause the replay. Change the selected player, then hover their name and an event marker.]

The player arrows now bring the free camera near the hero you choose while
the replay is paused. You can click the name to return to that player too.
If a Bone Picker camera is attached, detach it first. If the hero is missing
at that moment, or their view is still settling, Dolly keeps the camera
where it is and shows a message.

Blue marks on the timeline show that player's kills, and red marks show
their deaths. Hover their name for the full-replay totals. Click an event
to seek to it, and zoom in when the marks are close together.

[Enable the path guides and grid while composing. Press F8 twice, then F9.]

F8 hides all three Dolly panels together. Your enabled guides and grid can
stay on screen while you compose the shot; path guides still hide during
playback. Press F8 again to bring the panels back in the same places.
F9 still opens Deadlock's own replay controls.

[Select a short camera path and use Play cinematic.]

Play cinematic prepares the shot and starts it automatically. You do not
need a second keypress. The panels hide as the shot starts, and F8 can
bring them back while it keeps playing.

[Show Export and a short Color export.]

This version also includes support for Deadlock build 6785 and a fix for
an early failure during replay preparation. Dolly now lets the pause settle
before checking the exact shot start and beginning the recording. You can
still cancel preparation with Stop.

[End on a composed shot with the panels hidden.]

Thanks to @tbhtho for the UI and saved layouts, @s34532 for the custom
particle effects, and @Hesykhia for high-resolution screenshot export.
The download and full notes are linked below. If you run into a problem,
include your Dolly version and diagnostics ZIP so we can look into it.
