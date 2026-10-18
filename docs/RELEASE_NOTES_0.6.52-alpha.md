**0.6.52-alpha**

- **A calmer desktop workspace.** *Before:* tools could be hidden behind an editor-mode switch, shortcut editing was buried in Settings, and tabs and scrolling felt uneven. *After:* matte panels, close-fitting tab outlines, precision scrolling and a dedicated Controls page keep Camera, Look and the shot timeline easy to reach.
- **Camera curves in one place.** *Before:* separate graphs and stale view ranges made it easy to lose a camera or an adjustment. *After:* Position, Rotation and Framing share a workspace with Stack graphs and Show original; short paths fit their actual duration, Alt aligns nearby camera values, and right-click cancels an active in-game adjustment.
- **In-game panels that fit.** *Before:* fractional speeds and recording-source names could clip, and saved timeline heights could leave empty space. *After:* dropdowns stay readable, cards reflow and scroll, and the timeline fits Replay or Campaths, grows for Curves and stays near the bottom of the screen. Layout saves retain a recoverable backup.
- **Clearer replay startup and navigation.** *Before:* player selection could be lost through seeks, and the loading notice looked separate from Dolly. *After:* the timeline keeps the chosen participant through seeks and tick steps, while a Dolly-branded loading card sits at the top center of the game's loading screen without a duplicate native popup.

Built on the in-game UI rework contributed by [@tbhtho](https://github.com/tbhtho) in [PR #20](https://github.com/cravvnn/deadlock-dolly/pull/20).

## Editing curves

Open **Curves** on the in-game timeline, then choose **Position**, **Rotation**
or **Framing**. **Stack graphs** puts groups on one time ruler; **Show original**
pins a faded snapshot behind current edits. **Update original** replaces that
snapshot. It is temporary and does not restore or overwrite camera values.

Drag a selected key vertically, or Ctrl+click its value to type. Holding **Alt**
while dragging aligns with a nearby value on the immediately preceding or
following camera. **Right-click** cancels an active graph or numeric adjustment;
release applies it as one Undo step. Arrival times stay unchanged. Wheel zoom
and right-drag panning remain available when no adjustment is active.

New camera ranges fit the complete path, including paths shorter than one
second. Accepted values outside the visible plot expand its value range while
keeping the authored value. **Fit all** brings the full in-game graph back into
view. The desktop Camera page uses the same Position / Rotation / Framing
organization, with stacked graphs and an original snapshot.

## Panels, controls and replay navigation

The desktop **Controls** page records keyboard and mouse shortcuts, shows
conflicts, and offers **Clear** and **Reset** for individual actions. Existing
bindings carry over. Camera, Look and the shot timeline remain available without
a Full editor switch.

The in-game timeline starts on **Replay** in each new session. Replay and
Campaths fit their active controls with normal bottom padding; Curves grows for
its graphs. Narrow layouts use compact controls and **More** for extra actions.
Outside **Layout > Arrange panels**, the timeline stays just above the bottom
of the screen, retaining its custom width and horizontal position. Arrange
allows temporary free placement; leaving it reattaches the timeline to the
bottom. Main-panel pages scroll as needed, and Export cards reflow to keep
recording-source names readable.

The Replay player selector retains the chosen participant through seeks and
tick steps, resolving their current hero after the replay settles. **Fly camera**
returns to a fixed view. An unavailable hero produces a status message instead
of moving the camera to a guessed target.

Completed layout changes save with a checked backup outside the app folder.
The loading screen now carries a top-center **Deadlock Dolly** notice through
the game's Panorama UI, without the separate native loading popup. Replay
startup and automatic loading keep their existing checks.

## Playback fixes carried with this update

Recording a single attached camera keeps its endpoint local to the take, so the
next take can use a different **Replay seconds** duration without adding a
camera to the saved shot. Pause transitions also check replay continuity before
rejecting a brief backward settling tick; actual seeks and replay changes still
stop playback.

See the [in-game editor guide](UI_REWORK.md) for the controls and the
[changelog](CHANGELOG.md) for the complete change list. This release does not
extend the existing Players/Depth export guarantees.

## Updating and release assets

Extract the complete **Deadlock_Dolly_0.6.52-alpha_Windows_x64.zip** into a fresh
folder and run **Dolly.exe**, keeping **_internal** beside it. Existing installed
versions can use Dolly's updater after publication; **Update now** is required
before downloading or installing.

The publisher uploads the locally built Windows ZIP,
**Deadlock_Dolly_0.6.52-alpha_Source.zip** and **SHA256SUMS.txt** from the same
completed build. Use tag **v0.6.52-alpha** on the tested main-branch commit and
mark the public release **Latest**, with GitHub's pre-release box unchecked.
Publishing remains a manual step; pushing the source does not publish a release.
