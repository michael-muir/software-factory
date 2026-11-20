# E16 · Machine daemon and worktrees — Spec

Issue: [#16](https://github.com/michael-muir/software-factory/issues/16) · Milestone: M2 · One job, end to end · Depends on: E05 (done)
Status: **Draft, awaiting product owner approval** · Next: Architect design note and ADRs, then failing tests per AC

## Goal

Agents need somewhere safe to run commands on a real machine: the gate, test suites, builds that need local hardware (an Unreal build machine, in E30), and agent command lines. E16 gives each job its own git worktree and branch, runs the commands sent to it one at a time, and holds every job to a turn cap, a cost cap and a time cap. A job that hits a cap is stopped, its whole process tree is killed, and it leaves a handoff and its worktree behind, so a person or a later session can see what happened. E16 delivers:

- **`.factory/runner/run.py`:** a standard-library command runner. `run.py --daemon` runs in the foreground and works through a file queue. `submit`, `send`, `close`, `usage`, `cancel`, `status` and `stop` talk to it through files.
- **A worktree per job,** in a sibling folder, on its own branch, claimed atomically, so two jobs can never share one.
- **Caps:** turns, cost and time, from a new `[runner]` config section and the existing `[budgets]`.

E16 is the local half of hosting. E23 adds the cloud transport, E22 repairs what a crashed daemon leaves, and E19 decides which jobs to send. All of them build on the queue and the job records defined here.

**Done when:** parallel jobs never share a worktree; caps halt a job (PRD).

## Decisions in force (product owner, 19 Nov 2026)

| Topic                  | Decision                                                                                                                                                                                                                                                                                                                                                                               |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Jobs                   | **An agent-neutral command runner.** A job is a worktree plus the commands sent to it: the gate, tests, builds, or an agent command line. One command is one turn. Cost comes from a per-job ledger that the caller reports to (`run.py usage <job> --usd N`). The daemon checks the caps after every command and every report.                                                        |
| Intake                 | **A file queue on the machine.** `run.py submit` drops a request into a folder inside the git directory, and `run.py --daemon` runs in the foreground, polling it. No network.                                                                                                                                                                                                         |
| Worktrees              | **A sibling folder,** `../<repo>.worktrees/<job-id>` (configurable as `runner.worktree_root`), on branch `factory/<job-id>`. Removed when a job succeeds; kept when it halts or fails, so it can be inspected. E22 cleans up orphans.                                                                                                                                                  |
| Records                | **One TOML file per job** under the git directory, never committed. Worktree claims are made by atomic create, so two jobs can never share one. `state.py` gets no locking: that waits for E18, since each job has its own `.agentic` copy in its worktree.                                                                                                                            |
| Caps                   | **A new `[runner]` section:** `max_turns = 50`, `job_timeout_minutes = 120` and `max_parallel = 2`. The cost cap comes from `budgets.per_job_usd`. A warning goes into the job record at `budgets.warn_at`. At a cap, the daemon kills the job's whole process tree, marks the job `halted` with the reason, writes a handoff in the worktree with `state.py`, and keeps the worktree. |
| Settled by the sources | The runner lives at `.factory/runner/run.py`, standard library only (PRD dependency policy). It works on Ubuntu, macOS and Windows. Job intake stays pluggable, so E23's cloud transport and E30's build machine can feed the same queue.                                                                                                                                              |

## In scope

- `run.py` and its commands: `--daemon`, `submit`, `send`, `close`, `usage`, `cancel`, `status` and `stop`.
- The request format, the job record, the per-job cost ledger and the command logs.
- Creating, claiming and removing worktrees and their branches.
- The three caps, the cost warning, killing a process tree on each OS, and the handoff on halt.
- The `[runner]` config section and its validation in `install.py check`.
- Shipping the runner in the kit and installing it into this repo.

## Out of scope

- The network and cloud transport (E23). E16 has no sockets and no listener.
- Real token and cost metering, and the daily budget (E20, E21). E16 only adds up what callers report.
- Orphan and stall repair (E22): worktrees and records left by a daemon that crashed or was killed.
- The SQLite job index (E18), and any locking in `state.py`.
- Installing the daemon as an OS service (systemd, launchd or a Windows service).
- Choosing which jobs to dispatch, or in what order beyond first come, first served (E19).
- Resuming a halted job in place. A follow-up job can start from its branch with `--base factory/<job-id>`.
- Pruning the `factory/<job-id>` branches of finished jobs.

## Where things live

| What                          | Where                                                                                                |
| ----------------------------- | ---------------------------------------------------------------------------------------------------- |
| The runner                    | `.factory/runner/run.py` (kit file)                                                                  |
| Queue                         | `<git-common-dir>/factory/queue/`                                                                    |
| Job records, ledgers and logs | `<git-common-dir>/factory/jobs/`                                                                     |
| Worktrees                     | `runner.worktree_root/<job-id>`; by default `../<repo>.worktrees/<job-id>`, beside the main worktree |
| Branches                      | `factory/<job-id>`                                                                                   |

`<git-common-dir>` is what `git rev-parse --git-common-dir` prints, so `run.py` finds the same queue from the main checkout and from any worktree. Nothing under it is ever tracked by git.

## New `config.toml` keys

| Key                          | Type    | Default | Rule                                                                                      |
| ---------------------------- | ------- | ------- | ----------------------------------------------------------------------------------------- |
| `runner.max_turns`           | integer | 50      | 1 to 10000                                                                                |
| `runner.job_timeout_minutes` | number  | 120     | greater than 0                                                                            |
| `runner.max_parallel`        | integer | 2       | 1 to 64                                                                                   |
| `runner.worktree_root`       | string  | `""`    | empty means `../<repo>.worktrees`; a relative path is taken from the main worktree's root |

The cost cap is `budgets.per_job_usd × budgets.halt_at`, and the warning is at `budgets.per_job_usd × budgets.warn_at`; with the defaults, $15 and $12. Existing configs without `[runner]` stay valid, and the defaults apply.

## Acceptance criteria

**The runner**

- **AC-01** `run.py` runs under `python -I -S` with Python 3.11+ and imports only the standard library. Run anywhere inside a repo, it works on that repo's git common directory. Exit code 0 means the command did what it was asked. 1 means it was refused (for example, `send` to a job that has finished). 2 means bad input: a bad argument, an invalid config, an unknown job, or a directory that isn't in a git repo with at least one commit.
- **AC-02** `run.py submit [--id ID] [--base REF] [--task TASK] [--open] [-- argv ...]` checks the request and writes it into the queue atomically (no reader ever sees a part-written file), prints the job's id, and exits 0. The id is `ID` if given, else generated. Ids match `[a-z0-9][a-z0-9-]{0,39}`, and an id already used in this repo is refused with exit 2. `--base` defaults to `gates.base_ref`. `--task` names the `state.py` task the job works on, and defaults to the job id. A job submitted without `--open` has exactly the one command given; one submitted with `--open` may have none yet.
- **AC-03** `run.py send <job> -- argv ...` adds a command to an open job, and `run.py close <job>` says no more will come. Both exit 1 for a job that is closed or finished. Commands run one at a time, in the order sent, as argument lists without a shell, with the worktree as the working directory and `FACTORY_JOB=<job-id>` in the environment.
- **AC-04** `run.py status <job> [--json]` prints the job record. The record is one TOML file per job, written atomically, and holds at least: the id, `status` (`queued`, `running`, `succeeded`, `failed` or `halted`), `reason` (empty unless failed or halted), the base, branch, worktree path and task, the created, started and finished times, the turns used, the dollars reported, the warnings, and for each command its argv, exit code, duration and the path of its log. Each command's stdout and stderr go to a log file next to the record. `--json` prints the same fields as JSON.
- **AC-05** A request that is malformed (bad TOML, a bad id, an empty argv, or one dropped by hand in the wrong form) never runs. The daemon gives it a record with status `failed` and a reason that names the problem, and carries on with the next job.

**The daemon**

- **AC-06** `run.py --daemon` runs in the foreground, takes queued jobs first come, first served, and runs at most `runner.max_parallel` jobs at once. It picks up a new request or command within 2 seconds of it being written. It reads the config at start, and exits 2 if the config is invalid.
- **AC-07** `run.py stop`, or Ctrl+C in the daemon's console, stops the daemon. Every running job is halted with reason `daemon stopped`, as in AC-15, and the daemon exits 0. Jobs still queued stay queued for the next daemon.
- **AC-08** Each request is claimed by exactly one daemon, even when two daemons poll the same queue: no job runs twice.

**Worktrees**

- **AC-09** When a job starts, the runner claims its worktree path by an atomic exclusive create, and only then runs `git worktree add -b factory/<job-id> <path> <base>`. A claim that fails, because the path is already claimed or already exists, fails the new job with a reason that names the path, and leaves the other job and its worktree untouched. A base that doesn't resolve fails the job, and leaves no worktree, branch or claim behind.
- **AC-10** When a job ends `succeeded` (by the result rule in AC-11), its worktree is then removed with `git worktree remove` (never forced) and its claim is released; the branch is kept. If git refuses because the worktree has uncommitted changes, the worktree is kept and the record says why.
- **AC-11** **Result rule.** In a job submitted without `--open`, a command that exits non-zero ends the job `failed`. In an open job, a failing command is recorded and the job carries on, because the caller decides what to send next; when the job is closed, it ends `succeeded` if its last command exited 0 and `failed` otherwise. A closed open job with no commands succeeds. A failed or halted job keeps its worktree, branch and claim.
- **AC-12** **Done-when, worktrees.** In a test, 6 jobs are submitted to a daemon with `max_parallel = 2`, and 2 more to a second daemon on the same queue. Each job's command writes its job id and working directory to a file and waits. Every job runs once, in its own worktree, on its own branch; no two jobs ever have the same worktree path; and one daemon never has more than 2 jobs running at once.

**Caps**

- **AC-13** **Turns.** Every command that starts counts as one turn; usage reports don't. When a job has used `runner.max_turns` turns and has another command queued, or is still open, it is halted with reason `turn cap (<n>)`, and no further command runs. A closed job that finishes its last command exactly on the cap is not halted.
- **AC-14** **Cost.** `run.py usage <job> --usd N` adds `N` (a number, 0 or more) to the job's ledger, and exits 0 for any known job, finished or not, so late reports are still counted. Reports made at the same time are never lost: 20 concurrent reports of $0.25 add up to exactly $5.00. When a running or queued job's total first reaches `per_job_usd × warn_at`, one warning naming the total and the cap goes into its record. When the total reaches `per_job_usd × halt_at`, the job is halted with reason `cost cap ($<cap>)`, within 2 seconds, even while a command is running.
- **AC-15** **Time.** A job that has run for `runner.job_timeout_minutes` since it started, counting time spent waiting for commands, is halted with reason `time cap (<n> min)`, within 2 seconds, even while a command is running.
- **AC-16** **Halting.** `run.py cancel <job>` halts a job with reason `cancelled`, and a queued job that's cancelled never starts. Every halt, whatever its cause, does the same things in this order: kills the job's whole process tree (AC-17); sets `status = "halted"` with the reason and the finished time; drops the commands still queued; writes a handoff in the worktree with that worktree's own `.factory/state/state.py handoff <task> --from runner` (creating the task with `state.py task new` first if it doesn't exist), whose `## Done`, `## Next` and `## Open questions` say what ran, why it stopped, and where the worktree and branch are; and keeps the worktree. If the handoff can't be written (for example, the branch has no `.agentic`), the halt still stands and the record says why. Halting a finished job exits 1 and changes nothing.
- **AC-17** **Killing a process tree, on every OS.** When a job is halted while a command is running, the command and every process it started are gone within 10 seconds, on Ubuntu, macOS and Windows. A test checks this with a command that starts a child, which starts a grandchild, all three waiting. It checks it again where the child has already exited and left the grandchild running. On Ubuntu and macOS that is the command's own process group or session. On Windows, where there are no process groups to signal, `taskkill /T /F` alone isn't enough for the second case, because it walks the tree by parent id and an orphan has none; the runner must still end the orphaned grandchild (see the notes). No process of another job, or the daemon itself, is touched.
- **AC-18** **Done-when, caps.** In a test, one job is halted by each cap: turns (with `max_turns = 3` and 4 commands), cost (by `usage` reports while a command runs) and time (with a timeout of a few seconds while a command runs). Each ends `halted` with its reason, has no process left running, keeps its worktree, and has a handoff in that worktree that `state.py check` accepts.

**Config, kit and quality**

- **AC-19** `install.py check` validates the `[runner]` keys by the rules in the table above, the default config that `install.py` writes includes `[runner]` with its defaults and comments, and a config without `[runner]` stays valid. This repo's `.agentic/config.toml` gets the section.
- **AC-20** The runner is a kit file, installed by `install.py` and listed in the kit layout tests, and this repo commits its install. CI runs the runner's tests on Ubuntu, macOS and Windows. ruff, `ruff format --check` and `mypy --strict` pass, and every AC above has at least one test tagged `E16-AC-nn`.

## Assumptions (to confirm with approval)

1. **Commands sent over time.** A job is either one command (`submit -- argv`) or open (`submit --open`, then `send` and `close`), so a cloud session can drive a job one turn at a time. E23 adds the transport for `send`; the file queue is the same.
2. **The result rule (AC-11).** A one-command job fails on a non-zero exit; an open job fails or succeeds on its last command, so a red gate in the middle of an agent loop doesn't end the job.
3. **`cancel` and `stop` (AC-07, AC-16)** are added beside the decided commands. They halt jobs exactly as a cap does, and the tests need them on Windows, where Ctrl+C can't easily be sent to a process.
4. **`max_parallel` counts per daemon.** The design expects one daemon per repo. A second daemon on the same queue is safe (AC-08, AC-09) but runs its own `max_parallel`. Refusing a second daemon needs a liveness check that belongs with E22.
5. **The warning is for cost only.** `warn_at` is a budget setting, so turns and time get no warning, only the halt.
6. **The cost cap is `per_job_usd × halt_at`,** so the existing `halt_at` keeps its meaning. With the defaults, that is $15.
7. **`runner.job_timeout_minutes` is a number,** not an integer, so tests (and builds that should be short) can set a fraction of a minute.
8. **The base defaults to `gates.base_ref`** (`main`), and a halted job's branch can be the base of the next one.
9. **Exit and timing limits.** The daemon picks up work within 2 seconds, and a halt kills the tree within 10 seconds. These are test limits, not settings.
10. **A dead daemon's jobs stay `running`** in their records until E22 repairs them. E16 doesn't try to detect it.

## Notes for the Architect (design, not requirements)

- The gate already kills a tree on timeout (`gate.py` `_execute`: `start_new_session` and `os.killpg` on POSIX, `CREATE_NEW_PROCESS_GROUP` and `taskkill /T /F` on Windows). The runner should share that approach, not invent a second one. For AC-17's orphaned grandchild on Windows, the likely answer is to put each command in a Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` through `ctypes` (standard library), keeping `taskkill /T /F` as the fallback. GitHub's Windows runners already run jobs inside a Job Object, so nested jobs must work (Windows 8 and later).
- On Windows, `os.kill(pid, 0)` doesn't test a process, it ends it: use `OpenProcess` through `ctypes` where liveness is needed.
- How the claims work: exclusive create (`os.open` with `O_CREAT | O_EXCL`) for worktree claims, and an atomic rename from the queue (`os.rename`, which fails on Windows if the target exists) for request claims. Atomic record writes: write a temp file in the same folder, then `os.replace`. On Windows, `os.replace` can fail while another process has the file open, so readers should retry briefly.
- The ledger as an append-only file (one line per report, opened in append mode) avoids a read-modify-write race for AC-14.
- TOML writing: `state.py` already emits TOML with the standard library. Reuse or copy its emitter rather than adding a dependency.
- Keep intake behind one small interface (read a request, claim it), so E23 can add a transport without touching the job loop.
- E01's expected default config and the kit file list change with this epic: update them in the test commit, and flag it in the PR.
