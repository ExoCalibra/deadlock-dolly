# Deadlock Dolly 0.6.41-alpha

Two fixes: updates now show a clear progress window instead of flashing, and a failed layered export (Players + Depth) no longer leaves Dolly unresponsive.

## Changes

- **You can see Dolly updating.** *Before:* when an update installed and rebuilt, the editor closed and the file replacement happened with no window, then the relaunch briefly painted a window — which looked like random flashing and left users unsure whether anything was happening. *After:* one steady "Updating Dolly" window stays on screen through the install, verification and relaunch, showing what step is running. If the update fails, that same window explains the problem and stays until you close it, instead of a separate pop-up.
- **A failed Players/Depth export no longer freezes Dolly.** *Before:* requesting a Players layer and a Depth layer together when the game drive was short on space could leave the main window unresponsive (needing Task Manager), and the error could sit behind the game. *After:* Dolly shows a single dialog, keeps the window clickable, and returns to a clean state so you can free space and try again. A preflight failure such as the disk-space check no longer runs recording recovery.
- **Clearer Players disk-space message.** *Before:* "Players capture needs approximately X GiB … only Y GiB is available." *After:* the message also tells you how much it is short by and reminds you that the Players layer stores every frame uncompressed, so it is clear what to free, shorten or lower.

## Validation

The full Python suite passes: 2,003 tests, 22 skipped. One bounded local session requested Players + Depth on a real owned development session with the game drive at about 30.7 GiB free. It produced exactly one dialog ("needs about 49.5 GiB … short by about 19.8 GiB"), the window stayed responsive, the failed attempt left the recorder idle and the layered state cleared, and the session exited with all configuration restored and no leftover deployment. The update progress window and its hidden install check were verified offline (window shows progress, failure stays on screen, the post-install check no longer paints a window).

## Limits

The export fix covers failing the layered attempt cleanly; a real Players/Depth capture still needs the disk headroom the message reports. The update window shows the current step rather than a byte-accurate progress bar, since the file replacement itself is quick and most of the time is unzipping and the post-install startup check.

## Updating

Extract the Windows ZIP into a fresh folder and run Dolly.exe, or let Dolly update itself. Keep the previous installation until your workflow is checked. Python and Tcl/Tk are bundled.