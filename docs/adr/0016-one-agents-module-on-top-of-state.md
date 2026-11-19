# 0016 · One standard-library agents module, built on the state module

Status: Accepted · Date: 2026-11-18 · Epic: E03

## Context

E03 needs four things:
- an agent file validator
- an allow/deny checker
- test lock records
- a Claude Code hook

Three places validate, as with state (ADR 0015): the module's own CLI, the gate and `install.py check`. Agent files use the same TOML front matter as state files (ADR 0014). Lock records name tasks, which `state.py` already finds and validates.

The options:
1. **A new module with its own parser.** Two parsers could drift.
2. **Add everything to `state.py`.** It's nearly 800 lines already, and roles aren't state.
3. **A new module that reuses `state.py`'s parser, `Problem` type, root finder and atomic writer.**

## Decision

Option 3:
- **One module:** `.factory/agents/agents.py` holds the agent schema, the validator, the checker, the locks, the hook and the CLI. It's standard library only.
- **Reuse:** it loads its sibling `../state/state.py` with `importlib`, under the module name `factory_state`, and reuses `parse`, `Problem`, `find_root` and `_write`. If `state.py` is missing, `agents.py` exits 2.
- **The gate** loads `<root>/.factory/agents/agents.py` as `factory_agents` after it validates state. It calls `validate(root)`, where problems mean exit 2, then `verify_locks(root)`, where problems mean exit 1. If the file isn't there (a kit older than E03), both steps are skipped.
- **`install.py check`** loads the kit source's `agents.py` and validates the target, as it does for `state.py`.

## Consequences

- One front-matter parser serves both kinds of file, so their rules can't drift.
- `agents.py` depends on `state.py`. The two always ship together in the kit, and a test pins the dependency.
- The gate stays a single file. It gains two calls and no imports.
- `_write` is private to `state.py` but used across modules. It's a kit-internal contract, and a test calls it through `agents.py` so a rename fails loudly.
