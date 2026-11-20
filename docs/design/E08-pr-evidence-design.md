# E08 · PR evidence design note

Spec: [E08 spec](../specs/E08-pr-evidence.md) · Issue: [#8](https://github.com/michael-muir/software-factory/issues/8)
Status: **Proposed, awaiting product owner acceptance** · ADRs: [0025](../adr/0025-pr-evidence-is-drafted-from-the-gates-json-report.md) · [0026](../adr/0026-pr-bodies-are-checked-in-their-own-github-workflow.md)

## Summary

There are four parts:

1. **The gate's report** names its commit and whether the tree was dirty. `--json-out PATH` saves the JSON from the same run, and `Report.from_json` rebuilds a report from it, so there's one text renderer (ADR 0025).
2. **A kit module, `.factory/workflow/evidence.py`,** standard library only. It loads its siblings by path: `docs.py` for the spec's ACs, `state.py` for the task and its findings, and `gate.py` for `Report.from_json`. It drafts one task's PR body, with `TODO(author):` placeholders where only the author can write. `--summary REPORT` prints the short Markdown summary CI puts on the job page.
3. **`docs.py check-pr --strict` and `--commits`** add the commit, trace, spec, placeholder and PR-commit rules. Plain `check-pr` doesn't change (ADR 0025).
4. **`install.py ci github`** renders a second workflow, `factory-pr-evidence.yml`, and gives the gate jobs an artefact and a job summary (ADR 0026). Then comes the `pull-request-evidence` skill, which writes down the procedure.

## Source layout

```text
kit/.factory/gates/gate.py               # + commit, dirty, --json-out, Report.from_json
kit/.factory/workflow/evidence.py        # draft <task> --gate-report PATH [--out FILE]; --summary REPORT
kit/.factory/workflow/docs.py            # + check-pr --strict, --commits SHA...
kit/.factory/workflow/templates/pr-evidence.md   # shows a commit and the <details> block
kit/.factory/skills/pull-request-evidence/SKILL.md
kit/.factory/agents/core/integrator.md   # names evidence.py in its Does list
factory_installer/pipelines.py           # Provider.extra files; render_github_evidence; gate steps
.github/workflows/factory-gate.yml, factory-pr-evidence.yml   # this repo's rendered workflows
```

## The gate report

- **`commit`:** from `git rev-parse HEAD`, or `null` when there are no commits.
- **`dirty`:** whether `git status --porcelain --untracked-files=no` prints anything. Both are read once, before any check runs.
- **The text report** gains `Commit: <sha>` after `Base:`. On a dirty tree, ` (uncommitted changes)` is added. With no commits, it reads `Commit: none`.
- **`--json-out PATH`:** the parent folder must exist and the path must not be a folder. Otherwise it's exit 2, before validation. The file is written after the report prints, with LF line endings.
- **`Report.from_json(data)`** is the inverse of `to_json`. When E12-T3's adapter drift fields land in `Report`, `from_json` covers them too.

## Drafting (`evidence.py`)

**Inputs:**

- `.agentic/tasks/<task>.md`, through `state.parse`.
- The epic: the task id up to `-T` (E08-T2 → E08).
- `docs/specs/<EPIC>-*.md`: its AC ids (`docs.AC_ID`, in order), and the issue from `Issue: [#N]`.
- `.agentic/locks/<task>.toml`: its file paths, through `tomllib`.
- The lock record's commit: `git log -1 --format=%h -- <record>`.
- The gate report JSON.

**The body, section by section:**

- **First line:** `<EPIC>/<Tn>: TODO(author): what this PR delivers. Covers <EPIC> **AC-03** to **AC-05**. Refs #<issue>.` A run of consecutive ACs is written as a range, and other ACs as a list.
- **What changes:** `- TODO(author): what each change does, and why.`
- **Acceptance criteria:** one line per traced AC, in spec order: ``- **AC-04** `tests/test_x.py`: `test_a`, `test_b` ``. More than one file gives one indented line per file.
- **Tests:** `N tests in M files, locked in .agentic/locks/<task>.toml (<sha>).` With no lock record: `No locked tests.`, and the trace is a single `TODO(author)` line.
- **Gate evidence:** this summary line, followed by the `<details><summary>Full gate report</summary>` block holding a fenced `text` block of `Report.from_json(...).to_text()`:

  ```text
  **PASS** on `<12-char sha>` · Locks: … · Docs: … · python format pass 0.21 s · …
  ```

  A check that didn't run shows its status without a time.

- **Findings:** `- F1 [major] (fixed) summary`, one per finding, or `None.`

**How tags bind:** the text `<EPIC>-AC-nn` binds to the next test definition after it in the same file:

- Python: `^\s*(async\s+)?def (test_\w+)`
- TS/JS: `\b(test|it)(\.\w+)?\(\s*(['"\`])(.+?)\3`

The tags stacked before one test all bind to it. A tag with no test after it is listed under its file alone. The test count is the number of such definitions in the locked files.

**Exit codes:** 0 when drafted. 1 for refused input: a missing task, report, spec or locked file, a dirty report or one with no commit, or a tag not in the spec. 2 for usage errors.

**`--summary REPORT`:** prints the summary line, then a Markdown table of profile, check, status and time. A missing or unreadable report prints `No gate report.` and exits 0, so the CI step never hides the gate's own result.

## Checking (`check-pr --strict`)

E04's `lint_pr` runs first, unchanged. Then `lint_pr_strict(text, name, root, commits)` adds these rules:

- **The epic** comes from the first non-empty line: `^(E\d+)/T\d+` or `Covers (E\d+)`.
- **The commit:** the first whole word of 7 to 40 lowercase hex characters, with at least one digit, under "Gate evidence". If there's none: "no commit SHA".
- **The trace:** each `- **AC-nn**` line under "Acceptance criteria", with the indented lines that follow it, needs at least one backtick span. Without one: "lists no test".
- **The spec:** with an epic named, at least one AC line, and every id must be in `docs/specs/<EPIC>-*.md` under the root. Missing: "not in the E08 spec". No spec at all: "no spec for E08".
- **Placeholders:** any line containing `TODO(author)`.
- **`--commits SHA ...`:** the commit must be a prefix of one of them, or equal to one. If not: "evidence is for <sha>, which is not a commit of this PR".
- An empty file, or empty stdin, gives E04's four missing-heading problems plus the strict ones.

## Test seams

- **Gate:** in temp git repos (`tests/_repo.git_repo`):
  - `commit` and `dirty`, both clean and with a tracked edit
  - `Commit: none` before the first commit
  - `--json-out` writes the same data as `--json` would print, on PASS and FAIL
  - a bad path exits 2 with no checks run
  - `from_json(to_json()).to_text() == to_text()`
- **`evidence.py`:** `evidence.main([...])` in-process, on fixture repos holding a spec, task, lock record and test files (Python and TS), and a hand-made report JSON. The tests compare whole drafts with expected text. Each refusal and its exit code is checked too, and a filled-in draft must pass `lint_pr_strict`.
- **`check-pr`:** strings into `lint_pr_strict`, one test per rule. `docs.main` checks the exit codes. Plain `check-pr` gives the same results as E04's locked tests, which stay untouched.
- **Pipelines:** parse the rendered YAML and check:
  - the evidence workflow's triggers, its runner and its steps
  - that no `${{` in a `run:` mentions `body` or `title`
  - the gate job's new steps, with `if: always()` and the artefact name
  - that GitLab, Azure and Jenkins are byte for byte the same as before (a golden copy, taken before the change)

  A further test runs the evidence step's script under bash with a fake event file and a temp repo.

- **Done-when (AC-18):** one test drives draft, fill, check and read-back, plus the four tamperings, in a temp repo.

## Vertical slices

| Task | Slice                                                                                                                                                                   | ACs                   |
| ---- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------- |
| T1   | The gate report: `commit`, `dirty`, `Commit:` line, `--json-out`, `Report.from_json`                                                                                    | AC-01, AC-02          |
| T2   | `evidence.py`: the draft (summary, trace, tests, gate evidence, findings, placeholders) and `--summary`; the template shows a commit and `<details>`                    | AC-03 to AC-08        |
| T3   | `check-pr --strict` and `--commits`; empty bodies. T3's own PR is drafted with `evidence.py` and checked with `--strict`                                                | AC-09 to AC-11        |
| T4   | CI: `factory-pr-evidence.yml`, the gate jobs' artefact and summary, other providers unchanged, this repo re-rendered and checked live                                   | AC-12 to AC-15, AC-19 |
| T5   | The `pull-request-evidence` skill and Integrator card; E10's exception removed (E10-T3 relock, with approval); the exercise record; the done-when test; E08 AC coverage | AC-16 to AC-18, AC-20 |

## Risks

- **E10-T3's relock** is needed in T5. Its locked file pins 16 skills and the `NOT_YET` exception. The exact diff goes to the product owner at T5's test commit: the skill added to `ALL_SKILLS`, `NOT_YET` emptied, and one `EXERCISED` entry. Nothing in T1 to T4 touches that file.
- **The live record is retrospective in part.** The procedure the skill writes down (gate `--json-out`, `evidence.py`, fill in, `check-pr --strict`) is followed on T3's and T4's PRs, before the skill file exists. So E10's record cites those PRs and commits, which are known by T5. T5's own PR then follows the skill as written.
- **Parallel edits to `gate.py`'s `Report`:** E12-T3 adds adapter drift fields. Whichever merges second updates `from_json` and its round-trip test. The orchestrator is told when T1's PR opens.
- **ADR numbers:** 0025 and 0026 are the next free on main. If another branch takes them first, these are renumbered at merge.
- **Hex-word false positives:** a 7-character all-hex word with a digit, under "Gate evidence", could be mistaken for the commit. `evidence.py` always puts the commit first, and `--commits` in CI catches a wrong one.
- **Lexical tag binding** can miss tests written in unusual forms. They fall back to listing the file, which still passes the trace check, and the author can edit the line.
- **Windows runners and `shell: bash`:** GitHub's Windows images ship Git Bash, and E07's hooks already rely on it. The summary step is the only new bash step on Windows.
