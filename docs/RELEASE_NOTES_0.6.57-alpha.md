### Deadlock Dolly v0.6.57-alpha

**0.6.57-alpha**

A build and tooling release: nothing changes in the app itself on Windows.

- **Fresh builds work again.** *Before:* the pinned FFmpeg archive had been removed upstream, so a new checkout — or the hosted Windows build — failed with HTTP 404 while preparing the bundled encoder. *After:* the pin names a current archive of the same 8.1 LGPL line, with the same shared libraries and encoders (NVENC, AMF, Quick Sync, Media Foundation, libopenh264, FFV1).

- **The hosted Windows build works again.** *Before:* the GitHub workflow failed on runner-specific paths, a 1080-tall frame assumed by the native campaths smoke test, and an image-supplied MinGW compiler that cannot build the C++ parity sources. *After:* those checks are desktop-independent, so the workflow produces the same verified packages as a local build. This is the build path a future release can fall back on.

## What to expect

Recording, camera paths, exports, Replay seeking and update checks behave
exactly as in 0.6.56-alpha. The bundled FFmpeg is a newer build of the same
8.1 LGPL line: the encoder set, the shared DLLs and the license notices are
unchanged, and the packaged editor passes the same startup checks.

## Verification

The Windows package was built by the repository's normal local build: full
source regressions, the native suite, and a relocated packaged-editor startup
check. The same commit was also built by the GitHub workflow, which produced a
matching package from a clean checkout — the first hosted build to succeed after
the upstream archive was pruned.
