# 0015 · One standard-library state module serves the CLI, the gate and the installer

Status: Accepted · Date: 2026-11-18 · Epic: E02

## Context

Three places must validate state files with identical results:
- `state.py check`
- the gate, before it runs any check
- `install.py check`

The gate and `state.py` run inside target repos, from `.factory/`. The installer runs from the clone (ADR 0002), where the kit source is `kit/.factory/`. E07 learned that code installed into targets can't import `factory_installer`.

## Decision

- **One module:** a single file, `.factory/state/state.py`, holds the schemas, the parser, the validator, the writer and the CLI (`main`). It's standard library only.
- **The gate** loads `<root>/.factory/state/state.py` with `importlib` and calls `validate(root)` before running any check. If the file isn't there (a kit older than E02), the gate skips validation.
- **`install.py check`** loads the **kit source's** `state.py` (`kit/.factory/state/state.py`) the same way, then validates the target. This is the pattern E07's pipelines use to load the kit's `gate.py`.
- **Problems** are values, `Problem(path, where, message)`, rendered everywhere as `<file>: <key or heading>: <problem>`.

## Consequences

- There's one validator, so `state.py`, the gate and the installer can't drift apart.
- The gate stays a single file with no new import-time dependency. A missing `state.py` degrades gracefully.
- `state.py` is a kit file under the ADR 0005 upgrade rules. Upgrading it changes validation in every repo on its next install, as intended.
