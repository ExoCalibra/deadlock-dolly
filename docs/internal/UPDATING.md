# Published release updates

Packaged Windows builds include the updater and recovery launcher in `Dolly.exe`.
Source checkouts use the local build workflow; the packaged updater does not
install or build source checkouts.

## Moving from the older automatic updater

The **Update now** choice applies once 0.6.51-alpha or a later version is
installed. Versions through 0.6.50-alpha still use their original updater when
opened with automatic updates enabled. They can jump directly to whichever release is Latest:
for example, 0.6.50-alpha can automatically install 0.6.52-alpha without ever
opening 0.6.51-alpha. New release code cannot change the launcher that is already
running before that first upgrade.

After that transition, opening the updated **Dolly.exe** opens the editor first.
The notice appears when a newer release is available, and requires **Update
now** before downloading or installing it. When the installed version is already
Latest, there is no update notice. **Settings > Updates** remains available.

To choose the timing of the first upgrade from an older version, extract the
complete current Windows ZIP into a fresh folder and open its **Dolly.exe**.
Updating a Git checkout does not replace a separately installed Windows copy,
such as a Dolly folder on the desktop.

## For users

Open `Dolly.exe`. The desktop editor opens immediately, and any enabled update
check runs in the background. The editor runtime stays under `_internal`.

Dolly checks version and release information from GitHub's public Latest release.
When a newer release is available, a prominent notice inside the desktop app
shows the installed and available versions, with **What's changed**, **Update
now**, and **Later**. **What's changed** smoothly expands the short published
Before/After notes inside the mint-outlined notice. Longer notes scroll within
the panel; **Full release notes** opens the release page in your browser. If a
release has no supported short notes, the panel explains that and keeps the full
release link available. **Later** collapses
the notice to an **Update available** button in the header for this session; the
next launch checks again when automatic checking is enabled. The update also
remains available in **Settings > Updates**.

Every update requires **Update now**. No package downloads or installs before
that click, and there is no automatic-install option or countdown. If Dolly asks
you to save your shot, close Deadlock, finish a recording or operation, or close
an open dialog, do that first and click **Update now** again. The request is not
queued: becoming idle does not start a download, installation or restart.

After an accepted **Update now** action, Dolly downloads the Windows package,
verifies GitHub's SHA-256 digest and the file manifest, then installs and restarts
when safe. If the app becomes busy before installation, finish that work and
click **Update now** again. The replacement application is checked and reopens
at the same path, so shortcuts keep working.

**Settings > Updates** has **Check for updates** and **Automatically check for
updates**. The preference controls background release-information checks only;
turning it off keeps automatic checks off. Manual checks remain available.
Existing saved preference values are preserved. Offline, incomplete, missing-asset
and rate-limited checks leave the installed application usable. Experimental
pre-releases are ignored.

Preferences and ReShade configuration stay in `%APPDATA%/DeadlockDolly`.
Custom FFmpeg paths are saved there too. The bundled FFmpeg is found relative
to the running application, so updating or moving Dolly does not retain an old
bundled path. Export / FFmpeg runtime offers Save path and Use bundled FFmpeg.
An explicitly selected external FFmpeg or ReShade installation is not replaced.

Only files listed in the application manifest are updated. Shots, replays,
exports, logs and unknown custom files are preserved, even inside the install
folder. A managed application file that was modified locally (for example a
hand-built DLL) is backed up in the update folder and replaced. An update still
refuses to overwrite an unowned file that conflicts with a new package. Keep
edited shader presets and external tools outside the bundled runtime to avoid
those conflicts.

## Interrupted updates and recovery

The updater verifies complete backups before changing installed files, journals
the transaction, and restores the previous files on replacement or startup-check
failure. Staging and backups are kept in a `.dolly-update-*` folder inside the
Dolly folder, never beside it. After a successful update the following launch
removes that folder automatically; it is kept only while a recovery is pending
or a transaction is unfinished. A later **Update now** attempt can reuse an
already verified download instead of downloading the same release again.

Recovery of an already approved, interrupted update remains automatic. Close
Deadlock and open `Dolly.exe` again. This
self-contained launcher can recover even if the editor runtime in `_internal`
is incomplete. It starts a private copy of its embedded update worker, waits for
the old processes to close, restores journaled application files, then reopens
Dolly. No separate updater executable is installed beside Dolly.exe.

Recovery does not restore, replace or downgrade your preferences or shot files.
Keep the `.dolly-update-*` folder inside the Dolly folder and its verified
backups until recovery finishes. If the public Dolly.exe itself is damaged and
cannot start, the private `DollyUpdater.exe` in that recovery folder can be run
with `--plan plan.json --recover`; otherwise extract a fresh release into a
separate folder. Ordinary recovery needs only Dolly.exe.

## For the publisher

The in-app highlights use the same short publish description pasted into the
GitHub release body. Put the exact release version on its own line, such as
`**0.6.52-alpha**`, followed by two to four bullets in the form
`- **Short title.** *Before:* ... *After:* ...`. Wrapped lines are supported.
Use the version being published; the example is not an assigned next version.
No separate summary attachment or package download is needed to read highlights.

1. Use a new increasing version in `dolly/__init__.py` for every public build.
2. Build locally with `tools/build_windows.py`; do not build on GitHub Actions.
   The build includes Dolly.exe with embedded update/recovery, a file manifest, bundled
   FFmpeg, and matching native/Python components. Both GUI and updater smoke
   checks must pass.
3. Create a release from the intended commit on main, using a tag such as
   `v0.6.52-alpha`. Attach the generated
   `Deadlock_Dolly_0.6.52-alpha_Windows_x64.zip`,
   `Deadlock_Dolly_0.6.52-alpha_Source.zip` and `SHA256SUMS.txt`.
4. Leave GitHub's pre-release box unchecked and mark the release Latest.
   "alpha" can remain in the title and version. GitHub must expose the uploaded
   Windows asset's SHA-256 digest before the updater accepts it.
5. Experimental branches should publish as pre-releases and should not be Latest.

Selection follows GitHub's Latest designation, not branch polling. The publisher
is responsible for designating a main-branch build as Latest. A push or source
ZIP alone does not trigger an update. The updater never downloads or builds source.
Do not replace an existing version's asset to distribute changes; publish a newer
version. If a newer build regresses, publish the fix with another increasing version.
