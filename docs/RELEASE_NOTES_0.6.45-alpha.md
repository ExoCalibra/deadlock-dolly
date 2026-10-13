# Deadlock Dolly 0.6.45-alpha

Fixes an export startup failure when Deadlock loses focus while recording is being prepared.

## Changes

- **Reliable export startup.** *Before:* switching away from Deadlock or using Dolly's desktop controls could block the first recording frame and produce a misleading DirectX 11 error. *After:* recording starts from available game frames even when another window has focus.
- **Clearer recording errors.** *Before:* a timeout waiting for the first frame looked like missing DirectX 11. *After:* the message explains the frame timeout and suggests restoring the game window, retrying, and exporting diagnostics if it persists.

## Validation

The regression reproduces the first-frame timeout on the old code and writes frames successfully with the fix using a synthetic DX11 WARP game window. It also checks camera handoff, subsequent focus changes and session disconnect. All 28 enabled native checks pass; the hardware encoder stress test is excluded. The full Python suite passes: 2,014 tests, 22 skipped.

## Limits

The fix has been verified locally with synthetic rendering and recording. The affected user's export still needs confirmation on the updated build. A minimized or stalled game that stops rendering can still time out.

## Updating

Extract the Windows ZIP into a fresh folder and run Dolly.exe, or use Dolly's updater once the release is published. Keep the previous installation until your workflow is checked. Python and Tcl/Tk are bundled.
