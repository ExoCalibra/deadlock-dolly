### Deadlock Dolly v0.6.70-alpha

**0.6.70-alpha**

- **Old replays no longer crash on seek.** *Before:* seeking a replay recorded before Deadlock build 6801 could crash the game and leave Dolly showing "The console is disconnected. Use Connect after Deadlock finishes loading." *After:* Dolly refuses the seek before sending it, keeps the game running, and explains that the replay is from an older build. Use a replay recorded on 6812 or 6813, or play the old replay from the start without seeking.

- **Crashes during a seek are named as crashes.** *Before:* when the game died just as the console socket dropped, Dolly blamed the console. *After:* Dolly waits briefly for the game process and reports the actual exit code and crash dump module/offset.
