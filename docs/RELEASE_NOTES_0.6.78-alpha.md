### Deadlock Dolly v0.6.78-alpha

**0.6.78-alpha**

- **Players layer captures survive a busy scratch drive.** *Before:* a 1440p Players export could stop with "missed shot frames" after a brief write stall, and lowering the FPS or raising the export speed did not help. *After:* the fixed-step capture waits for the scratch drive and keeps every frame, so the export continues instead of failing.

- **A real stop names the scratch drive.** *Before:* every writer stall was reported as a missed shot cadence. *After:* a genuine write timeout says the scratch drive could not keep up and suggests a faster scratch folder or a lower FPS. Still captures keep using the aligned settled frame.
