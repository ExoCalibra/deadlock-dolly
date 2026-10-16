# Development checks

Choose checks for the behavior being changed, then run its neighboring consumers.
Run from the product checkout root and select its qualified Python environment
explicitly. For the standard setup in [BUILDING.md](../BUILDING.md):

```powershell
$py = '.\.venv\Scripts\python.exe'
```

If a linked worktree uses a shared environment, set `$py` to the interpreter
identified by the active project instructions and keep the product worktree as
the current directory. For example, update-flow checks are:

```powershell
& $py -m unittest discover -s tests -p 'test_update*.py' -q
& $py -m unittest discover -s tests -p 'test_release_launcher.py' -q
& $py -m unittest discover -s tests -p 'test_release_notes.py' -q
```

These are the update-flow checks, not a replacement release command. For another
component, substitute its owning test file and include consumers of the changed
contract. Tests import sibling fixtures by bare names: do not use `-t .`.

| Changed area | Include in the selected checks |
|---|---|
| Update discovery, consent or worker | Updater, consent, notice, release launcher and notes; settings when persistence changes |
| Desktop component | Component tests plus its real GUI adapter, layout/theme and input consumers affected by the change |
| Controller, path, settings or shared test fixture | Owning tests during iteration; full source suite before completing a shared-contract change |
| Launch, configuration or recovery | Launcher, graphics profiles, session cleanup/recovery, atomic files and relevant controller consumers |
| Native compatibility, protocol or packaging | Generated compatibility, Python/native agreement, launcher and package tests; affected native targets when their inputs change |
| Documentation only | Changed commands/links and source-export membership; runtime tests only if executable behavior is affected |

If the affected consumers are unclear, run the full source suite. Search fixture
imports before changing a helper shared by other test files. Preserve independent
transport, lifecycle, platform and packaging checks even when their assertions
look similar. Reuse a passing result only while its relevant source, fixtures,
generated inputs and environment remain unchanged; record that identity.

The full source check for shared or unclear changes is:

```powershell
& $py -m unittest discover -s tests -q
```

For a separately requested Windows release, retain the full local source/native
and packaged-executable qualification in the normal builder. It includes the
full source suite, so reuse that proof when its relevant inputs match. Its gates
and forced native relink remain unchanged. Use the intended release version and
outputs, preserving published artifacts. No new skip flags or hosted builds are
part of this workflow.

```powershell
& $py tools/build_windows.py
```

For new regressions, name the observable contract, a credible failing change,
and why existing proof misses it. Prefer one strong owning test with independent
expected values. Before consolidating, carry every unique case into its keeper
and demonstrate that the keeper fails for the intended regression. Avoid new
production seams used only by tests. Use virtual clocks for simulated waiting;
keep real timing, process and filesystem proof in the tests that own it.

Record elapsed time for changed suites and preserve failed attempts. Do not add
retries, broaden mocks or remove failure checks merely to get a passing run.
