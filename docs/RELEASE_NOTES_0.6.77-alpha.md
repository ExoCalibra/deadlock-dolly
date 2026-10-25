### Deadlock Dolly v0.6.77-alpha

**0.6.77-alpha**

- **Game updates can sometimes skip a new Dolly download.** *Before:* every Deadlock update broke Native camera until a matching Dolly build shipped. *After:* Dolly fetches small reviewed build definitions from the project's GitHub page in the background and accepts a client-only update from that file. A changed `server.dll` still needs a release because the cvar unlocker is built from it.

- **Support is additive and offline-safe.** *Before:* build support was fixed at release time. *After:* published definitions can only add newly reviewed builds, never remove or override what shipped in the release, and a missing, failed or malformed download leaves the installed build behaving exactly as before.

- **The startup build check reports the merged result.** *Before:* **Check game build** only knew about the installed release. *After:* it also reports support that arrived through published definitions, including the editing-configuration pins and whether the cvar unlocker still needs a matching release.
