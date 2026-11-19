# E09 · 16 core role definitions design note

Spec: [E09 spec](../specs/E09-core-roles.md) · Issue: [#9](https://github.com/michael-muir/software-factory/issues/9)
Status: **Accepted by the product owner, 19 Nov 2026** · ADRs: [0021](../adr/0021-core-roles-are-kit-data-pinned-by-tests.md)

## Summary

E09 is data, not code: 16 Markdown role files in `kit/.factory/agents/core/`, in the E03 format. There's no new module, and `agents.py`, the gate and the installer don't change. `agents.py check` already validates the front matter, the gate already runs it, and the installer already ships every kit file.

The rules the spec adds are pinned by tests on the kit's own files, not by new validator rules (ADR 0021):
- the role table
- the reviewer limit
- the card layout
- the hand-off names
- the summaries and must-not rules

A repo or a domain expert (E29) can then write a different card, and still pass `agents.py check`.

## Source layout

```text
kit/.factory/agents/core/<name>.md     # 16 role cards, one per row of the spec's table
.factory/agents/core/<name>.md         # this repo's own install (dogfooding, AC-10)
tests/test_core_roles_make.py          # T1: the eight Coordinate, Specify, Make and Learn roles
tests/test_core_roles_prove.py         # T2: the eight Prove and Deliver roles, and the whole set
tests/_repo.py                         # the kit layout gains the 16 files
```

**A card:**

```markdown
+++
name = "verifier"
title = "Verifier"
summary = "Runs the gate; a claim without a report counts for nothing."
model_hint = "any"
different_from = ""
tools = ["read", "search", "run"]

[scope]
run = ["python .factory/gates/gate.py", "...the reviewer limit..."]
+++

## Scope

Does:
- ...

Must not:
- ...

## Inputs

## Outputs

## Hand-off

Pass: `integrator`. Fail: `implementer`, with the report.
```

`## Hand-off` is a fourth heading. E03's validator only requires its three, so the extra one is allowed. Skills are named in prose as `skill: <name>`, and E10 makes them real.

**The reviewer limit** is written out in full in all five cards: the Verifier and the four code reviewers. The E03 format has no includes, so a test keeps the five lists identical, and equal to the spec's prefixes:
- `python`, `python3`, `py` and `uv run python`, each followed by `.factory/gates/gate.py` or `.factory/state/state.py`
- `git diff`, `git log`, `git show` and `git status`

## Test seams

- **The table:** each test file holds its eight rows of the spec's table, as data: name, title, tools, run limit, hint, `different_from` and the summary. Each test parametrizes over those rows, and reads the kit file with `state.parse`, the E03 parser.
- **Cards:**
  - the four headings
  - `Does:` and `Must not:` lists under `## Scope`, each with at least one `- ` item
  - backticked names under `## Hand-off`, which must be in the spec's 16, or `human`
  - the must-not rules of AC-07, found as phrases in the `Must not:` list
- **Validity:** `agents.validate` on a temp repo that holds the kit's `core/` folder returns no problems.
- **The hook (T2, AC-08):** the E03 hook runs in-process (`agents.main(["hook", "claude-code"])`) in a temp repo with the kit installed by `install.py`. For each role and each of the six tools, the test sends a call that's in bounds (a path in `src/`, a command from the role's limit or `git status`). Listed tools must return 0, and unlisted ones 2.
- **Install and upgrade (T2, AC-09):** `install.py` into a temp repo, then `check`. Then a local edit to `core/verifier.md` and an upgrade from a kit with a changed `verifier.md`: the result is `keep`, with `verifier.md.factory-new` written (ADR 0005).
- **Dogfooding (T2, AC-10):** this repo's `.factory/agents/core/` equals the kit's. The live check uses `FACTORY_ROLE=verifier` with the real `claude-hook`.

## Vertical slices

| Task | Slice                                                                                                                                         | ACs                                         |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| T1   | The eight Coordinate, Specify, Make and Learn roles: `router`, `spec-writer`, `architect`, `test-designer`, `implementer`, `debugger`, `docs-writer` and `retro` | AC-01 to AC-07 for these roles              |
| T2   | The eight Prove and Deliver roles; the reviewer limit; exactly 16 files; the hook end to end; install and upgrade; dogfooding; E09 AC coverage | AC-01 to AC-07 for these roles, AC-08 to AC-11 |

In T1, hand-off names are checked against the spec's 16 names, since some of those roles arrive in T2. In T2, they're checked against the files.

## Risks

- **Cards can drift from the table,** for example when a repo tightens a role. Only the kit's copies are pinned. A repo's edits are its own, and E01 keeps them on upgrade.
- **Phrase checks on `Must not:` are brittle wording tests.** They check only the four AC-07 rules, by key phrases such as "locked test", and nothing else in the prose.
- **The reviewer limit hard-codes four ways to run Python.** A repo whose `gates.python_command` is something else, for example `poetry run python`, must add its own prefix. `_schema.md` already says roles may be tightened or adjusted, and the card says how.
- **No mutation cost:** the slices change no Python in the kit, so the gate's mutation step has nothing to mutate.
