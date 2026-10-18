### Deadlock Dolly v0.6.56-alpha

**0.6.56-alpha**

- **Seek to the camera you selected.** *Before:* selecting Camera 2 and pressing the Replay timeline's middle seek button could leave you at the current tick and view. *After:* **Seek camera** moves to the selected camera's saved replay time and full saved view, including cameras later in the shot.

- **Clearer seek controls.** *Before:* Replay and Campaths both called the middle button **Seek here**, despite targeting different things. *After:* Replay uses **Seek camera**, Campaths keeps **Seek here** for the shot cursor, and the replay tick controls still seek the tick you choose.

## Seeking saved cameras

Pause the replay, select a saved camera, then press **Seek camera** in Dolly's
Replay timeline. This uses the camera's authored time and saved position,
rotation and framing. Selecting a row by itself still selects it; viewing a
camera with a double-click or Previous/Forward still applies its view at the
current replay moment.

The request is checked against the current camera list and active operation.
Once accepted, its shot and target time are captured together so a later edit
cannot redirect the queued seek. The selected camera remains available when
you browse another page of a long camera list.

The saved-camera action uses Dolly's existing guarded seek path. Replay
identity, cancellation, reconstruction and compatibility checks remain in
place. Automated regressions exercise the actual in-game button, native event
transport and saved-target dispatch, and detect the previous routing mistake.

## Updating and release assets

Extract the complete **Deadlock_Dolly_0.6.56-alpha_Windows_x64.zip** into a fresh
folder and run **Dolly.exe**, keeping **_internal** beside it. Installed versions
can use **Update now** after publication.

Attach only the Windows ZIP to the release. The Source ZIP and checksum files
remain local build records; developers can use the repository or release tag.
Use **v0.6.56-alpha** on the tested main-branch commit and mark the public release
**Latest**, with GitHub's pre-release box unchecked. Publishing remains manual.
