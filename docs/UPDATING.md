# Updating Dolly and recovering an update

[Documentation](README.md) · [User guide](USER_GUIDE.md)

This guide applies to the packaged Windows application. Source checkouts use
the [source build workflow](BUILDING.md); the updater does not build or update
a Git checkout.

## Checking for an update

Open **Dolly.exe**. The editor opens immediately, and an enabled update check
runs in the background. **Settings → Updates** provides **Check for updates**
and **Automatically check for updates**. That preference controls background
checks for release information; manual checks remain available when it is off.

When GitHub's published Latest release is newer, the notice shows the installed
and available versions, **What's changed**, **Update now** and **Later**.
**What's changed** expands the short published notes; **Full release notes**
opens the release page. Older Dolly versions may not recognize a release's
short-note format, so use the full release link if the highlights are empty.

**Later** collapses the notice to **Update available** for that session. The
update stays available under Settings, and the next launch checks again when
background checks are enabled. Offline or rate-limited checks leave the
installed app usable. Experimental pre-releases are ignored.

## Installing an update

1. Save your shot and finish any recording or operation. Close Deadlock and any
   open Dolly dialog if the app requests it.
2. Click **Update now**. Every new update requires this action; enabling
   background checks does not authorize downloading or installing an update.
3. Dolly downloads the Windows package, verifies GitHub's SHA-256 digest and
   the file manifest, then installs and reopens at the same path.

If an update is blocked by unsaved work or the app becomes busy before
installation, finish that work and click **Update now** again. The request is
not queued for later installation.

Preferences, custom shortcuts and external tool paths stay in
`%APPDATA%/DeadlockDolly`. Shots, replays, exports, logs and unknown custom files
are preserved. Only application files in the manifest are replaced. A modified
managed file, such as a custom native DLL, is backed up and replaced; an unowned
file conflicting with a new package blocks the update. Keep custom tools and
edited shader presets outside the bundled runtime.

## Recovering an interrupted update

Close Deadlock and open **Dolly.exe** again. The self-contained launcher can
recover an already approved update even if `_internal` is incomplete. It uses
the transaction's verified backups, restores the journaled application files
and reopens Dolly. Recovery preserves your preferences and shot files.

Keep the `.dolly-update-*` folder inside the Dolly folder until recovery
finishes. It contains the transaction plan and backups; a following launch
removes it after success. A later approved attempt can reuse a verified
download.

If **Dolly.exe** itself cannot start, extract the complete current Windows ZIP
into a separate folder. For advanced recovery, an intact private
`DollyUpdater.exe` in the transaction folder accepts `--plan plan.json --recover`
when run from that folder. Keep the existing installation and logs available
when asking for help.

Update recovery is separate from restoring Deadlock's session configuration.
For an interrupted editing session, close Deadlock and use **File → Recover
game configuration**; see the [user guide](USER_GUIDE.md).

## First upgrade from 0.6.50-alpha or earlier

Those versions retain their original automatic updater. New release code cannot
change the old launcher before its first upgrade. To choose the upgrade timing,
extract a complete current Windows ZIP into a fresh folder and run its
**Dolly.exe**. From 0.6.51-alpha onward, new updates require **Update now**.

Updating the repository does not replace a separate portable installation,
such as a Dolly folder on your desktop.
