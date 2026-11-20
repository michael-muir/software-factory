# 0025 · PR evidence is drafted from the gate's JSON report and checked strictly on request

Status: Accepted · Date: 2026-11-19 · Epic: E08

## Context

A PR's evidence has to name the commit it proves, show the gate's result for that commit, and trace each acceptance criterion to its tests. Until E08, authors pasted a hand-written summary of the gate's text report, with no commit check and nothing to compare the trace against.

The product owner chose a kit command that drafts the body, and a check that verifies the trace (spec decisions). That leaves three questions for the design:

- What the draft is built from.
- How the full text report gets into the body without a second renderer.
- How the stricter check coexists with E04's locked tests. Those tests require plain `check-pr` to pass a body that names no commit.

## Decision

- **The gate's JSON report is the contract.** It gains `commit` and `dirty`. `gate.py --json-out PATH` saves it from the same run that prints the text. `evidence.py` reads only that file, the task file, the lock record and the spec. It never reruns the gate.
- **One renderer.** `gate.py` gains `Report.from_json(data)`. `evidence.py` loads `gate.py` by path, as the gate loads `docs.py` (ADR 0016's pattern), and calls `from_json(...).to_text()` for the `<details>` block. `from_json(to_json())` round-trips, so the block is exactly what the gate printed.
- **No evidence from a dirty tree.** A report with `dirty: true` or no commit is refused, because its result doesn't belong to a commit.
- **The trace comes from tags in the locked test files.** The text `<EPIC>-AC-nn` binds to the next test definition in the same file: Python `def test_*`, or TS/JS `test(` or `it(`. Stacked tags bind to the same test. A tag the spec doesn't have stops the draft.
- **Strict checking is opt-in.** `check-pr --strict` adds the commit, trace, spec and placeholder rules. `--commits` adds the PR-commit rule. Plain `check-pr` stays E04's check, byte for byte. The skill and CI always pass `--strict`.
- **Placeholders are visible.** `TODO(author): ...` lines mark what the author must write. `--strict` rejects any that are left.

## Consequences

- A reviewer can audit a PR without rerunning anything. The body names a clean commit, CI checks that the commit belongs to the PR, and the full report is there to read.
- The gate's JSON gains two keys that other readers, such as E13's pipeline and the Line Monitor, can rely on. `Report.from_json` must be updated whenever `Report` gains a field, and a round-trip test pins that.
- Tag binding is lexical, so it works without running a test collector. A tag far from its test, or in a stack the kit doesn't ship, falls back to listing the file.
- A bare `check-pr` remains weak. Anything that wants the full check must ask for `--strict`.
