# E13 · Full-track pipeline design note

Spec: [E13 spec](../specs/E13-full-track-pipeline.md) · Issue: [#13](https://github.com/michael-muir/software-factory/issues/13)
Status: **Accepted by the product owner, 21 Nov 2026** · ADRs: [0040](../adr/0040-a-stage-passes-only-by-a-check-over-committed-files.md) · [0041](../adr/0041-the-driver-is-a-resumable-step-machine-under-the-e18-lease.md) · [0042](../adr/0042-a-role-session-is-a-templated-command-held-by-an-allow-list-and-the-hook.md) · [0043](../adr/0043-the-driver-opens-prs-through-a-forge-only-after-check-pr-strict.md) · [0044](../adr/0044-approvals-commit-status-lines-with-git-plumbing.md) · [0047](../adr/0047-a-relock-is-a-recorded-human-decision-the-driver-carries-out.md)

## Summary

There is one new kit module, `.factory/workflow/pipeline.py`, standard library only, and one kit document, `.factory/workflow/pipeline.md`. The module has five parts:

1. **The stage table** (ADR 0040): one data structure, `STAGES`, with each stage's name, role, skills, where it runs, its checkpoint and its check. `pipeline.md`'s table and the prompts are made from it, and a test pins them to each other.
2. **The checks** (ADR 0040): one function per stage, `check_<stage>(Checkout) -> list[Problem]`. A check reads the committed files and history of a checkout, plus the gate's JSON report where it's needed. It never trusts what an agent says it did.
3. **The driver** (ADR 0041): `Driver.step()` does exactly one action, such as submitting a runner job, sending a command, collecting a finished command, running a check or moving to the next stage. It writes the pipeline record after every action. `run` calls `step()` until it reaches a wait point: a checkpoint, a merge, a human, or the end. A wait point releases the lease and exits.
4. **Sessions** (ADR 0042): `session_argv(role, prompt)` fills `pipeline.agent_command` with the role, its generated allow-list and the stage prompt. The command runs on the runner with `FACTORY_ROLE` set.
5. **Ports to the outside:**
   - **`Runner`:** the E16 CLI.
   - **`Jobs`:** E18's `jobs.py`.
   - **`Forge`:** GitHub REST through `gh api`, or plain git (ADR 0043).
   - **The plumbing committer** for approvals (ADR 0044).

   Each has a real version that calls a command line and a fake for the fast tests.

Everything the pipeline keeps is in two E18 sidecars beside E18's `work/<job>.toml`: `work/<job>.pipeline.toml` and, at the end, `work/<job>.summary.toml`. Both are written with `jobs.write_sidecar` while holding the lease. E18's record and lease are the job; the pipeline record holds the stages, approvals, runner jobs, gate reports and PRs.

## Source layout

```text
kit/.factory/workflow/pipeline.py      # STAGES, checks, Record, Driver, sessions, Runner/Jobs/Forge ports; CLI: new | run | check | approve | reject | resume | cancel | status
kit/.factory/workflow/pipeline.md      # the full track for people: stages, roles, skills, checks, checkpoints, commands, config
factory_installer/config_schema.py     # + [pipeline]: checkpoints, agent_command, forge, gate_retries
.agentic/config.toml                   # this repo gains [pipeline], with the design checkpoint on
CHANGELOG.md                           # new: Keep a Changelog, with ## [Unreleased]
.factory/workflow/pipeline.py, pipeline.md   # this repo's install of the kit files
tests/_pipeline.py                     # temp repos with the kit and a bare origin; FakeRunner, FakeJobs, FakeForge; record builders
tests/fixtures/pipeline/fake_agent.py  # a scripted agent: reads FACTORY_ROLE and a script, does the role's work, prints {"total_cost_usd": ...}
tests/test_pipeline_*.py               # one file per slice
pyproject.toml                         # pipeline.py is under kit/.factory/workflow, already on the paths
```

`pipeline.py` loads its siblings by path, as `evidence.py` does: `state.py` (task files, findings, handoffs), `docs.py` (`check`, `check-pr`), `evidence.py` (AC tags in locked files) and `agents.py` (role cards and E12's Claude Code tool names). It calls `run.py` only through its command line, so E23's transport works unchanged. It calls E18's `jobs.py` through the Python API that E18's design pins as a contract (`new_job`, `read_job`, `set_job`, `claim`, `beat`, `release`, `lease_state`, `sidecar_path`, `write_sidecar`), loaded by path.

## The stage table

```python
@dataclass(frozen=True)
class Stage:
    name: str  # one of state.PHASES
    roles: tuple[str, ...]  # sessions, in order; () when the driver does the work
    skills: tuple[str, ...]  # one per role, or the stage's skills
    scope: str  # "plan", "slice" or "main"
    checkpoint: str  # "", "spec", "design" or "merge"
    passes: str  # the plain-text pass condition, used in prompts and pipeline.md
    check: Callable[[Checkout], list[Problem]]
```

| Stage  | Roles                                                                                                | Scope | Checkpoint |
| ------ | ---------------------------------------------------------------------------------------------------- | ----- | ---------- |
| spec   | `spec-writer`                                                                                        | plan  | spec       |
| design | `architect`                                                                                          | plan  | design     |
| test   | `test-designer`                                                                                      | slice |            |
| build  | `implementer`                                                                                        | slice |            |
| gate   | (driver), `debugger` on red                                                                          | slice |            |
| review | `verifier`, `spec-reviewer`, `standards-reviewer`, `security-reviewer`, `perf-reviewer`, `adversary` | slice |            |
| docs   | `docs-writer`                                                                                        | slice |            |
| ship   | `integrator`                                                                                         | slice | merge      |
| learn  | (driver)                                                                                             | main  |            |

A checkpoint that isn't in `pipeline.checkpoints` is skipped (only `design` can be left out). `next_stage(record)` is a pure function of the record and the table. It is the only way the driver moves on (spec AC-05).

## The checks

`Checkout(path, epic, task, base, head)` is a worktree at `head`, with `base` the commit the scope started from: `origin/<base_ref>` for the plan, and the plan branch's head or `origin/<base_ref>` for a slice. Every check reads committed state with `git show`, `git log` and `git diff --name-only base..head`, so uncommitted files never count. A check returns problems as `<stage>: <file or commit>: <message>`, the same shape as `state.Problem`.

| Stage  | Conditions, each a separate problem                                                                                                                                                                                                                                                                                                  |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| spec   | exactly one `docs/specs/<EPIC>-*.md` at `head`; it's in a commit after `base`; `docs.lint("spec", ...)` has no problems; it has at least one `- **AC-nn**`                                                                                                                                                                           |
| design | one `docs/design/<EPIC>-*.md`, committed and lint-clean; at least one `.agentic/tasks/<EPIC>-T<n>.md` that `state.py check` accepts. Each task's ACs are read from its `## Acceptance criteria` section: every `AC-nn`, with `AC-aa to AC-bb` expanded. Every one of them is in the spec, and every spec AC is in at least one task. |
| test   | `.agentic/locks/<task>.toml` is committed. Every AC the task names is tagged `<EPIC>-AC-nn` in a locked file (`evidence.trace_file`). The commit that adds the lock record is the first commit after `base` that changes a file outside `.agentic/` (so no code change comes before the lock).                                       |
| build  | at least one commit after the lock commit; `git status --porcelain` is empty; `agents.py check` passes (the lock hashes hold)                                                                                                                                                                                                        |
| gate   | the newest gate report for the task, in the record (or `--gate-report PATH`), has `verdict = "pass"`, `commit` equal to `head` and `dirty = false`                                                                                                                                                                                   |
| review | the record shows all six review sessions finished for this task; the task's `review_round` is 1; no finding of severity `blocker` or `major` has status `open`                                                                                                                                                                       |
| docs   | `git diff base..head -- CHANGELOG.md` adds a line inside the `## [Unreleased]` section; the gate check holds again for the new `head`                                                                                                                                                                                                |
| ship   | the body file passes `docs.py --root <checkout> check-pr --strict <body> --commits <rev-list base..head>`; the forge reports the PR open with head = the pushed branch                                                                                                                                                               |
| learn  | every task has `merged = true` in the record; the `summary` sidecar exists and its `handoff` text has E02's three headings                                                                                                                                                                                                           |

`pipeline.py check <stage> --worktree PATH --epic E [--task T] [--base REF]` builds a `Checkout` directly. For the gate, review and ship checks, which also need the record, it reads the record of the job named by `--job`, or takes `--gate-report PATH` and `--pr-body PATH`. `check <job> [stage]` builds the `Checkout` from the record: the current runner job's worktree, or, if that has gone, a temporary detached worktree of the branch in the system temp folder, removed afterwards.

## The records

`work/<job>.pipeline.toml`, an E18 sidecar, written with `jobs.write_sidecar` (atomic, and only while holding the lease):

```toml
version = 1
id = "e31-evidence-tags"          # the E18 job's id
epic = "E31"
issue = 82                       # 0 when the request came from a file
status = "awaiting-approval"     # ready | running | awaiting-approval | awaiting-merge | needs-human | cancelled | done
reason = ""
stage = "spec"
task = "e31-evidence-tags"       # the plan's task is the job id; slices use <EPIC>-T<n>
base = "main"
warnings = []

[[tasks]]                        # filled from the design's task files after the design stage
id = "E31-T1"
branch = "factory/e31-evidence-tags-t1"   # the pushed PR branch
pr = "17"                        # the forge's reference: a PR number, or the branch for forge = "git"
merged = false

[[runs]]                         # one per E16 runner job, in order
id = "e31-evidence-tags-p1"
task = "e31-evidence-tags"
base = "origin/main"
stages = ["spec"]
branch = "factory/e31-evidence-tags-p1"
worktree = "/home/me/proj.worktrees/e31-evidence-tags-p1"

[[sessions]]                     # one per command the driver sent
run = "e31-evidence-tags-p1"
index = 1                        # the runner's command number
stage = "spec"
task = "e31-evidence-tags"
role = "spec-writer"             # or "gate", "commit", "push"
sent = 2026-11-21T10:00:00Z
exit_code = 0                    # absent until collected
usd = "0.42"

[[decisions]]
checkpoint = "spec"
verdict = "reject"               # approve | reject
by = "michael-muir"
at = 2026-11-21T11:00:00Z
note = "Answer to Q1: option A."
```

The record also holds, as TOML strings:

- `request`: the request, from `--request-file` or the issue
- `[[gates]]`: each gate run's task, commit, verdict and full JSON report
- the PR body of each task, under `[[tasks]]`

Files that a command has to write go to the runner worktree's own git dir, `git rev-parse --git-path factory-pipeline` (for example `<common>/worktrees/<name>/factory-pipeline/`). They are `gate-<n>.json` and `pr-body.md`. Git never tracks them, they never make the tree dirty, and they go away with the worktree. The driver reads each one into the record as soon as its command finishes. The learn stage writes a second sidecar, `work/<job>.summary.toml`, which holds the summary and the closing handoff's text.

Stage times and costs in `status` and the summary are worked out from `[[sessions]]`.

## The driver (ADR 0041)

`run <job>`:

1. Read the config and the record.
2. Claim the job: `jobs.py claim <job> --session <S>`. The session is `--session`, `FACTORY_SESSION`, or `pipeline-<host>-<pid>`. Exit 1 if the claim is refused.
3. Loop `step()` until it returns a wait point, calling `jobs.py beat` whenever `lease_minutes / 3` has passed.
4. Release the lease, and exit 0 (checkpoint, merge or done) or 1 (a human is needed).

`step()` looks at the record and does the first of these that applies:

- **A command is outstanding** (the newest `[[sessions]]` entry has no `exit_code`). Poll `run.py status <run> --json`. If the command has finished, record its exit code, read `total_cost_usd` from its log, report it with `run.py usage`, and record it. If the runner job is `halted` or `failed`, the pipeline needs a human, with the runner's reason. Otherwise sleep 1 second.
- **The stage's sessions aren't all done.** Make sure a runner job is open for the scope. If not, submit `run.py submit --open --id <job>-<p|tN>-<k> --base <ref> --task <task>`, set the E18 job's branch and worktree, and then send the next session.
- **All sessions are done.** Run the stage's check. Failing problems make the job `needs-human`, with the problems as the reason. The gate is the exception: the Debugger and the gate run again, up to `gate_retries` times.
- **The check passed.** If the stage has a configured checkpoint, close the runner job, set the status to `awaiting-approval` or `awaiting-merge` (and E18's to `blocked`), and return a wait point. If not, set `stage = next_stage(...)`, update E18's `phase` and `task`, and go on.

Every write to the record happens before the action it describes is confirmed: the `[[sessions]]` entry is written, then `run.py send` runs. So a crash between the two never sends a command twice. On restart, a session entry with no matching runner command (`status --json` shows fewer commands than `index`) is sent again; otherwise it's waited for.

**Runner jobs and their ids:** `<job>-p<k>` for plan segments and `<job>-t<n>-<k>` for slice segments. A segment ends at every wait point, because E16's time cap counts time spent waiting for commands, and a human may take longer than `job_timeout_minutes`. A new segment's base is the last segment's branch, `factory/<previous id>`. The first slice's first segment starts from the plan's last branch, and every later slice's from `origin/<base_ref>`, after `git fetch origin`. With a 30-character job id, `<job>-t99-99` fits E16's 40.

**Commands the driver sends itself** (each is one E16 turn):

| What            | argv                                                                                                                                 |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| a role session  | `session_argv(role, prompt)`, with `FACTORY_ROLE`, `FACTORY_PR_BODY` and `FACTORY_GATE_REPORT` passed through `env` (below)          |
| the gate        | `gates.python_command + [".factory/gates/gate.py", "--json-out", "<scratch>/gate-<n>.json"]`                                         |
| findings commit | `git add .agentic/tasks/<task>.md`, then `git commit -m "chore(<task>): review findings from <role>"`, sent only if the file changed |
| push            | `git push origin HEAD:refs/heads/factory/<job>-t<n>`                                                                                 |

E16 gives commands no extra environment beyond `FACTORY_JOB`. So the driver sends `[sys.executable, pipeline.py, "_env", "KEY=VALUE", ..., "--", argv...]`. That small internal command sets the variables and runs `argv` with `os.execv` on POSIX, or a `subprocess` call that passes the exit code on Windows (the runner's Job Object still holds the tree).

**The prompt** is made by `prompt(stage, role, job=, epic=, task=, reads=, note=)` from a fixed template. It names the job, stage, epic, task and skill, the files to read (the request, the spec, the design note, the task file), the last rejection note, and the stage's `passes` text. It ends with "Commit your work and stop." It's deterministic, and a test pins one stage's prompt in full.

**Resume and cancel.** `resume` clears `needs-human` and drops the failed stage's unfinished sessions, so that stage starts again with the note. If the runner job is no longer running, the next step opens a new segment from its branch. `cancel` runs `run.py cancel` on an open segment, sets `cancelled`, and sets the E18 job `cancelled`.

## Sessions and the allow-list (ADR 0042)

`allowed_tools(card)` maps the card's neutral tools with `agents.CLAUDE_CODE_AGENT_TOOLS` (E12's table), keeping its order and dropping repeats:

- **`run` with no `[scope].run`:** `Bash`, `PowerShell`.
- **`run` with scopes:** for each prefix, `Bash(<prefix> *)` then `PowerShell(<prefix> *)`.
- **Joining:** the rules are joined with `,`.

For the Verifier, that is `Read,Glob,Grep,Bash(python .factory/gates/gate.py *),PowerShell(python .factory/gates/gate.py *),...,Bash(git status *),PowerShell(git status *)`. A trailing ` *` is Claude Code's documented prefix form (it also matches the bare command), and Claude Code matches each part of a compound command on its own, so `gate.py && rm -rf x` isn't allowed by the gate's rule.

These layers apply to a session, from the outside in:

1. **E16's caps:** turns, cost and time for the runner job.
2. **Claude Code's permissions:**
   - `--agent <role>` loads E12's generated agent file, whose `tools` limits what the session has at all.
   - `--permission-mode acceptEdits` approves edits inside the worktree.
   - `--allowedTools` approves the role's own rules.
   - `--permission-prompts none` denies anything else, without retrying.
3. **E03's `PreToolUse` hook:** it reads `FACTORY_ROLE`, and denies an out-of-role tool or command, or an edit to a locked file.

**What a template can contain:** `pipeline.agent_command` is checked by `install.py check` and by `pipeline.py` with the same rules (a test pins the agreement, as E16 did). `{role}`, `{allowed_tools}` and `{prompt}` must each be a whole element, never part of one, so a prompt can never be split into extra arguments.

## Forges and approvals (ADRs 0043, 0044)

```python
class Forge(Protocol):
    def open(
        self, branch: str, base: str, title: str, body: str
    ) -> str: ...  # returns the PR's reference
    def state(self, ref: str, branch: str, base: str) -> str: ...  # "open", "merged" or "closed"
```

- **`GitHubForge`:** owner and repo come from `git remote get-url origin` (https or ssh forms).
  - **`open`:** `gh api repos/<o>/<r>/pulls -f title=... -f head=<branch> -f base=<base> -F body=@<file>`, then the number from the JSON.
  - **`state`:** `gh api repos/<o>/<r>/pulls/<n>`; `merged: true` means merged, `state: closed` means closed.
  - Never GraphQL.
- **`GitForge`:**
  - **`open`:** returns the branch.
  - **`state`:** `git fetch origin`; merged if `git merge-base --is-ancestor <branch head> origin/<base>`; closed if the remote branch has gone without being merged.

**The order of the ship stage:**

1. The Integrator's session writes the body to `FACTORY_PR_BODY`.
2. The driver runs `check-pr --strict --commits`.
3. The push command.
4. `Forge.open`.

The title is the body's first line, up to the first `.`. A body that fails the check never reaches a push.

**Approvals:** `approve <job> <checkpoint> --by <name>` claims the lease, checks that the job is waiting at that checkpoint, and records the decision. Then it commits the new status line to the plan's last branch with git plumbing, without a checkout (ADR 0044):

1. `git show <branch>:<doc>`
2. Replace the `Status:` line: the spec's becomes `Status: **Approved by <name>, <d Mon yyyy>** · Next: Architect design note and ADRs, then failing tests per AC`; the design note's keeps its `· ADRs: ...` part.
3. `docs.lint` on the new text.
4. `git hash-object -w`, `GIT_INDEX_FILE=<temp> git read-tree <branch>`, `git update-index --cacheinfo`, `git write-tree`, `git commit-tree -p <branch>`, `git update-ref refs/heads/<branch> <new> <old>`.

The last step refuses if the branch moved, so a concurrent writer never loses a commit. `reject` records the decision with its note, and moves the stage back so the next `run` sends its role again.

## Config

The `[pipeline]` keys go in `config_schema.SECTIONS` after `[runner]`:

| Key             | Kind    | Default                         | Rule                                                                                                   |
| --------------- | ------- | ------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `checkpoints`   | strlist | `["spec", "merge"]`             | from `spec`, `design`, `merge`; no repeats; must contain `spec` and `merge`                            |
| `agent_command` | strlist | the spec's Claude Code template | not empty; `{prompt}` exactly once; only `{role}`, `{allowed_tools}`, `{prompt}`, each a whole element |
| `forge`         | str     | `"github"`                      | `"github"` or `"git"`                                                                                  |
| `gate_retries`  | int     | 2                               | `_between(0, 5)`                                                                                       |

`pipeline.py` keeps its own `PIPELINE_RULES`, as `run.py` does for `[runner]`, and a test feeds both validators the same values. It also reads `gates.base_ref`, `gates.python_command` and E18's `jobs.lease_minutes`.

## Test seams

- **The checks, in-process** (T1): temp git repos built by `tests/_pipeline.py`, with commits made to pass or to break one condition at a time. Each condition of each stage gets a passing case and a failing case (AC-04). Mutation scoring comes mostly from these: they're fast, and every condition is a branch.
- **Pure functions** (T1): `allowed_tools` for every core card, pinned in full for `implementer`, `verifier` and `docs-writer`. Also `session_argv` with a hostile prompt (spaces, quotes, `--flag`) staying one argument, `prompt` pinned in full for one stage, and the config rules against `config_schema` (AC-07, AC-18).
- **`pipeline.md`** (T1): a test parses its stage table and compares it with `STAGES` (AC-19).
- **The driver, in-process** (T2, T3): `Driver(record, config, runner=FakeRunner, jobs=FakeJobs, forge=FakeForge, clock)`.
  - `FakeRunner` runs each sent command at once, in a real temp worktree, with the real `fake_agent.py`, and records turns and usage. `FakeJobs` keeps leases in memory and can be set to refuse.
  - These cover stage order (AC-05), resuming after a crash between record and send (AC-06), cost and warnings (AC-08), every way to need a human (AC-09), resume and cancel (AC-10), checkpoints (AC-11), gate retries (AC-12), review (AC-13), docs (AC-14), ship (AC-15), merge (AC-16) and learn (AC-17).
- **The real ports** (T2, T3): `Runner` against a real `run.py --daemon` subprocess, and `Jobs` against the real `jobs.py`, in temp repos (slow). `GitForge` against a local bare origin. `GitHubForge` with a stub `gh` on `PATH` that records its argv and answers with canned JSON, so no network is used and the REST paths are pinned.
- **Plumbing commits** (T2): approve on a branch that moved between read and update is refused, and the branch's history is unchanged. The new status line passes `docs.py check`.
- **The done-when** (T4, AC-20): `tests/test_pipeline_end_to_end.py`, marked slow, on three OSes. It sets up a real daemon, the real `jobs.py`, `GitForge`, a bare origin and `fake_agent.py` as `agent_command`, then runs a two-task job from `new` to `done`, with approvals by command and merges made by the test. Four more runs cover a red-then-fixed gate, a blocker finding, a rejected spec and a closed PR.
- **The fake agent:** `tests/fixtures/pipeline/fake_agent.py` reads `FACTORY_ROLE`, the prompt (last argument) and `FAKE_AGENT_SCRIPT`, a JSON file mapping `role` or `role@task` to actions: write a file, run `state.py` or `agents.py lock`, commit, exit with a code. It prints `{"total_cost_usd": 0.01}`. It writes the spec, design and task files, the tests and lock, the implementation, findings, the changelog entry and the PR body (by running `evidence.py` and filling the placeholders), so every check runs on real files.

## Vertical slices

| Task | Slice                                                                                                                                                                                                                                                | ACs                                                    |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| T1   | The stage machine: `STAGES`, the nine checks and `pipeline.py check`, the record format, the allow-list, session argv and prompt, `[pipeline]` config, `pipeline.md`, `CHANGELOG.md`, the kit files and this repo's install. No E18 needed.          | AC-01, AC-04, AC-07, AC-18, AC-19                      |
| T2   | The driver for the plan: `new`, `status`, `run` through spec and design, E18 lease and beats, cost, needing a human, `resume`, `cancel`, the checkpoints with `approve` and `reject` and their plumbing commits. **Starts after E18-T1 has merged.** | AC-02, AC-03, AC-05, AC-06, AC-08, AC-09, AC-10, AC-11 |
| T3   | The slice stages: test, build, the gate with Debugger retries, review with findings commits, docs, ship with both forges, merge detection, the next slice from the fetched base, and learn                                                           | AC-12, AC-13, AC-14, AC-15, AC-16, AC-17               |
| T4   | The done-when test on three OSes, E13 AC coverage, then the live run on #82 with Claude Code; the closing PR links its record, summary and PRs                                                                                                       | AC-20, AC-21, AC-22                                    |

Each slice ships on its own:

- **T1** gives people and sessions a `check` that says whether a stage is done, and the docs that describe the track.
- **T2** drives a job to an approved spec and design.
- **T3** drives each slice to a merged PR.
- **T4** proves the whole line, live.

## Changes

- **21 Nov 2026, after acceptance, aligned with E18's accepted design:** the pipeline record is E18's sidecar `work/<job>.pipeline.toml`, not a `work/<job>/` folder. The summary is a second sidecar, `work/<job>.summary.toml`. Request, gate reports and PR bodies live inside the record. Scratch files live in the runner worktree's git dir. The `Jobs` port uses E18's pinned Python API rather than its command line, and the E18 status is `blocked` while awaiting approval or a merge.
- **21 Nov 2026, while building T2:**
  - Each `[[sessions]]` entry also records its `attempt` and its full `argv`, so a crash between writing it down and sending it can resend exactly the same command.
  - `reject` and `resume` raise the record's `attempt`, so a stage reruns all its sessions, and the prompt carries that attempt's note.
  - `[[runs]]` entries record `closed`.
  - The spec stage's prompt carries the request text, since a session can't read the job's sidecar outside its worktree.
  - The driver renews the lease before every write of the record, so a session longer than the lease never loses it.
  - Until T3, a job that reaches the gate, review, docs, ship or learn stage stops for a human.
- **21 Nov 2026, while building T3:**
  - `Forge.state` also takes the pushed head commit: the plain-git forge checks that commit against `origin/<base>`, because the branch may be gone once it has merged.
  - The docs-writer has no shell, so the driver commits what it changed, as it does the reviewers' findings. The commit is sent through a small internal command, `pipeline.py _commit MESSAGE -- PATH...`, which commits only when something under the paths changed.
  - The review round is set with `state.py task set <task> --round 1` as a runner command, and committed like the findings.
  - `[[tasks]]` entries also record the pushed `head`, the attempt the PR was `opened` for, and the task's committed `findings` (as JSON), for merge detection and the summary.
  - `gate-report.json` in the scratch folder hands the newest gate report to the Debugger and the Integrator, as `$FACTORY_GATE_REPORT`, even in a new segment's worktree.
  - The GitHub forge reads origin's configured URL (`git config remote.origin.url`), not `git remote get-url`, so an `insteadOf` rewrite doesn't hide which repository it is.
  - A gate report's failing checks are named from each check's `profile` and `check`, as `gate.py --json-out` writes them. The stage check read a `name` key, which real reports don't have.
- **23 Nov 2026, while building T4 (the product owner's decision of the same day):**
  - After the session of a role without a shell, the driver commits what it left in the tree, with `pipeline.py _commit "docs(<EPIC>): <stage> from the <role>" -- .`. This covers the spec-writer and the architect, which can't commit. A tree still dirty after that commit stops the job for a human. A failed session's files are never committed.
  - `has_shell(root, role)` reads the role's card: `run` with no `[scope].run` is a shell. The reviewers' scoped `run` isn't one, so their findings are still committed as before.
  - The done-when test, `tests/test_pipeline_end_to_end.py`, installs the kit with `install.py` into its temp repo and runs the installed `pipeline.py` and `run.py --daemon` as commands.
- **26 Nov 2026, the product owner's decisions after the live run (#109, E13-T8, ADR 0047):**
  - **The Debugger's stop.** After each Debugger session in the gate stage, `_gate` reads the task file in the worktree. An open blocker finding that the gated commit's task file didn't have stops the job, with the findings in the reason, and the Debugger's `[[sessions]]` entry records their ids as `blockers`. A finding left uncommitted is committed first, with `chore(<task>): the debugger's blocker findings`.
  - **Relock approval.** `approve <job> relock --task <id> --by <name> [--files f...]` claims the lease, checks the job is `needs-human` at a slice stage, and reads the lock record and files on the slice's last branch with `git show`, to default `--files` and refuse a change that isn't approved. It appends a `[[decisions]]` entry with `checkpoint = "relock"`, `lock_task`, `files` and `findings` (the Debugger's `blockers`), raises the attempt, and sets the job `ready`. It writes no branch.
  - **The relock step.** At the start of a slice step, a relock decision for the current attempt runs first, as driver commands marked `relock` in their `[[sessions]]` entries: `agents.py lock --replace` (role `relock`), one `state.py finding set <task> <id> --status fixed` per finding (role `finding`), and `_commit "test(<task>): relock approved by <name>"` over the lock record and the task file. The hash check runs in the driver, on the new segment's worktree, before the lock command, so a refusal writes nothing. The stage's own plan never sees the marked sessions, so it reruns from its start.

## Risks

- **E18's interface isn't merged yet.** T2 uses only `jobs.py new`, `claim`, `beat`, `release`, `set` and `show`, from E18's approved spec, behind the `Jobs` port. If E18-T1's command lines differ, only `CliJobs` changes. T1 doesn't touch E18 at all, so it can merge first.
- **E18's sidecars.** E13 writes only `work/<id>.pipeline.toml` and `work/<id>.summary.toml`, through `jobs.write_sidecar`, and creates no folders under `work/`. Gate reports and PR bodies are copied into the record, so a large report makes the record larger: a few tens of KB a gate run, which is fine for TOML.
- **The E16 time cap.** A runner job's timeout counts waiting, so the driver ends a segment at every wait point. A single long slice (nine sessions, gate retries) could still pass the default 120 minutes. The halt then makes the job `needs-human`, and `resume` carries on in a new segment from the branch. This repo can raise `runner.job_timeout_minutes` for the live run.
- **The E16 turn cap.** A slice uses about 20 turns: six reviewers, up to six findings commits, the gate and its retries, docs, ship and push. That's inside the default 50. Each segment gets a fresh count.
- **Headless agents are less reliable than a supervised session.** Every stage ends in a deterministic check, so a session that claims success without the files fails its check and stops for a human. The live run (T4) is where the prompts get tuned.
- **Claude Code flags change between versions.** `--permission-prompts` needs v2.1.259 or later, and this machine has 2.1.330. The template is config, so a repo can adjust it without a kit change. T1 records the version it was checked against in `pipeline.md`.
- **Writing outside the worktree.** The Integrator has no edit tools. It writes `FACTORY_PR_BODY` (in the worktree's git dir, so the gate's tree stays clean) through `evidence.py --out` and its shell. That is allowed by its bare `Bash` rule, and the E03 hook checks it.
- **Mutation and slow tests.** The end-to-end and real-port tests are marked `slow`. The in-process check and driver tests have to reach the 60% changed-lines threshold on their own.
- **E01 and the kit list change.** The test commits update `tests/_repo.py` KIT_FILES and E01's expected default config, and the PRs flag it.
