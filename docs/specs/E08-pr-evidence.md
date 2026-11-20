# E08 · PR evidence — Spec

Issue: [#8](https://github.com/michael-muir/software-factory/issues/8) · Milestone: M1 · Manual factory (alpha) · Depends on: E04 (done), E05 (done)
Status: **Draft, awaiting product owner approval** · Next: Architect design note and ADRs, then failing tests per AC

## Goal

E04 defined the shape of PR evidence and a check for its headings. E05 gave the gate its reports. E08 puts the two together, so that every PR carries evidence a reviewer can audit without rerunning anything: the gate's verdict for a named commit, the trace from each acceptance criterion to its tests, and the review findings. E08 delivers:

- **`.factory/workflow/evidence.py <task>`:** drafts the PR body from the gate's JSON report, the task file, the spec's ACs, the lock record and the findings. The author still writes the summary and "What changes".
- **A stricter `docs.py check-pr`:** it checks the trace and the evidence's commit as well as the structure.
- **A `pr-evidence` job in the GitHub Actions pipeline,** which checks every PR body, and gate jobs that keep their JSON report as an artefact and summarise it on the job page.
- **The `pull-request-evidence` skill,** which the Integrator follows. It ends E10's exception.

**Done when:** every PR has evidence a reviewer can audit without rerunning (PRD).

## Decisions in force (product owner, 19 Nov 2026)

| Topic           | Decision                                                                                                                                                                                                                                                                                                                                                                  |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Scope           | **The skill plus a standard-library kit command,** `.factory/workflow/evidence.py <task>`. It drafts the PR body from the gate's JSON report, the task file, the spec's ACs, the lock record and the findings. The author writes the summary and "What changes".                                                                                                          |
| CI              | **A `pr-evidence` job in the GitHub Actions pipeline.** Ubuntu only, on `pull_request` opened, edited, synchronize and reopened. It runs `docs.py check-pr` on the body from the event payload. `install.py ci github` renders it, and it runs live on this repo. GitLab, Azure and Jenkins get no body check.                                                            |
| The gate report | **A summary line plus the full report.** The body holds the summary (verdict, commit, each check with its time, locks, docs) and the full text report in a collapsible `<details>` block. CI also saves its own gate JSON report as a build artefact and writes a summary to the job page. A small gate option, `--json-out PATH`, lets one run print text and save JSON. |
| Strictness      | **Structure plus the trace.** The gate evidence names a commit SHA. Every AC id in the trace exists in the epic's spec (read from the root). Every AC lists at least one test. Test names aren't resolved, so the check works for any stack.                                                                                                                              |
| Stale evidence  | **The evidence's commit must be one of the PR's commits** (checked in CI), not necessarily the head. CI's own gate run on the head covers the latest push.                                                                                                                                                                                                                |

## In scope

- Two additions to the gate's report: the commit it ran on, and `--json-out PATH`.
- `evidence.py`, which drafts a PR body for one task.
- `check-pr --strict`, which adds the trace and commit checks, and `--commits`, which checks the evidence's commit against the PR's.
- The rendered GitHub Actions workflow: the `pr-evidence` job, and the gate jobs' artefact and job summary.
- The `pull-request-evidence` skill, with its exercise record, and the Integrator card naming it.
- The PR evidence template, updated to show a commit and the `<details>` block.
- Dogfooding: this repo's workflow is re-rendered, and E08's own PRs are drafted and checked with these tools.

## Out of scope

- Rating merge risk (E17).
- Opening the PR or posting the body through an API. The author or Integrator opens it as today. Doing it in a pipeline is E13's.
- Checking PR bodies in GitLab, Azure or Jenkins, and saving gate artefacts there.
- Resolving test names against the test suite. The trace's names are checked for presence, not existence.
- Rechecking PRs merged before E08.
- Branch protection settings, such as making `pr-evidence` a required check. That's a repo setting for its owner.

## Acceptance criteria

**The gate report**

- **AC-01** The gate's JSON report gains `commit` (the full SHA of `HEAD`, or `null` in a repo with no commits) and `dirty` (true when tracked files differ from `HEAD`). The text report gains a `Commit:` line with the same facts. Everything already in both reports stays as it is.
- **AC-02** `gate.py --json-out PATH` prints the report as usual (text, or JSON with `--json`) and also writes the JSON report to `PATH`, from the same run. It's written whatever the verdict. A path that can't be written is a usage error (exit 2) before any check runs.

**Drafting the body**

- **AC-03** `evidence.py <task> --gate-report PATH` prints a PR body (or writes it with `--out FILE`) that follows `.factory/workflow/templates/pr-evidence.md`. Its first line is `<EPIC>/<Tn>: <placeholder>. Covers <EPIC> **AC-nn** ... Refs #<issue>.`, with the issue number from the spec's `Issue:` line. The epic comes from the task id. The output is deterministic and uses LF line endings.
- **AC-04** **The AC trace:** for each AC id that the task's locked test files tag (`<EPIC>-AC-nn`), one line `- **AC-nn** ...`, in the spec's order, listing in backticks the file and the tests that carry the tag. A tag naming an AC the spec doesn't have stops the draft (exit 1, naming the tag and the file). Test names are found for the kit's stacks (Python and TS/JS). A test the command can't name is listed by its file.
- **AC-05** **Tests:** the number of locked test files and tests, the lock record's path (`.agentic/locks/<task>.toml`), and the commit that added the lock record. A task with no lock record says so, and the trace is left as a placeholder.
- **AC-06** **Gate evidence:** one summary line, holding the verdict in bold, the commit's short SHA, the locks and docs lines, and each check with its status and time. Then the full text report, in a fenced block inside `<details><summary>Full gate report</summary> ... </details>`, the same as the gate printed for that run. A report from a dirty tree, or with no commit, is refused (exit 1), because it doesn't prove a commit.
- **AC-07** **Findings:** one line per `[[findings]]` entry of the task file, with its id, severity, status and summary. A task with no findings says "None."
- **AC-08** **Placeholders:** the summary sentence and "What changes" (and the trace, under AC-05) are left as marked placeholders for the author. A missing task, gate report or spec is an error (exit 1) that names what's missing; usage errors exit 2. Once the author has replaced every placeholder, the draft passes `check-pr --strict`.

**Checking the body**

- **AC-09** `docs.py check-pr --strict` adds these checks to E04's:
  - the gate evidence names a commit SHA (7 to 40 hex characters)
  - every `- **AC-nn**` line under "Acceptance criteria" lists at least one test in backticks, on that line or the lines indented under it
  - a body whose first line names an epic (`E<nn>/...` or `Covers E<nn>`) has at least one AC line, and every AC id in it exists in that epic's spec under the root (`--root`, or the nearest `.agentic/`). A named epic with no spec is a problem. A body that names no epic skips this check.
  - no `evidence.py` placeholder is left

  Problems are printed as `<name>: <where>: <message>`, and the exit code is 1. Without `--strict`, `check-pr` behaves exactly as E04 defined it.

- **AC-10** `check-pr --commits SHA ...` checks the commit the gate evidence names against the PR's commits. A full SHA or a prefix of at least 7 characters matches. A commit that isn't among them is a problem naming both.
- **AC-11** An empty body, or a body that's missing (`null` in the event), gives problems, not a crash.

**CI (GitHub Actions)**

- **AC-12** `install.py ci github` renders a `pr-evidence` job. It:
  - runs on `ubuntu-latest`, for `pull_request` events of the types opened, edited, synchronize and reopened, and never on a push
  - reads the body from the event file (`$GITHUB_EVENT_PATH`), and never puts the body or title into a script with `${{ }}`
  - lists the PR's commits with git, from the event's base and head SHAs
  - runs `docs.py --root . check-pr --strict --commits ...` with Python alone, installing nothing
- **AC-13** Editing a PR's body runs only `pr-evidence`. The gate jobs don't run on the `edited` type.
- **AC-14** On each OS, the gate job saves its JSON report with `--json-out`, uploads it as an artefact named per OS, and writes a summary to the job page (`$GITHUB_STEP_SUMMARY`): the verdict, the commit, and each check with its time. Both steps run when the gate fails too, and work in each OS's default shell.
- **AC-15** The GitLab, Azure and Jenkins pipelines render byte for byte as before.

**The skill**

- **AC-16** The kit ships `.factory/skills/pull-request-evidence/SKILL.md`, valid under E10's AC-02 and following its AC-04 conventions, with `Used by:` `integrator`. Its steps run the gate with `--json-out`, draft the body with `evidence.py`, fill in the placeholders, check it with `check-pr --strict`, and open the PR. The Integrator card names it, and E10's exception for it is gone (E10 AC-05 holds with no exception).
- **AC-17** The skill is exercised live: E08's own PRs are drafted with `evidence.py` by following the skill, and E10's exercise record names the PR and commits.

**Done-when and dogfooding**

- **AC-18** **Done-when, in a test:** a temp repo holds a spec, a task with locked tests tagged with its ACs, a finding, and a gate JSON report. `evidence.py` drafts the body, the test fills in the placeholders, and `check-pr --strict --commits` passes it. From the body alone, the test reads back the verdict, the commit, each check's time, each AC's tests and each finding, and they match the inputs. Each tampering fails the check: an AC that isn't in the spec, an AC with no test, no commit, and a commit that isn't the PR's.
- **AC-19** **Live:** this repo's workflow is re-rendered and committed. On E08's PRs, `pr-evidence` passes, and each gate job's artefact and summary are on the run. The PR links to them.
- **AC-20** ruff, `ruff format --check` and `mypy --strict` pass. `evidence.py` is standard library only. The kit layout tests list the new kit files. Every AC above has at least one test tagged `E08-AC-nn`, except AC-17 and AC-19.

## Assumptions (to confirm with approval)

1. **`--strict` is a new option, so E04's locked tests stay locked.** E04-T3's locked tests pin today's `check-pr`: a body with no commit passes, and so does the template. A strict default would need those tests relocked. The skill and CI always pass `--strict`.
2. **E10-T3 needs one relock, at the test commit, with the product owner's approval.** Its locked `tests/test_skills_prove.py` pins exactly 16 kit skills and names `pull-request-evidence` as the one exception. The relock adds the skill to the set, empties the exception and adds its exercise record. Nothing else in the file changes.
3. **E07's pipeline tests aren't locked.** They pin the GitHub job's exact steps, and E08's test commit updates them for the new steps. The PR flags it.
4. **One PR covers one task.** `evidence.py` drafts for one task. A PR spanning several is drafted by hand, and `check-pr --strict` still checks it.
5. **The placeholder is visible text,** such as `TODO(author): ...`, not an HTML comment, so a reviewer sees what wasn't filled in.
6. **A dirty tree can't give evidence.** The gate still runs on one, but `evidence.py` refuses its report, because the result doesn't belong to a commit.
7. **CI reads the PR's commits with git** (`fetch-depth: 0`, then base SHA..head SHA from the event), not through the GitHub API, so the job needs no token.
