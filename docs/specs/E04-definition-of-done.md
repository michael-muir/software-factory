# E04 · Definition-of-done templates — Spec

Issue: [#4](https://github.com/michael-muir/software-factory/issues/4) · Milestone: M1 · Manual factory (alpha) · Depends on: E02 (done)
Status: **Approved by the product owner, 19 Nov 2026** · Next: Architect design note and ADRs, then failing tests per AC

## Goal

"Done" has a written shape, and the gate checks it. Every spec, design note and ADR in a factory repo follows a template, and a gate check fails the verdict when one is missing a required part, such as a spec with no acceptance criteria. Agents write from the templates (Spec Writer, Architect, Integrator and Docs Writer in E09), and reviewers and the Line Monitor can trust that each document has the parts they look for. E04 delivers:
- **`.factory/workflow/templates/`:** `spec.md`, `design.md`, `adr.md`, `task.md` and `pr-evidence.md`.
- **A standard-library document linter in the kit** that checks the documents written from those templates and reports problems as `<file>: <where>: <problem>`.
- **A gate step** that runs the linter on every run and fails the verdict on any problem.

**Done when:** templates are validated by a linter in the gate (PRD).

## Decisions in force (product owner, 19 Nov 2026)

| Topic | Decision |
| --- | --- |
| What is linted | **The documents written from the templates**: every spec, design note and ADR in `docs/`. The templates themselves must also pass. |
| Gate effect | A document problem **fails the verdict** (exit 1) and is listed in the report, text and JSON, the same way as a broken lock. Unlike a broken lock, the checks still run. |
| Formats | The templates **codify today's formats** (the specs, design notes and ADRs already in this repo), so existing documents pass with at most small fixes. |
| Templates | Five: **spec, design note, ADR, task and PR evidence**. |

## In scope

- The five templates, as kit files.
- Lint rules for specs, design notes and ADRs, run by the linter's CLI, the gate and `install.py check`.
- A PR evidence check that runs on a given file. E08 runs it in CI, on the PR body.
- Dogfooding: this repo's own documents pass, and CI's gate checks them.

## Out of scope

- The `pull-request-evidence` skill, and attaching evidence to PRs automatically (E08). E04 only defines the evidence's shape and a way to check it.
- Judging content quality, for example whether an acceptance criterion is testable. That's the Spec Reviewer's job (E09, E14). The linter checks structure only.
- Lint rules for task files and handoffs: `state.py` already validates those (E02).
- Glossary and README formats.

## The documents

| Kind | Where | Template |
| --- | --- | --- |
| Spec | `docs/specs/<EPIC>-<slug>.md` | `spec.md` |
| Design note | `docs/design/<EPIC>-<slug>.md` | `design.md` |
| ADR | `docs/adr/NNNN-<slug>.md` (`README.md` isn't an ADR) | `adr.md` |
| Task | `.agentic/tasks/<id>.md` (validated by `state.py`) | `task.md` |
| PR evidence | a PR body, checked from a file or stdin | `pr-evidence.md` |

Rules common to all of them:
- **Headings** are matched by their start, so `## Assumptions (confirmed with approval, 18 Nov 2026)` counts as `## Assumptions`.
- **Headings inside fenced code blocks are ignored.** A spec may show another file's format, as the E02 spec does.
- **The `Status:` line** is the first line that starts with `Status:`.

## Acceptance criteria

**Templates**

- **AC-01** The kit ships `.factory/workflow/templates/` with `spec.md`, `design.md`, `adr.md`, `task.md` and `pr-evidence.md`. Each template, with its placeholders as written, passes the rules for its kind. The kit's `.factory/workflow/.gitkeep` goes.
- **AC-02** `task.md` stays in step with `state.py`: it has exactly `state.py`'s task headings, and a task written from it is valid state (E02). A test keeps the two equal.

**Lint rules**

- **AC-03** A **spec** must have:
  - a title line `# <EPIC> · <title> — Spec`, whose epic matches the file name's prefix
  - an `Issue:` line, and a `Status:` line whose status (the bold text) starts with `Draft` or `Approved`
  - the headings `## Goal`, `## Decisions in force`, `## In scope`, `## Out of scope`, `## Acceptance criteria` and `## Assumptions`
  - at least one acceptance criterion, written `- **AC-nn**` (two digits, with an optional lowercase letter such as `AC-05b`), and no AC id used twice
- **AC-04** A **design note** must have:
  - a title line `# <EPIC> · <title> design note`, whose epic matches the file name's prefix
  - a `Spec:` line whose link resolves to an existing file, and a `Status:` line whose status starts with `Proposed` or `Accepted`
  - the headings `## Summary`, `## Source layout`, `## Test seams`, `## Vertical slices` and `## Risks`
- **AC-05** An **ADR** must have:
  - a title line `# NNNN · <title>`, whose number matches the file name's
  - a `Status:` line of the form `Status: <status> · Date: YYYY-MM-DD`, optionally followed by more `· Key: value` parts. The status is `Proposed`, `Accepted` or `Superseded by NNNN`, where NNNN names an existing ADR.
  - the headings `## Context`, `## Decision` and `## Consequences`
- **AC-06** **PR evidence** must have the headings `## What changes`, `## Acceptance criteria`, `## Gate evidence` and `## Findings`. The gate evidence must state a verdict, `**PASS**` or `**FAIL**`. The linter checks a PR body given as a file or on stdin, with exit 0 or 1. The gate doesn't check PR evidence, because it isn't a file in the repo.

**Running the linter**

- **AC-07** The linter's `check` command lints every spec, design note and ADR under `docs/`. It prints one line per problem, as `<file>: <heading or line>: <problem>`, and exits 1 if there are any problems, else 0. A repo without those folders has nothing to check.
- **AC-08** **The gate** lints on every run, including `--checks` runs, after it validates state and agents. Problems are listed in the report: text `Docs: N checked, M problems`, then one line each; JSON `"docs": {"checked": N, "problems": [...]}`. Any problem fails the verdict (exit 1). The checks still run. A kit without the linter skips this step.
- **AC-09** `install.py check` reports document problems beside the state and agent problems, in the same format.

**End to end and dogfooding**

- **AC-10** **Done-when, in a test:** in a temp repo with the kit installed, a spec whose `## Acceptance criteria` section has no ACs makes the gate fail, naming the file. Adding an AC makes it pass.
- **AC-11** **This repo's documents pass.** All specs E01 to E07 and this one, all design notes and all ADRs pass, after at most small fixes, each listed in the PR. CI's gate checks them on three OSes.

**Quality**

- **AC-12** ruff, `ruff format --check` and `mypy --strict` pass. The linter stays standard-library only. The kit layout tests list the new kit files. Every AC above has at least one test tagged `E04-AC-nn`, except the CI part of AC-11.

## Assumptions (confirmed with approval, 19 Nov 2026)

1. **The linter is a new kit module** (the Architect places it, for example `.factory/workflow/docs.py`), loaded by the gate and the installer like `state.py` and `agents.py`.
2. **Document locations are conventions,** not configuration: `docs/specs/`, `docs/design/` and `docs/adr/`. A repo that keeps them elsewhere isn't linted until a later epic adds a setting.
3. **Draft documents are allowed.** The linter checks structure, not approval. A `Draft` spec or a `Proposed` ADR passes.
4. **The PR evidence template follows today's PR bodies** ("What changes", "Tests" and "Gate evidence"), and adds "Acceptance criteria" (the AC trace) and "Findings" from the blueprint. E08 fills them in automatically.
