# E04 · Definition-of-done templates design note

Spec: [E04 spec](../specs/E04-definition-of-done.md) · Issue: [#4](https://github.com/michael-muir/software-factory/issues/4)
Status: **Accepted by the product owner, 19 Nov 2026** · ADRs: [0019](../adr/0019-one-docs-module-with-rules-as-data.md) · [0020](../adr/0020-document-problems-fail-the-verdict-not-the-run.md)

## Summary

There's one new kit module, `.factory/workflow/docs.py`, standard library only, built on `state.py` like `agents.py` is (ADR 0016). It holds:
- one rule table per document kind (ADR 0019)
- `validate(root)`, which lints every spec, design note and ADR under `docs/`
- `lint_pr(text)`, for PR evidence
- a CLI with `check` and `check-pr`

The five templates sit beside it in `.factory/workflow/templates/`. The gate runs `validate` after state and agents, puts the result in its report, and fails the verdict on any problem, while still running the checks (ADR 0020). A survey of this repo's 7 specs, 6 design notes and 18 ADRs against the approved rules found **no fixes needed**.

## Source layout

```text
kit/.factory/workflow/docs.py                 # rules, validate(), lint_pr(), CLI
kit/.factory/workflow/templates/spec.md
kit/.factory/workflow/templates/design.md
kit/.factory/workflow/templates/adr.md
kit/.factory/workflow/templates/task.md
kit/.factory/workflow/templates/pr-evidence.md
kit/.factory/gates/gate.py                    # + lint docs after agents; Report.docs_checked/doc_problems
factory_installer/cli.py                      # install.py check also reports doc problems
```

`kit/.factory/workflow/.gitkeep` goes.

## docs.py

**Rules as data** (ADR 0019). Each kind is a `Kind`:

| Field | Spec | Design note | ADR |
| --- | --- | --- | --- |
| folder | `docs/specs` | `docs/design` | `docs/adr` |
| file name | `<EPIC>-<slug>.md` | `<EPIC>-<slug>.md` | `NNNN-<slug>.md` |
| title | `# <EPIC> · <title> — Spec` | `# <EPIC> · <title> design note` | `# NNNN · <title>` |
| status | bold text starts with `Draft` or `Approved` | bold text starts with `Proposed` or `Accepted` | `Status: <Proposed\|Accepted\|Superseded by NNNN> · Date: YYYY-MM-DD[ · Key: value]...` |
| required line | `Issue:` | `Spec:` (link must resolve) | none |
| headings | Goal, Decisions in force, In scope, Out of scope, Acceptance criteria, Assumptions | Summary, Source layout, Test seams, Vertical slices, Risks | Context, Decision, Consequences |
| extra | at least one `- **AC-nn**`, ids unique | none | a `Superseded by` target must exist |

**Reading a document:** a heading counts when a line outside fenced code blocks equals it, or starts with it followed by a space. The `Status:` line is the first line that starts with `Status:`. The epic or number comes from the file name, and the title must repeat it.

**Repo context is optional.** `lint(kind, rel, text, root)` takes `root=None` for a template. Then checks that need other files, such as a design note's spec link or a superseding ADR, are skipped. Templates are linted as if named `E00-example.md` or `0000-example.md` (spec AC-01).

**PR evidence:** `lint_pr(text)` requires `## What changes`, `## Acceptance criteria`, `## Gate evidence` and `## Findings`, and a `**PASS**` or `**FAIL**` in the gate evidence section.

**CLI:**
- `docs.py [--root PATH] check`: exit 0 when clean, 1 on problems
- `docs.py check-pr [FILE]`: reads stdin when no file is given; exit 0 or 1

Both print `<file>: <where>: <problem>` lines, where `<where>` is a heading, `title`, `status`, `Issue`, `Spec` or an AC id.

**`task.md`:** front matter with placeholder values, then `state.TASK_BODY`. A test writes a task from it and runs `state.validate`.

## Gate change

After `agent_problems`, the gate loads `docs.py` with `_load_module(root/.factory/workflow/docs.py, "factory_docs")` and calls `validate(root)`, which returns a `Checked` holding the problems and a count. The `Report` gains `docs_checked` and `doc_problems`:
- **Text:** `Docs: 31 checked, no problems`, or `Docs: 31 checked, 2 problems` followed by one line each.
- **JSON:** `"docs": {"checked": 31, "problems": [...]}`.

The verdict fails when `doc_problems` isn't empty. The checks run regardless (ADR 0020). A broken lock still stops the run before any check, and the report then shows both.

## Installer change

`install.py check` adds `docs_problems(repo)` from the kit's `docs.py`, through `load_kit_module`, after the state and agent problems.

## Dogfooding (AC-11)

This repo's 31 documents pass today. CI's gate lints them on three OSes from T2 on, when the gate gains the step.

## Test seams

- **In-process:** `docs.lint(kind, rel, text, root)` and `docs.main([...])` with `tmp_path` repos, in the style of the `state.py` tests.
- **Gate:** the existing `gate_repo` fixture plus copies of `state.py` and `docs.py`. A spec with no ACs gives exit 1 with the checks still run, and adding one gives exit 0 (AC-10).
- **Templates:** each template is linted with `root=None` under its example name.
- **Repo:** `docs.validate(REPO_ROOT)` is empty (AC-11).

## Vertical slices

| Task | Slice | ACs |
| --- | --- | --- |
| T1 | `docs.py`: rule table, spec/design/ADR rules, `check`; the `spec.md`, `design.md` and `adr.md` templates; this repo's documents pass | AC-01 (three templates), AC-03 to AC-05, AC-07, AC-11 |
| T2 | The gate step and report section; `install.py check`; the done-when end-to-end test | AC-08 to AC-10 |
| T3 | `task.md` and `pr-evidence.md`; `lint_pr` and `check-pr`; E04 AC coverage enforced | AC-01 (rest), AC-02, AC-06, AC-12 |

Each slice locks its failing tests with `agents.py lock E04-Tn` before its implementation commit.

## Risks

- **Rules that are too strict slow down writing a document.** The rules ask only for parts every existing document already has, and they match headings by prefix, so a heading can still carry a qualifier.
- **One more file is read and parsed on every gate run.** About 31 small files take milliseconds, which is negligible next to the checks.
- **PR evidence isn't checked until E08 wires `check-pr` into CI.** Until then, the template and the check exist, but nothing calls them automatically.
