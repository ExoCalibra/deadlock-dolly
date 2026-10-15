# Deadlock Dolly 0.6.51-alpha

This update puts update approval and published release highlights inside Dolly's
desktop app.

From this version, Dolly opens normally and any enabled release-information
check runs in the background. No update package downloads or installs until you
click **Update now**. Earlier versions, including 0.6.50-alpha, keep their
existing updater behavior when obtaining this release.

## Changes

- **Choose when to update.** *Before:* opening Dolly or leaving it idle could download and install updates automatically. *After:* from this version, release checks run inside the desktop app and every update requires **Update now** before a package downloads or installs.
- **A clear update notice.** *Before:* updates used a startup window or a small sidebar control. *After:* a mint-outlined notice shows your installed and available versions; **Later** leaves a header reminder without scheduling a restart.
- **Read release highlights inside Dolly.** *Before:* **What's changed** opened a browser. *After:* it smoothly expands the publisher's short Before/After notes inside the update notice, with a separate full-release link.

## Using the update notice

The notice below the main header shows your installed and available versions.
**What's changed** smoothly expands the publisher's short Before/After highlights
inside the notice. Longer highlights scroll within the panel, and **Full release
notes** opens the official release page. If short highlights are unavailable,
the full-release link remains available.

**Later** collapses the notice to an **Update available** reminder in the header
for this session. The update stays accessible through **Settings > Updates**.
**Automatically check for updates** controls background release checks only;
existing opt-outs are preserved. There is no automatic-install option or countdown.

After an accepted **Update now** click, Dolly downloads and verifies the package,
then installs and restarts when safe. If asked to save your shot, close Deadlock,
finish a recording or operation, or close a dialog, do that first and click
**Update now** again. Becoming idle does not approve an update. Interrupted
recovery of an already approved update remains automatic.

## Recording controls carried forward

The recording controls and camera-clearing repair from 0.6.50-alpha are carried
forward unchanged. Pausing the replay does not finish a normal video take. Use
**Finish recording**, wait for saving to complete, then edit or clear cameras.

## Updating

Extract the complete Windows x64 ZIP into a fresh folder and run **Dolly.exe**.
Keep **_internal** beside **Dolly.exe**. You can also obtain this release through
your installed version's updater after publication; the new approval behavior
applies once 0.6.51-alpha is running.

## Credit

Thanks to [@Hesykhia](https://github.com/Hesykhia) for the update-control feedback.
