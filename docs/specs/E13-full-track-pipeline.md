# E13 · Full-track pipeline — Spec

Issue: [#13](https://github.com/michael-muir/software-factory/issues/13) · Milestone: M2 · One job, end to end · Depends on: E08 (done), E12 (done)
Status: **Approved by the product owner, 21 Nov 2026** · Next: Architect design note and ADRs, then failing tests per AC

## Goal

The factory has its parts: the roles (E09), the skills (E10), the gate (E05), PR evidence (E08), the tool adapters (E12), the state files (E02) and the runner (E16). So far a person or a session puts them together by hand. E13 joins them into one pipeline. A job on the full track goes through nine stages: spec, design, test (lock), build, gate, review, docs, ship and learn. Each stage is done by the role that owns it, running headless in its own session, and the stage only passes when checks run as code accept its output. People do two things: they approve the spec, and they merge the PR. E13 delivers:

- **`.factory/workflow/pipeline.md`:** the full track described for people. It covers each stage's role, skill, inputs, exit check and hand-off, and the human checkpoints.
- **`.factory/workflow/pipeline.py`:** a standard-library tool with two parts.
  - **A stage machine.** It decides from files alone whether a stage has passed.
  - **A driver,** `pipeline.py run <job>`. It runs each stage's role headless as commands on an E16 open job, and stops at each human checkpoint.
- **A `[pipeline]` config section:** the checkpoints, the agent command template, the forge and the number of gate retries.
- **A live run.** One real issue goes through the pipeline in this repo. The product owner approves the spec and merges the PR.

E13 runs one job through one track. E14 adds the review loop, E15 the lite track, E17 the merge-risk rating, E18 the job index, and E19 a router that runs many jobs at once. All of them build on the stages, the job record and the stage checks defined here.

**Done when:** one job runs end to end with human spec approval and merge (PRD).

## Decisions in force (product owner, 21 Nov 2026)

| Topic       | Decision                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Build       | **`workflow/pipeline.md` and a standard-library `.factory/workflow/pipeline.py`.** It has a deterministic stage machine that checks each stage's exit conditions from files. It also has a driver, `pipeline.py run <job>`, that runs each stage's role headless on an E16 open job and stops at the human checkpoints.                                                                                                                                                                                                                                                          |
| Runtime     | **Claude Code first:** `claude -p --agent <role>` with JSON output, reporting its cost to `run.py usage`. The command sits behind a template in config, so another tool can replace it. Tests use a scripted fake agent.                                                                                                                                                                                                                                                                                                                                                         |
| Checkpoints | **Spec and merge by default,** as a configurable list, `pipeline.checkpoints`. Design acceptance is opt-in, and this repo turns it on. Approvals are recorded with `pipeline.py approve <job> <checkpoint> --by <name>`, which also updates the document's status line. The merge checkpoint passes when the pipeline sees that a human has merged the PR.                                                                                                                                                                                                                       |
| Slices      | **One job is one spec.** Each slice gets its own E16 job, its own branch and its own PR. The next slice starts only after the last one has merged.                                                                                                                                                                                                                                                                                                                                                                                                                               |
| Review      | **The Verifier, then each of the five reviewers once.** Each runs in its own session and records findings through `state.py`. Any open blocker or major finding stops the job for a human. E14 adds the loop.                                                                                                                                                                                                                                                                                                                                                                    |
| Proof       | **A test, then a live run.** A CI test with scripted fake agents takes a job through all nine stages on Ubuntu, macOS and Windows, using a local bare repository as the origin for the merge. Then one live run through Claude Code on a small real issue (#82 is suggested), where the product owner approves the spec and merges.                                                                                                                                                                                                                                              |
| Settled     | These come from the sources and weren't asked:<br>- **Stages:** the stage names and order (PRD, `state.py` PHASES).<br>- **Roles and skills:** the owner of each stage and its skill (E09, E10).<br>- **Tests:** locked before implementation (E03).<br>- **Pass/fail:** the gate decides (E05).<br>- **PR bodies:** drafted by `evidence.py` and checked with `check-pr --strict` (E08).<br>- **Where jobs run:** E16 worktrees under E16's caps.<br>- **Merging:** never automatic.<br>- **Code:** standard library only, Ubuntu, macOS and Windows.<br>- **ADRs:** 0040–0049. |

## In scope

- `pipeline.md`, and `pipeline.py` with these commands: `new`, `run`, `check`, `approve`, `reject`, `resume`, `cancel` and `status`.
- The job's pipeline record, kept beside E18's job record and keyed by its id, and the job summary written at the learn stage.
- Claiming the job with E18's lease while the pipeline writes, and keeping the E18 job's phase, task, branch, worktree and status current.
- A list of every stage, its role, its skill and the check that decides whether it passed.
- The prompt the driver gives each role, the agent command template, and reporting each session's cost to the runner's ledger.
- The human checkpoints for the spec, the optional design acceptance and the merge, and the status lines that approvals write.
- The ship stage. The driver checks the Integrator's PR body with `check-pr --strict` and opens the PR through GitHub's REST API (`forge = "github"`). For tests, a plain-git forge pushes to a local bare origin (`forge = "git"`).
- Finding out that a PR has merged, on each forge.
- The `[pipeline]` config section and its checks in `install.py check`.
- `CHANGELOG.md` in this repo, with a `## [Unreleased]` section for the docs stage.
- Shipping the pipeline in the kit, installing it into this repo, the fake-agent test, and the live run.

## Out of scope

- **E14:** review rounds after the first, the fix-and-re-review loop, round limits per track, and strict reviewer isolation (a reviewer that can't read another reviewer's findings).
- **E15:** the lite track and pass-through jobs. E13 accepts only `track = "full"`.
- **E17:** the merge-risk rating, and routing by it.
- **E18:** the job record itself, the SQLite index, leases and heartbeats, and handing a job over after a crash. E13 uses E18's `jobs.py` for all of them.
- **E19:** running several pipeline jobs at once, the Router session, and a `delegate` tool that lets one agent start another.
- **E20:** mapping `model_hint` and `different_from` to real models. Every role runs on the agent command's default model.
- **E21:** the daily budget and real metering beyond the cost the agent reports.
- **E22:** finding stalled or dead daemons. E13 waits on the runner and trusts its caps.
- **E24:** taking requests from GitHub issues and replying in their threads. A job starts from the command line, from a request file or an issue number.
- **E28:** running Retro on each job. E13 only writes the summary that E28 reads.
- **Built-in templates for other tools:** agent command templates for Copilot or Cursor. The template is configurable, but only Claude Code's is shipped and tested.
- **Changes requested on an open PR.** A review on GitHub that asks for changes stops the job for a human. E13 doesn't feed it back to the Implementer.

## The stages

| Stage  | Role                                                                                                      | Skill                                                                                               | Where         | Passes when (checked by `pipeline.py`)                                                                                                                                                                                                                         |
| ------ | --------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- | ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| spec   | `spec-writer`                                                                                             | spec-interview                                                                                      | plan job      | `docs/specs/<EPIC>-*.md` exists, is committed, passes `docs.py check` and has at least one AC. Then the `spec` checkpoint.                                                                                                                                     |
| design | `architect`                                                                                               | design-note                                                                                         | plan job      | `docs/design/<EPIC>-*.md` exists, is committed and passes `docs.py check`. There is at least one task file `<EPIC>-T<n>`. Every AC a task names is in the spec, and every AC in the spec is named by a task. Then the `design` checkpoint, if it's configured. |
| test   | `test-designer`                                                                                           | tdd-slices, lock-tests                                                                              | slice job     | The task's lock record is committed. Every AC the task names is tagged in a locked file. No commit on the branch changes a non-test file before the lock commit.                                                                                               |
| build  | `implementer`                                                                                             | tdd-slices                                                                                          | slice job     | At least one commit follows the lock commit, the worktree is clean, and the gate's locks check passes.                                                                                                                                                         |
| gate   | (the driver runs it) `debugger` on red                                                                    | debugging                                                                                           | slice job     | The full gate's JSON report says pass, for the branch's head commit, from a clean tree.                                                                                                                                                                        |
| review | `verifier`, then `spec-reviewer`, `standards-reviewer`, `security-reviewer`, `perf-reviewer`, `adversary` | verify-with-evidence, spec-review, standards-review, threat-check, perf-budget, adversarial-testing | slice job     | All six sessions ran, the task's `review_round` is 1, and the task has no open blocker or major finding.                                                                                                                                                       |
| docs   | `docs-writer`                                                                                             | (none)                                                                                              | slice job     | The branch adds at least one line under `## [Unreleased]` in `CHANGELOG.md`, and the full gate still passes on the new head.                                                                                                                                   |
| ship   | `integrator`                                                                                              | pull-request-evidence                                                                               | slice job     | The PR body passes `check-pr --strict --commits <the branch's commits>`, the branch is pushed, and the PR is open. Then the `merge` checkpoint.                                                                                                                |
| learn  | (the driver)                                                                                              | (none)                                                                                              | main checkout | Every slice has merged. The job summary and the closing handoff are written.                                                                                                                                                                                   |

**Where:** the **plan job** is one E16 open job, `<job>-plan`, on a branch from `origin/<base_ref>`. It holds the spec, the design and the task files. A **slice job** is one E16 open job per task, `<job>-t<n>`. The first slice's branch starts from the plan branch, so its PR carries the spec, the design and the task files too. Every later slice's branch starts from `origin/<base_ref>`, fetched after the slice before it has merged.

## Where things live

| What                            | Where                                                                                                                              |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| The full track, for people      | `.factory/workflow/pipeline.md` (kit file)                                                                                         |
| The tool                        | `.factory/workflow/pipeline.py` (kit file)                                                                                         |
| The job (E18's record)          | `<git-common-dir>/factory/work/<job>.toml`, owned by E18's `jobs.py`                                                               |
| The job's pipeline record       | E18 sidecar `<git-common-dir>/factory/work/<job>.pipeline.toml`: stages, decisions, PRs, the request, each gate report and PR body |
| Job summary and closing handoff | E18 sidecar `<git-common-dir>/factory/work/<job>.summary.toml`, the handoff text inside it                                         |
| Scratch files of a runner job   | the worktree's own git dir, `git rev-parse --git-path factory-pipeline`: never tracked, never dirty, gone with the worktree        |
| Runner jobs                     | E16's own records, ids `<job>-plan` and `<job>-t<n>`, each run with `--task` set to its task                                       |

## New `config.toml` keys

| Key                      | Type            | Default                                                                                                                                                                                 | Rule                                                                                                      |
| ------------------------ | --------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `pipeline.checkpoints`   | list of strings | `["spec", "merge"]`                                                                                                                                                                     | each is `spec`, `design` or `merge`, with no repeats; `spec` and `merge` are required                     |
| `pipeline.agent_command` | list of strings | `["claude", "-p", "--agent", "{role}", "--output-format", "json", "--permission-mode", "acceptEdits", "--permission-prompts", "none", "--allowedTools", "{allowed_tools}", "--", "{prompt}"]` | not empty; contains `{prompt}` once; `{role}`, `{allowed_tools}` and `{prompt}` are the only placeholders |
| `pipeline.forge`         | string          | `"github"`                                                                                                                                                                              | `"github"` or `"git"`                                                                                     |
| `pipeline.gate_retries`  | integer         | 2                                                                                                                                                                                       | 0 to 5                                                                                                    |

This repo's `.agentic/config.toml` sets `checkpoints = ["spec", "design", "merge"]`. Existing configs without `[pipeline]` stay valid, and the defaults apply.

## Acceptance criteria

**The tool and the job record**

- **AC-01** `pipeline.py` runs under `python -I -S` with Python 3.11+ and imports only the standard library. It uses the same exit codes as `run.py`: 0 when the command did what it was asked, 1 when it was refused (a stage check failed, a checkpoint is waiting, or the job is in the wrong state), and 2 for bad input (a bad argument, an invalid config, an unknown job, or not a git repo).
- **AC-02** `pipeline.py new <job> --epic <EPIC> (--request-file FILE | --issue N) [--title T]` creates the job with E18's `jobs.py new` (id `<job>`, `--track full`, task `<job>`), writes the job's pipeline record beside it atomically, and exits 0. An E18 job that already exists with that id and no pipeline record is taken over instead of created, if it's `open` and on the full track.
  - The id matches `[a-z0-9][a-z0-9-]{0,29}`, so every runner id built from it fits E16's limit.
  - The epic matches `E[0-9]+`, and must not have a spec in `docs/specs/` yet.
  - `--issue` reads the issue's title and body through `gh api` (REST) when `forge = "github"`.
  - An id already used in this repo is refused with exit 2.
- **AC-03** `pipeline.py status <job> [--json]` prints the E18 job's fields and the pipeline record. The pipeline record holds at least:
  - the id (the E18 job's), epic, issue and `status`: `ready`, `running`, `awaiting-approval`, `awaiting-merge`, `needs-human`, `cancelled` or `done`
  - `reason`: empty unless the status is `needs-human` or `cancelled`
  - the current stage and current task
  - each task's runner job id, branch and PR
  - each stage that ran: its start and end times, the runner commands it used, and the dollars reported
  - each approval and rejection: who, when, and the note

  `--json` prints the same fields as JSON.

**The stage machine**

- **AC-04** `pipeline.py check <job> [<stage>]` runs the stage's exit check from the table above, on that stage's worktree, and changes nothing. `pipeline.py check <stage> --worktree PATH --epic EPIC [--task TASK] [--base REF]` runs the same check on any checkout, without a job. It exits 0 when the check passes. Otherwise it exits 1 and prints one problem per line, each naming the stage, the file or commit, and what's missing. Each stage's check has a test with a passing case and at least one failing case for each condition in its row.
- **AC-05** The stages run in the table's order, and none is skipped. For each task, test, build, gate, review, docs and ship run in that order, and tasks run in task-id order. A stage starts only after the stage before it has passed its check, and after that stage's checkpoint, if it has one, is approved. The driver can't move a job forward in any other way, and a test shows that a failed check leaves the job where it was.

**The driver**

- **AC-06** `pipeline.py run <job> [--session S]` takes the job from where it stands to the next human checkpoint, or to the end.
  - It first claims the job with E18's lease (`jobs.py claim`), and refuses with exit 1, changing nothing, while another session holds a live lease. It beats (`jobs.py beat`) at least once per `jobs.lease_minutes / 3` while it runs, and releases the lease when it stops. It keeps the E18 job's `phase`, `task`, `branch` and `worktree` current with `jobs.py set`, sets its `status` to `blocked` while the pipeline waits for a human (`needs-human`, `awaiting-approval` or `awaiting-merge`), and to `done` or `cancelled` at the end. Every runner job it submits has `--task` set to one of the job's tasks, so it belongs to the job.
  - It submits the plan job and the slice jobs to the E16 queue with `run.py submit --open --task <task>`, sends each role's session to them with `run.py send`, waits for each command through `run.py status`, and closes each runner job once its stage is over.
  - It exits 0 when it stops at a checkpoint or at the end, and 1 when it stops for a human.
  - Run again, it carries on from the record and never repeats a stage that has passed.
- **AC-07** **The agent command.** For each role session, the driver fills in `pipeline.agent_command`: `{role}` becomes the role's name, `{allowed_tools}` the role's allow-list and `{prompt}` the stage prompt. The command runs with `FACTORY_ROLE=<role>`, so the E03 hook holds the role to its tools and the locks as a second layer, under E16's caps.
  - **The allow-list** is generated from the role's card, as one comma-separated string in Claude Code's permission rule syntax. Each neutral tool maps to E12's Claude Code names (`read` to `Read`; `search` to `Glob`, `Grep`; `edit` to `Edit`, `MultiEdit`, `NotebookEdit`; `write` to `Write`; `web` to `WebFetch`, `WebSearch`). `run` maps to `Bash` and `PowerShell` for a role with no `[scope].run`. For a role with run scopes, it maps to `Bash(<prefix> *)` and `PowerShell(<prefix> *)` for each prefix, in the card's order, and never to a bare `Bash` or `PowerShell`. A test pins the list for `implementer`, `verifier` and `docs-writer`, and checks that every core role's list holds only rules for its own tools.
  - **The prompt** is plain text, the same for the same inputs, and names:
    - the job, stage, epic and task
    - the role's skill
    - the spec, the design note and the task file, by path
    - the human's last rejection note for that stage, if there is one
    - what has to be true for the stage to pass
- **AC-08** **Cost.** When a session's output is JSON with a numeric `total_cost_usd`, the driver reports it with `run.py usage <runner-job> --usd <n>` and adds it to the stage in the record. Output without it adds a warning to the record, and the stage carries on. A runner job halted by any E16 cap stops the pipeline job as `needs-human`, with the runner's reason.
- **AC-09** **A failed stage stops for a human.** When a role's session exits non-zero, or its stage check fails, the job becomes `needs-human`, with a reason that names the stage and the check's problems, and no later stage starts. The gate is the one exception (AC-12).
- **AC-10** `pipeline.py resume <job> [--note TEXT]` sets a `needs-human` job back to `running` and runs the stopped stage again, with the note in the prompt. If that stage's runner job has finished or halted, resume first starts a new runner job from that job's branch (`--base factory/<old-id>`). `pipeline.py cancel <job>` cancels the job's running runner job (E16 `cancel`), and marks the pipeline record and the E18 job `cancelled`. Both commands, and `approve` and `reject`, take E18's lease for the time they write, by AC-06's rules, and refuse with exit 1 while another session holds it. Resuming or cancelling a job that's done or cancelled exits 1 and changes nothing.

**Checkpoints**

- **AC-11** At each configured checkpoint, the job becomes `awaiting-approval` (spec, design) or `awaiting-merge` (merge), and `run` exits 0.
  - **`pipeline.py approve <job> <checkpoint> --by <name>`** records the approval and changes the document's status line, committed on the plan branch:
    - the spec becomes `Status: **Approved by <name>, <d Mon yyyy>** ...`
    - the design note becomes `Status: **Accepted by <name>, <d Mon yyyy>** ...`

    The changed document still passes `docs.py check`.

  - **`pipeline.py reject <job> <checkpoint> --by <name> --note TEXT`** records the rejection. The next `run` sends the stage's role again, with the note.
  - **Refusals:** approving or rejecting a checkpoint the job isn't waiting at exits 1, and so does `approve ... merge`. A merge is never approved by command, only by merging.

**Gate, review, docs and ship**

- **AC-12** **Gate.** The driver itself runs the full gate as a runner command, with `--json-out` to a scratch file, and keeps the report in the pipeline record. On a red report, it sends the `debugger` the report, then runs the gate again, up to `pipeline.gate_retries` times. If the gate is still red, the job stops for a human with the failing checks.
- **AC-13** **Review.** The driver sends the `verifier`, then the five reviewers in the table's order, each in its own session. After each session, the driver commits the task file's findings on the slice branch, because the reviewers can't commit. Then it sets the task's `review_round` to 1. Any open finding of blocker or major severity stops the job as `needs-human`, and the reason lists the findings. Minor findings go on to ship and appear in the PR body.
- **AC-14** **Docs.** The `docs-writer` adds the change's entry under `## [Unreleased]` in `CHANGELOG.md`. If the stage adds a commit, the driver runs the full gate again on the new head before ship. The ship stage uses that report.
- **AC-15** **Ship.**
  - The `integrator` follows the pull-request-evidence skill and writes the filled-in PR body to the path in `FACTORY_PR_BODY`. The driver then checks it with `docs.py check-pr --strict --commits <the branch's commits>`, and a body that fails stops the job for a human.
  - Next the driver pushes the branch and opens the PR, base `<base_ref>`, head the slice branch:
    - **`forge = "github"`:** through `gh api repos/<owner>/<repo>/pulls` (REST, never GraphQL).
    - **`forge = "git"`:** the PR is the pushed branch, with the body kept in the pipeline record.
  - The record keeps the PR's number or branch.
- **AC-16** **Merge.** `run` on an `awaiting-merge` job checks whether a human has merged the PR.
  - **`forge = "github"`:** the REST pulls endpoint says `merged: true`.
  - **`forge = "git"`:** the slice branch's head is an ancestor of `origin/<base_ref>`, after a fetch.

  Until then it exits 0 and changes nothing. A PR that was closed without merging stops the job for a human. Once the PR is merged, the next task starts on a branch from the newly fetched `origin/<base_ref>`.

**Learn**

- **AC-17** After the last task's merge, the learn stage writes the `summary` sidecar, then marks the job `done`.
  - It holds the job, each stage's times and cost, each gate run's verdict, each finding, each PR, and the total cost.
  - Its `handoff` text has `## Done`, `## Next` and `## Open questions`, in E02's handoff form, and says what shipped and what's left.

  `pipeline.py status` shows both.

**Config, kit and docs**

- **AC-18** `install.py check` validates the `[pipeline]` keys by the rules in the table above, and the default config `install.py` writes includes `[pipeline]` with its defaults and comments. A config without `[pipeline]` stays valid. This repo's config turns on the design checkpoint.
- **AC-19** `.factory/workflow/pipeline.md` describes the nine stages, the roles and skills, each stage's exit check, the checkpoints, the commands and the config. A test checks that its stage table matches the stages, roles and skills in `pipeline.py`. The Router card's hand-off and the role cards it names stay consistent with it. This repo gains `CHANGELOG.md` with a `## [Unreleased]` section.

**Done-when and quality**

- **AC-20** **Done-when, in a test,** on Ubuntu, macOS and Windows:
  - **Setup:** a temp repo with the kit installed and a local bare origin. A fake agent, scripted per role, plays every role, and a real E16 daemon runs the commands. The config sets `forge = "git"` and all three checkpoints.
  - **Run:** one job with two tasks goes from `new` to `done`. The test approves the spec and the design by command, and merges each slice branch into the origin's `main` itself.
  - **What it checks:**
    - every stage ran in order for each task
    - the second task started only after the first had merged
    - every PR body passed `check-pr --strict`
    - the cost the fake agent reported reached the record and the runner's ledger
    - the summary lists both PRs
  - **Further runs:** a red gate that the fake debugger fixes, a blocker finding, a rejected spec, and a slice PR closed without merging. Each one stops or carries on as AC-09, AC-11, AC-12, AC-13 and AC-16 say.
- **AC-21** **Live (product owner):** in this repo, one real issue runs through `pipeline.py run` with the default Claude Code agent command, from `new` to `done`. The product owner approves the spec (and the design) with `pipeline.py approve` and merges each PR on GitHub. The live run's record, summary and PRs are linked from E13's closing PR.
- **AC-22** `pipeline.py` is a kit file, installed by `install.py` and listed in the kit layout tests, and this repo commits its install. ruff, `ruff format --check` and `mypy --strict` pass. Every AC above has at least one test tagged `E13-AC-nn`, except AC-21.

## Assumptions (confirmed with approval, 21 Nov 2026)

1. **The docs stage needs `CHANGELOG.md`.** E13 creates it in this repo, in the Keep a Changelog form the release skill reads (`## [Unreleased]`). In a repo with no changelog, the `docs-writer` creates one.
2. **The learn stage writes a record, not a retro.** The job summary and the closing handoff are kept beside the job record, outside git. They're not committed, because committing them would need another PR after the last merge. E28 reads them.
3. **No `delegate` tool.** The driver starts every role, so no agent starts another. E03's deferred `delegate` tool waits for E19.
4. **PRs go through GitHub's REST API, opened by the driver.** I've changed one detail from the interview here. The Integrator drafts and fills in the body, and the driver opens the PR only after the body passes `check-pr --strict`, so the check decides whether a PR opens. Everything uses `gh api` REST; nothing uses GraphQL.
5. **Approvals by command.** `approve` and `reject` are command-line commands for now. E24 adds `/foundry approve · reject · ask` in GitHub threads, using the same record.
6. **The spec interview is asynchronous.** A headless Spec Writer can't ask questions as it goes. It writes the draft spec with its questions as assumptions and options, and the product owner answers with `reject --note` (another round) or `approve`.
7. **The default agent command doesn't bypass permissions** (changed at approval, see Changes). It uses `--permission-mode acceptEdits` and `--permission-prompts none`, with an `--allowedTools` list generated from the role's card (AC-07). Anything else that would prompt is denied. The E03 hook and the E16 caps still apply on top, so there are two layers.
8. **The first slice carries the plan.** The spec, the design and the task files reach main in the first slice's PR, as they have in this repo, not in a separate PR.
9. **There is one job, and E18 owns it** (replaced at approval, see Changes). E18's record, `<git-common-dir>/factory/work/<id>.toml`, with its id and lease, is the job. The pipeline keeps its stages, approvals and PRs in E18's sidecar `work/<id>.pipeline.toml`, beside it and keyed by the same id, written with `jobs.write_sidecar` while holding the lease. The driver claims the job with E18's lease and beats while it runs. E18's T1 (the record, `new`, `claim` and `beat`) merges before E13's driver slice, so E13 builds and merges its stage machine first.
10. **Gate retries.** A red gate gets up to `gate_retries` Debugger sessions (2 by default), each bounded by E16's caps. This is the one automatic retry in E13, and it isn't a review round.
11. **The live run's epic id.** The live job on #82 takes the next free epic id (E31), so its spec and AC tags can't clash with E08's.
12. **Reviewers all run on one model** until E20, so `different_from` isn't honoured yet. Strict reviewer isolation is E14's.

## Changes

- **21 Nov 2026, at approval, by the product owner (assumption 7, AC-07, config):** for security, the default agent command no longer uses `--permission-mode bypassPermissions`. It uses `--permission-mode acceptEdits` and `--permission-prompts none`, with an `--allowedTools` list generated from each role's card: its tools, and its run scopes as `Bash(<prefix> *)` and `PowerShell(<prefix> *)` rules. That is Claude Code's documented rule form (code.claude.com/docs/en/permissions: a space before the trailing `*` gives prefix matching, `:*` is an older equivalent, and a compound command must match each part). The E03 hook and the E16 caps stay on top, so a role is held by two layers. AC-07 gains the allow-list and a test that pins it, and `{allowed_tools}` becomes a template placeholder.
- **21 Nov 2026, at approval, by the product owner (assumption 9, AC-02, AC-03, AC-06, AC-10):** there is one job, and E18 owns it. `pipeline.py new` creates the E18 job, and the pipeline's own record lives beside it (as the sidecar `work/<id>.pipeline.toml`, see the next note). `run`, `approve`, `reject`, `resume` and `cancel` hold E18's lease while they write, and the driver beats while it runs. E13's driver slice waits for E18's T1 to merge. AC-04 also gains a form that checks any checkout without a job, so the stage machine can be built and merged first.
- **21 Nov 2026, after design acceptance, aligned with E18's accepted design (AC-12, AC-15, AC-17, where things live):** E18 keeps other epics' data in sidecar files, `work/<id>.<name>.toml`, written with `jobs.write_sidecar` while holding the lease, and its rebuild knows no `work/<id>/` folder. So the pipeline record is `work/<id>.pipeline.toml`, and the learn stage's summary and handoff are one more sidecar, `work/<id>.summary.toml`. The request, the gate reports and the PR bodies are kept inside the pipeline record. Files a command has to write (the gate's `--json-out`, `FACTORY_PR_BODY`) go to the worktree's own git dir, and the driver reads them into the record. The E18 job's status is `blocked` at the two awaiting statuses too, as E18's design maps them.
- **21 Nov 2026, at approval (assumption 4):** confirmed that the driver opens the PR, and only after the Integrator's body passes `check-pr --strict`.
- **23 Nov 2026, by the product owner, for T4 (AC-13, AC-14, AC-20):** the driver commits whatever a role without a shell leaves behind, at every stage. That takes in the `spec-writer` and the `architect`, which have no `run` tool, as well as the reviewers' findings and the `docs-writer`'s entry. A role with a shell (`run` with no `[scope].run`) commits its own work. So AC-20's fake spec-writer and architect only write their files, as the real ones can. Where the `adversary`'s attack files belong is decided in E14; T4 records what the live run shows.
- **24 Nov 2026, by the product owner, after the live run (AC-07, config):** the default agent command puts `--` before `{prompt}`. Claude Code's `--allowedTools` takes any number of values, so without `--` it read the prompt as a tool name, and the live run's first session exited 1 with no prompt. Built in E13-T5. A config installed before this keeps its own `agent_command` and needs the `--` added by hand.

## Notes for the Architect (design, not requirements)

- The runner already gives each runner job a worktree, a branch `factory/<id>`, caps and a handoff on halt. The driver should only talk to it through `run.py`'s commands (`submit`, `send`, `close`, `usage`, `cancel`, `status --json`), so E23's transport works unchanged.
- E16 removes a worktree when its job succeeds. Close a slice's runner job only after its branch is pushed.
- `claude -p --output-format json` prints one JSON object that includes `total_cost_usd`. Read the command's log from the runner record.
- Keep the forge behind one small interface (open a PR, read a PR's state), so GitLab or Azure can be added later.
- `evidence.py` drafts for one task. One PR per slice keeps that true.
- The record should be written with the same atomic temp-file-and-replace pattern as `run.py` (ADR 0030).
- E01's expected default config and the kit file list change with this epic. Update them in the test commit, and flag it in the PR.
