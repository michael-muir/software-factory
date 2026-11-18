# 0007 · The gate is one standard-library file in the kit, reading config itself

Status: Accepted · Date: 2026-11-17 · Epic: E05

## Context

The product owner put the gate in the kit, at `.factory/gates/gate.py`, so every repo carries its own copy, installed and upgraded by `install.py`. Target repos do not contain `factory_installer`, so the gate cannot import it. The gate still needs the `gates.*` settings from `.agentic/config.toml`, which `factory_installer.config_schema` defines.

## Decision

- **One file.** `gate.py` is a single module that imports only the standard library. It is easy to read, copy, run and upgrade, and the installer treats it like any other kit file.
- **The gate reads config itself.** It parses `.agentic/config.toml` with `tomllib` and reads only `gates.*`. Missing keys fall back to defaults. A wrong type or out-of-range value makes the gate exit 2, naming the key.
- **Defaults are mirrored and tested.** The gate keeps its own copy of the `gates.*` defaults. A test asserts they equal `config_schema`'s, so the two cannot drift silently.
- **Full validation stays in `install.py check`.** The gate does not re-implement every rule; it checks only the keys it uses.
- **Typing and tests:** `kit/.factory/gates` goes on `mypy_path` and on pytest's `pythonpath`, so tests `import gate` and mypy checks it strictly.

## Consequences

- A repo can run its gate with nothing but Python 3.11+, offline.
- Gate fixes reach existing repos through `install.py` upgrades. Hand edits to `gate.py` in a repo show up as `kept`, with a `.factory-new` beside them (ADR 0005, ADR 0006).
- If the file grows past easy reading, a later ADR can split it into a stdlib package under `.factory/gates/`.
