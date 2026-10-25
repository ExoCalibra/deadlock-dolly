### Deadlock Dolly v0.6.68-alpha

**0.6.68-alpha**

- **Works with Deadlock build 6813.** *Before:* the game updated to 6813 and Dolly could not start an editing session on it. *After:* Dolly recognizes 6813, initializes the unlocker, loads a replay and opens the paused camera editor normally.

- **Deadlock crashes are reported as crashes.** *Before:* when Deadlock crashed while Dolly was running a console command, Dolly showed "The console is disconnected. Use Connect after Deadlock finishes loading." *After:* Dolly reports the game's exit code and says the selected replay may be incompatible with the installed build, then points to a replay recorded on this build.

- **Crash details are in the error.** *Before:* finding the faulting module and offset required exporting diagnostics and reading the crash dump separately. *After:* the error names the newest crash dump's faulting module, offset and read address.
