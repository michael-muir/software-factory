# 0002 · Installer runs from a clone, standard library only

Status: Accepted · Date: 2026-11-17 · Epic: E01

## Context

The product owner chose `python install.py` from a clone or download, with no PyPI package in v0. The core scripts must also be stdlib-only on Python 3.11+. The installer still needs structure that can be tested, and it must refuse older Pythons with a clear message (AC-03), even ones that cannot parse modern syntax.

## Decision

- `install.py` at the repo root is a shim of a few lines. It uses only syntax that old Pythons parse (no f-strings, no annotations, no `match`).
  - It checks `sys.version_info >= (3, 11)` before anything else.
  - If the check passes, it puts the repo root on `sys.path` and calls `factory_installer.cli.main()`.
- The logic lives in the `factory_installer` package. It imports nothing outside the standard library. TOML is read with `tomllib`, and the default `config.toml` is rendered as text, because the standard library cannot write TOML.
- The kit content lives in `kit/`, which mirrors the target layout. `kit/VERSION` is the single source of the kit version, and a test asserts that `pyproject.toml` agrees with it.
- `uv` manages only the development tools (ruff, mypy, pytest, coverage, mutmut). Running the installer never needs `uv`.

## Consequences

- Anyone with Python 3.11+ and a copy of this repo can install the kit, offline.
- Publishing to PyPI later (`uvx software-factory install`) only needs packaging around `factory_installer` and `kit/`. The code itself does not change.
- A test runs the installer under `python -I -S`. Any third-party import fails that test, which is what holds the stdlib-only rule in place.
