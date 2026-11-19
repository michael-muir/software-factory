# 0022 · Skills are validated by agents.py, with a YAML subset reader

Status: Accepted · Date: 2026-11-19 · Epic: E10

## Context

E10 adds `.factory/skills/<name>/SKILL.md` files in the Agent Skills format: YAML front matter, then Markdown. The spec needs them checked in three places, the same three as roles: a CLI, the gate (exit 2) and `install.py check`. The kit is standard library only, and Python's standard library has no YAML parser.

Where the validation could live:
1. **A new kit module,** `skills.py`, with its own loading in the gate and the installer. That's a third copy of the module-loading code.
2. **`agents.py`,** whose `validate(root)` is already called by the gate and `install.py check`, and whose `check` command is already the roles' CLI.

How the YAML could be read:
1. **Vendor a YAML parser into the kit.** That's large, and it breaks "standard library only" in spirit.
2. **Read only the subset the spec allows,** and report anything else.

## Decision

- **`agents.py` validates skills.** `validate(root)` returns role problems, lock-record problems and skill problems together. `agents.py check` is the skills' CLI too. The gate and the installer don't change, since they already call `validate`.
- **A YAML subset reader** in `agents.py`. It reads front matter between `---` lines, made of `key: value` lines with plain or quoted strings, plus `metadata` as a one-level map of indented lines. Comments and blank lines are skipped. Any other YAML is reported as `front matter: unsupported YAML on line N`, never parsed loosely.
- **The validator applies the Agent Skills rules only,** to every skill in a repo. The factory's own conventions for its kit skills are tests, as for the core roles (ADR 0021): the sections, `Used by:` and the required commands.

## Consequences

- No new module, and no change to the gate or the installer. A kit older than E10 has no skills folder, so nothing changes for it.
- `agents.py` holds three things now: roles, locks and skills. Its name is narrower than its job. If a fourth kind of file arrives, a rename or split goes in a new ADR.
- Skills written elsewhere with richer YAML, such as block scalars or lists, are rejected clearly. Their authors can rewrite the front matter in the subset, or a later epic can widen the reader.
- A repo's own skills get the same Agent Skills checks as the kit's, and none of the kit's conventions.
