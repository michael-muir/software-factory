# 0012 · Git hooks are sh shims that hand over to a standard-library launcher

Status: Accepted · Date: 2026-11-18 · Epic: E07

## Context

The hooks must run on Linux, macOS and Git for Windows, and must run the gate inside the project's environment (`gates.python_command`). Reading TOML from `sh` isn't practical. A probe on Git for Windows 2.55 found two things:
- `sh` hooks run fine through `core.hooksPath`.
- `python3` on PATH can be the Microsoft Store stub, which doesn't run Python.

## Decision

- **Shims:** `pre-commit` and `pre-push` are short POSIX `sh` scripts with LF endings. Each tries `python3`, `python` and `py` in turn, keeps the first that really is Python 3.11 or later, and `exec`s `.factory/gates/hooks/run_hook.py <hook>`. If none qualifies, the hook exits 1 with a message.
- **Launcher:** `run_hook.py` is standard library only. It imports the installed `gate.py` and uses `gate.Settings`, so config validation has a single source in the target repo. It then runs `python_command` with the gate's arguments, passes the output through, and turns any non-zero result into exit 1.
- **Switching on:** hooks are switched on per clone by `install.py hooks`, which sets the local `core.hooksPath` to `.factory/gates/hooks`. It never overwrites a foreign hooks path without `--force`, and it fixes the exec bits.
- **Exec bits:** the installer writes the shims with mode `0o755` on POSIX, and this repo commits them as `100755`.

## Consequences

- One Python file holds the hook logic, and it's testable on every OS. The `sh` part stays small enough to review by eye.
- Repos with their own hook manager (husky, pre-commit) keep it. Switching to factory hooks is an explicit, reversible choice.
- Hooks depend on a Python 3.11+ on PATH, even in TS/JS repos, as the gate does.
- `--no-verify` still bypasses hooks. CI remains the check nobody can bypass.
