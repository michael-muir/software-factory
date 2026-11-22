# The full track

A job on the full track goes through nine stages. Each stage is done by the role that owns it, and it passes only when its check, which is code, accepts what the stage committed. People do two things: they approve the spec, and they merge the PR. This page is for the people who run the line. The stage table in `pipeline.py` (`STAGES`) is the source, and a test keeps this page in step with it (ADR 0040).

This version of the kit drives the plan: `pipeline.py check`, `new`, `run` (through the spec and design stages, and the test and build stages of each task), `approve`, `reject`, `resume`, `cancel` and `status`. The gate, review, docs, ship and learn stages arrive with E13-T3. Until then a job that reaches one stops for a human.

## The stages

| Stage    | Roles                                                                                                | Skills                                                                                                          | Runs in       | Checkpoint | Passes when                                                                                                                                                                    |
| -------- | ---------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- | ------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `spec`   | `spec-writer`                                                                                        | `spec-interview`                                                                                                | plan job      | `spec`     | the spec for {epic} is committed in docs/specs, passes docs.py check and has at least one acceptance criterion.                                                                |
| `design` | `architect`                                                                                          | `design-note`                                                                                                   | plan job      | `design`   | the design note for {epic} is committed in docs/design and passes docs.py check, and the task files cover every acceptance criterion of the spec, each naming only the spec's. |
| `test`   | `test-designer`                                                                                      | `tdd-slices`, `lock-tests`                                                                                      | slice job     | none       | the task's lock record is committed with the failing tests, every acceptance criterion of the task is tagged in a locked test, and no code is committed before the lock.       |
| `build`  | `implementer`                                                                                        | `tdd-slices`                                                                                                    | slice job     | none       | a commit follows the lock commit, the worktree is clean, and no locked test has changed.                                                                                       |
| `gate`   | `debugger`, only on a red gate (the driver runs the gate)                                            | `debugging`                                                                                                     | slice job     | none       | the full gate passes on the branch's head commit, from a clean tree.                                                                                                           |
| `review` | `verifier`, `spec-reviewer`, `standards-reviewer`, `security-reviewer`, `perf-reviewer`, `adversary` | `verify-with-evidence`, `spec-review`, `standards-review`, `threat-check`, `perf-budget`, `adversarial-testing` | slice job     | none       | all six review sessions have run, the task's review round is 1, and no blocker or major finding is open.                                                                       |
| `docs`   | `docs-writer`                                                                                        | none                                                                                                            | slice job     | none       | the branch adds an entry under the Unreleased section of CHANGELOG.md, and the full gate still passes on the new head.                                                         |
| `ship`   | `integrator` (the driver checks the body, pushes and opens the PR)                                   | `pull-request-evidence`                                                                                         | slice job     | `merge`    | the PR body passes docs.py check-pr --strict for the branch's commits, the branch is pushed, and the PR is open.                                                               |
| `learn`  | none (the driver writes the summary)                                                                 | none                                                                                                            | main checkout | none       | every task has merged, and the job's summary is written.                                                                                                                       |

**Where each stage runs:**

- **The plan job** is an E16 open job, `<job>-p<k>`, on a branch from `origin/<base_ref>`. It holds the spec, the design note and the task files.
- **A slice job** is an E16 open job per task, `<job>-t<n>-<k>`. The first slice starts from the plan's branch, so its PR carries the plan too. Every later slice starts from `origin/<base_ref>`, fetched after the slice before it has merged.
- **A new segment** (the `<k>`) starts after every wait for a person, because E16's time cap counts waiting.

**What each check reads:** only committed files and history, through `git show`, `git log` and `git diff <base>..HEAD`. A file that's only on disk doesn't count. The gate, review, ship and learn checks also read the job's record: its gate reports, the review sessions that finished, the PR, and which tasks have merged.

## The checkpoints

| Checkpoint | After stage | Passes when                                                                                     |
| ---------- | ----------- | ----------------------------------------------------------------------------------------------- |
| `spec`     | spec        | the product owner runs `pipeline.py approve <job> spec --by <name>`                             |
| `design`   | design      | the product owner runs `pipeline.py approve <job> design --by <name>` (only if it's configured) |
| `merge`    | ship        | a human merges the PR; there is no command for it                                               |

`pipeline.py reject <job> <checkpoint> --by <name> --note TEXT` sends the stage's role again with the note. That is how the spec interview works headless: the Spec Writer puts its questions in the draft, and the answers come back as the note.

## The commands

- `pipeline.py check <job> [<stage>]` runs a stage's check, by default the job's current stage, in the job's worktree. If that worktree has gone, it checks a temporary one, and removes it afterwards. It changes nothing.
- `pipeline.py check <stage> --worktree PATH --epic EPIC [--task TASK] [--base REF] [--gate-report FILE] [--pr-body FILE] [--job JOB]` runs the same check on any checkout, without a job. `--base` defaults to `gates.base_ref`. The slice stages need `--task`. The review, ship and learn stages need `--job`.
- `pipeline.py new <job> --epic <EPIC> (--request-file FILE | --issue N)` creates the job (E18's record) and its pipeline record.
- `pipeline.py run <job>` claims the job's lease, and drives it to the next checkpoint, to a human, or to the end.
- `pipeline.py approve <job> <checkpoint> --by <name>` and `pipeline.py reject ...` record a decision. Approving commits the document's new status line on the plan branch.
- `pipeline.py resume <job> [--note TEXT]` reruns a stage that stopped for a human, and `pipeline.py cancel <job>` cancels the job.
- `pipeline.py status <job> [--json]` prints the job and its pipeline record.

Exit codes: 0 done (or the check passed), 1 refused (a check failed, or a checkpoint is waiting), 2 bad input.

## Sessions

Each role runs headless, as `pipeline.agent_command` with its placeholders filled in. The default is Claude Code:

```text
claude -p --agent {role} --output-format json --permission-mode acceptEdits --permission-prompts none --allowedTools {allowed_tools} {prompt}
```

Three layers hold a session, outermost first (ADR 0042):

1. **E16's caps** on turns, cost and time.
2. **Claude Code's permissions:**
   - `--agent` loads E12's agent file, whose tools are all the session has.
   - `--permission-mode acceptEdits` approves edits inside the worktree.
   - `--allowedTools` approves the role's own rules, generated from its card. A role with a run scope gets `Bash(<prefix> *)` and `PowerShell(<prefix> *)` for each prefix, and never a bare shell.
   - `--permission-prompts none` denies everything else. It needs Claude Code v2.1.259 or later, and it was checked against v2.1.330.
3. **The E03 hook,** which reads `FACTORY_ROLE` and holds every call to the card and the locked tests.

The cost each session reports (`total_cost_usd` in its JSON output) goes to the runner's ledger with `run.py usage`.

## The records

- **The job** is E18's record, `work/<id>.toml`, under `<git-common-dir>/factory/`. Its lease says who may write.
- **The pipeline record** is E18's sidecar `work/<id>.pipeline.toml`. It holds the status, the stage, the tasks and their PRs, the runner jobs, every session sent with its exit code and cost, each gate report, each PR body, and every decision.
- **The summary,** written at the learn stage, is the sidecar `work/<id>.summary.toml`, with the closing handoff's text.

Git never tracks any of these.

## Config

The `[pipeline]` section of `.agentic/config.toml`:

| Key             | Default                       | Rule                                                                                  |
| --------------- | ----------------------------- | ------------------------------------------------------------------------------------- |
| `checkpoints`   | `["spec", "merge"]`           | from `spec`, `design` and `merge`, with no repeats; `spec` and `merge` are required   |
| `agent_command` | the Claude Code command above | not empty; `{prompt}` once; `{role}`, `{allowed_tools}` and `{prompt}` as whole items |
| `forge`         | `"github"`                    | `"github"` (REST through `gh api`) or `"git"` (a pushed branch, for tests)            |
| `gate_retries`  | `2`                           | 0 to 5 Debugger sessions on a red gate                                                |

The driver also reads `gates.base_ref`, `gates.python_command` and E18's `jobs.lease_minutes`.
