**0.6.53-alpha**

- **Camera handles you can author.** *Before:* arrival and departure timing could only be inherited from the cameras around a key, so smooth camera moves were not adjustable. *After:* Position curves keep saved Auto, Flat, Linked and Broken handles with numeric slopes, the in-game editor uses the same compact round handles, and dragging a key or handle previews the live path and camera markers on the game screen until you release.
- **Quieter composing and cleaner takes.** *Before:* every pause and resume played Deadlock's own replay cue, and a take that played an authored path kept recording while the finished camera was held. *After:* the cue is silenced around Dolly's own pauses, **R** returns the paused view to a level horizon without editing anything, and recordings end with the shot.
- **Works on the new Deadlock build (6793).** *Before:* the game update stopped Dolly — the session was refused, the console unlocker did not support the build, and native camera was disabled. *After:* camera, capture, attach, sound, preload and the console unlocker all work on the new build. **Follow is held back on this build** and reports "not reviewed for this game update" instead of running against unverified offsets.

## Editing curve handles

Open **Curves** on the in-game timeline and choose **Position**. Each key can carry
saved arrival and departure handles. **Auto** behaves as before; **Flat**, **Linked**
and **Broken** let you set the slope into and out of a key, and fixed-time handles
keep their length when the neighbouring key moves. Handles affect **Smooth** only:
switching a curve to **Linear** or **Spline** leaves the saved handles in place and
returns to them when Smooth is selected again.

Drag a handle to change its slope or length, or Ctrl+click a value to type it.
**Alt** aligns a dragged value with a nearby neighbouring camera; **right-click**
cancels an active adjustment and release applies it as one Undo step. Handle intent
survives shot history, save and reopen, **Update view**, recapture and tick-rate
conversion, and authored handles use project format 12. Older projects keep their
existing interpolation.

While you drag keys or XYZ handles, Dolly previews the path and camera markers on
the game screen and updates the desktop graph to the temporary values. Your
viewpoint does not change, releasing saves one edit and cancelling restores the
saved path.

## Composing and takes

**R** levels the live camera: the paused view you are composing returns to a level
horizon with the shot's normal aspect and zoom. The reset is view-only, so saved
cameras, the project and Undo are untouched. **Replace** keeps its Ctrl+Alt+R chord.

Deadlock's own replay cue is silenced around Dolly's pause and resume, so composing
with the pause key is quiet. Dolly declines the game's cue rather than muting the
mixer, so other game audio is unaffected.

A take that plays an authored path now ends with the shot. Previously the camera was
held at the final position for the remainder of the recording, so exported videos
ended with seconds of still frame; the held endpoint is dropped for every path take,
matching the paired depth and POV takes.

## Deadlock build 6793

Valve's October 16 update changed every module Dolly inspects, so the reviewed data
was re-derived for it: camera anchors and curve data, the particle and confetti
table, the sound hooks, the player-scene pairing, the editing baseline and the
console unlocker, whose server patch is rebuilt for the new build. The native bridge
accepts the new build, and automatic preload verification uses the new
resourcesystem module.

**Follow is held back on 6793.** Its stock camera rig still needs a live check of
whether the new build changed the game's own aim slide, so the feature reports "not
reviewed for this game update" and stays off until that review is done. Everything
else in the replay editor, including hiding the game HUD and the hero health panel
while Dolly's camera owns the view, works normally.

## Updating and release assets

Extract the complete **Deadlock_Dolly_0.6.53-alpha_Windows_x64.zip** into a fresh
folder and run **Dolly.exe**, keeping **_internal** beside it. Existing installed
versions can use Dolly's updater after publication; **Update now** is required
before downloading or installing.

The publisher uploads the locally built Windows ZIP,
**Deadlock_Dolly_0.6.53-alpha_Source.zip** and **SHA256SUMS.txt** from the same
completed build. Use tag **v0.6.53-alpha** on the tested main-branch commit and
mark the public release **Latest**, with GitHub's pre-release box unchecked.
Publishing remains a manual step; pushing the source does not publish a release.

See the [in-game editor guide](UI_REWORK.md) for the controls and the
[changelog](CHANGELOG.md) for the complete change list. This release does not
extend the existing Players/Depth export guarantees.
