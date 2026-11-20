# E16 · Machine daemon and worktrees design note

Spec: [E16 spec](../specs/E16-machine-daemon-worktrees.md) · Issue: [#16](https://github.com/michael-muir/software-factory/issues/16)
Status: **Accepted by the product owner, 19 Nov 2026** · ADRs: [0030](../adr/0030-runner-state-is-files-in-the-git-common-directory-claimed-by-atomic-operations.md) · [0031](../adr/0031-a-halt-kills-the-commands-session-on-posix-and-its-job-object-on-windows.md) · [0032](../adr/0032-a-job-is-a-worktree-and-a-stream-of-commands-driven-by-one-polling-loop.md)

## Summary

There is one kit module, `.factory/runner/run.py`, standard library only, with four parts:

1. **The store** (ADR 0030): every file under `<git-common-dir>/factory/`. Each state change is an atomic `mkdir`, exclusive create, `rename` or `replace`, so the CLI commands and any number of daemons can share it without locks.
2. **The CLI:** `submit`, `send`, `close`, `usage`, `cancel`, `status` and `stop`. Each one does a single store operation and exits.
3. **The daemon** (ADR 0032): one polling loop, `Daemon.tick(now)`. It claims requests, makes worktrees, runs commands one at a time per job, enforces the caps, and ends jobs by the result rule.
4. **The process tree** (ADR 0031): `Tree.start`, `poll` and `kill`. It uses a new session on POSIX, and a Job Object behind a small host process on Windows.

A halt is one function, whatever its cause: a cap, `cancel` or `stop`. It kills the tree, records the reason, drops the queued commands, writes a handoff with the worktree's own `state.py`, and keeps the worktree.

## Source layout

```text
kit/.factory/runner/run.py             # store, CLI, Daemon, Tree, config reading; CLI: run.py --daemon | submit | send | close | usage | cancel | status | stop | _host
factory_installer/config_schema.py     # + [runner]: max_turns, job_timeout_minutes, max_parallel, worktree_root
.agentic/config.toml                   # this repo gains [runner]
.factory/runner/run.py                 # this repo's install of the kit file
tests/_runner.py                       # temp repos with a commit and the kit, a fake Tree, pid liveness, wait-until helpers
tests/fixtures/runner/tree.py          # starts a child and a grandchild (optionally orphaned), writes their pids, waits
tests/test_runner_*.py                 # one file per slice
pyproject.toml                         # + kit/.factory/runner in pythonpath, coverage source and mypy files
```

## The store

All paths are under `<git-common-dir>/factory/` (ADR 0030).

```text
queue/<id>.toml                 # a request waiting to be claimed
jobs/<id>/request.toml          # the claimed request (renamed from the queue)
jobs/<id>/job.toml              # the record: written only by the job's claimer
jobs/<id>/commands/0001.toml    # commands sent with `send` (a one-command job's argv is in the request)
jobs/<id>/logs/0001.log         # stdout and stderr of command 1
jobs/<id>/usage/*.usd           # one file per `usage` report
jobs/<id>/closed, cancel        # markers
claims/<sha256 of path>         # a worktree claim, holding the job id
stop                            # the time `run.py stop` was run
rejected/<name>, <name>.job.toml # a hand-dropped request whose file name isn't a job id, and its record
```

**The request:**

| Field       | Meaning                                     |
| ----------- | ------------------------------------------- |
| `version`   | Always `1`.                                 |
| `id`        | The job's id.                               |
| `base`      | The git ref the worktree starts from.       |
| `task`      | The `state.py` task the job works on.       |
| `open`      | Whether more commands may come with `send`. |
| `commands`  | A list of argv lists: 0 or 1 at submit.     |
| `submitted` | When it was submitted.                      |

**The record** (`job.toml`) holds the spec's AC-04 fields:

- `id`, `status`, `reason`
- `base`, `branch`, `worktree`, `task`, `open`
- `created`, `started`, `finished`
- `turns`, `usd`, `warnings`
- `daemon`, naming the daemon that claimed the job (host, process id and a random suffix)
- a `[[commands]]` table per command: `argv`, `exit_code`, `started`, `duration_s`, `log`

`status` recomputes `usd` from the usage files, so late reports show. `--json` prints the same data as JSON.

**Ids:**

- **Generated** ids are `j<yymmdd>-<hhmmss>-<4 hex>`, in UTC, with the date and time joined to the `j`. That's 19 characters, inside the spec's pattern.
- **Given** ids (`--id`) must match `[a-z0-9][a-z0-9-]{0,39}`.
- **Reservation:** `os.mkdir(jobs/<id>)` reserves the id, so a duplicate exits 2.

**Repo paths:**

- **The main worktree** is the first entry of `git worktree list --porcelain`.
- **The config** comes from the main worktree's `.agentic/config.toml`. If there's none, the defaults apply.
- **`worktree_root`:** empty means `<main-parent>/<main-name>.worktrees`. A relative value is taken from the main worktree.

## The daemon loop

`Daemon(store, config, tree_factory, clock)`. `run()` calls `tick(clock())` about every 0.2 seconds, until a stop file is later than the daemon's start or Ctrl+C raises `KeyboardInterrupt`. Then it halts every running job with `daemon stopped` and returns 0.

Each `tick`:

1. **Claim** queued requests, oldest `submitted` first, while fewer than `max_parallel` jobs are running here. A request that fails to parse or validate gets a `failed` record naming the problem (AC-05).
2. **Start a job:**
   - claim the worktree path;
   - run `git worktree add -b factory/<id> <path> <base>`;
   - set `running` and `started`.

   A claim clash fails the job and names the path. A bad base also fails it; the claim is then released and the partial branch and worktree are removed.

3. **For each running job:**
   - **Cancel:** a `cancel` marker halts it with `cancelled`.
   - **A finished command:** record its exit code and duration. For a one-command job, a non-zero exit ends the job `failed`.
   - **Usage:** sum the usage files. At `per_job × warn_at`, add the warning once. At `per_job × halt_at`, halt with `cost cap ($15.00)`.
   - **Time:** at `job_timeout_minutes` since `started`, halt with `time cap (120 min)`.
   - **Turns:** with `turns == max_turns`, and either a command still queued or the job still open, halt with `turn cap (50)`.
   - **Next:** if nothing is running, start the next command. Its argv comes from the request, or from the lowest unrun `commands/` file. It runs in the worktree with `FACTORY_JOB=<id>`, and its output goes to its log.
   - **The end:** when the job is closed and no command is left, it ends by the result rule (AC-11). On success: `git worktree remove <path>`, without `--force`. If that's refused, keep the worktree and note why. Otherwise release the claim.

**The handoff on halt:**

- **Which `state.py`:** the runner uses the worktree's own `.factory/state/state.py`, run with `sys.executable`, and gives it `--root <worktree>`.
- **The task:** if `.agentic/tasks/<task>.md` is missing, the runner first runs `task new <task> "Runner job <id>"`.
- **The note:** then it runs `handoff <task> --from runner --body-file <jobs/<id>/handoff.md>`. The body's `## Done` lists the commands and exit codes, the turns and the cost. `## Next` gives the reason, the worktree, the branch, and how to start a follow-up job from the branch. `## Open questions` is "none".
- **Failure:** any non-zero exit from `state.py` puts `handoff: <stderr tail>` into the record's warnings. The halt stands.

**`cancel` on a queued job:** `cancel` itself tries the queue rename. If it wins, it writes a `halted` record with `cancelled`, and notes that no worktree existed, so no handoff was written. If it loses, it writes the marker and the daemon halts the job.

## Process trees (ADR 0031)

`Tree` has three methods:

- `start(argv, cwd, env, log_path)`
- `poll() -> int | None`
- `kill()`, which waits up to 10 seconds for the tree to go.

The parts:

- **POSIX:** `Popen(..., start_new_session=True, stdin=DEVNULL, stdout=log, stderr=STDOUT)`. A kill is `os.killpg(pgid, SIGKILL)`, then a wait.
- **Windows:** `Popen([sys.executable, run.py, "_host", ...argv], creationflags=CREATE_NEW_PROCESS_GROUP, stdin=PIPE, stdout=log, stderr=STDOUT)`. Then:
  1. create a Job Object with `KILL_ON_JOB_CLOSE`;
  2. `OpenProcess` the host;
  3. `AssignProcessToJobObject`;
  4. write `go\n`.

  The host reads the line, runs the command, and exits with its code. A kill is `TerminateJobObject`. If any `ctypes` call fails, the fallback is `taskkill /T /F`, plus a warning in the record.

- **`ctypes` types:** every `kernel32` call is declared with `argtypes` and `restype`, so 64-bit handles aren't truncated.

## Config

The `[runner]` keys go in `config_schema.SECTIONS`, after `[adapters]`:

| Key                   | Kind   | Default | Rule                 |
| --------------------- | ------ | ------- | -------------------- |
| `max_turns`           | int    | 50      | `_between(1, 10000)` |
| `job_timeout_minutes` | number | 120     | `_positive`          |
| `max_parallel`        | int    | 2       | `_between(1, 64)`    |
| `worktree_root`       | str    | `""`    | no check             |

`run.py` has its own `RUNNER_RULES`, and reads `[budgets]` for the cost cap. A test feeds the same good and bad values to both validators, and expects the same verdicts. An invalid config makes `--daemon` exit 2 and name the key.

## Test seams

- **In-process CLI:** `run.main([...])` in temp git repos (`tests/_runner.py`: `git init`, one commit, and the kit's `state.py` with a valid `.agentic`). The tests check:
  - ids, duplicates and atomic queue files (AC-02);
  - `send` and `close` refusals (AC-03);
  - `status --json` fields (AC-04);
  - usage arithmetic with `Decimal` (AC-14);
  - exit codes 0, 1 and 2 (AC-01).
- **In-process daemon:** `Daemon.tick(now)` with a fake clock and a `FakeTree`, whose processes finish, fail or hang on command. This is how most of the loop gets fast, deterministic tests, and it's what lets the mutation gate's "not slow" suite kill mutants in `run.py`:
  - first come, first served, and `max_parallel` (AC-06);
  - the result rule (AC-11);
  - each cap's boundary, such as the turn cap exactly at `max_turns` (AC-13 to AC-15);
  - the halt's order of steps (AC-16).
- **Real worktrees:** `tick` with the real `Tree` and real `git`, in temp repos:
  - worktree add and remove, and uncommitted changes blocking the remove (AC-09, AC-10);
  - a claim clash (AC-09);
  - a handoff that `state.py check` accepts (AC-16).
- **Subprocess daemons:** `python .factory/runner/run.py --daemon` as a real process, marked `slow`:
  - pickup within 2 seconds (AC-06);
  - `stop`, and Ctrl+C via `SIGINT`, POSIX only (AC-07);
  - two daemons on one queue (AC-08);
  - the done-when tests (AC-12, AC-18);
  - one run under `-I -S` (AC-01).
- **Process trees:** `tests/fixtures/runner/tree.py` writes the pids of itself, a child and a grandchild. In orphan mode, the child exits first. After `Tree.kill()`, `tests/_runner.alive(pid)` must be false for all of them within 10 seconds (AC-17). `alive` uses `os.kill(pid, 0)` on POSIX, and `OpenProcess` with `GetExitCodeProcess` on Windows. A second job's tree, running at the same time, must survive.
- **Config:** `install.py check` with good and bad `[runner]` values, the default render, and the pinned agreement with `RUNNER_RULES` (AC-19).

## Vertical slices

| Task | Slice                                                                                                                                                                     | ACs                                             |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| T1   | The store and CLI: `submit`, `send`, `close`, `status`, ids, requests and records; `[runner]` config; the kit file and this repo's install                                | AC-01, AC-02, AC-03, AC-04, AC-19               |
| T2   | The daemon and worktrees: the loop, claims, worktree add and remove, running commands with logs, the result rule, malformed requests, two daemons, the worktree done-when | AC-05, AC-06, AC-08, AC-09, AC-10, AC-11, AC-12 |
| T3   | Halting: the process tree on three OSes (session, Job Object, host), the halt function and its handoff, `cancel`, `stop` and Ctrl+C                                       | AC-07, AC-16, AC-17                             |
| T4   | Caps: turns, the usage ledger, the cost warning and cap, time; the caps done-when; dogfooding in CI and E16 AC coverage                                                   | AC-13, AC-14, AC-15, AC-18, AC-20               |

Each slice ships on its own:

- **T1** queues jobs that a later daemon will run.
- **T2** runs them, with no caps yet.
- **T3** adds a safe stop.
- **T4** adds the caps.

## Risks

- **Windows Job Objects through `ctypes`** are the least familiar part. T3 tests them on CI's Windows runner, inside GitHub's own job, so nesting is exercised. The `taskkill` fallback keeps the runner working if assignment fails, and it records a warning, so the failure isn't silent.
- **Flaky timing tests.** The subprocess tests poll for a state with a deadline (the spec's 2 and 10 seconds, with headroom on CI), rather than sleeping. Most loop logic is covered by `tick` with a fake clock, which never sleeps.
- **Slow tests and the mutation gate.** Real-daemon tests are marked `slow`, so the mutation kill suite skips them. The `FakeTree` and fake-clock tests have to cover the decisions in `run.py` well enough to reach the 60% threshold on changed lines.
- **Coverage of subprocesses.** The coverage patch for subprocesses doesn't apply under `-I -S`. Only the one AC-01 test uses `-I -S`; the rest run `run.py` with the plain interpreter, so coverage counts them.
- **Windows file sharing.** `os.replace` over a record that a reader has open can fail. The writer retries for up to a second, and readers open, read and close at once.
- **ADR numbers.** The orchestrator has given E16 the block 0030 to 0039, and E08 has 0025 to 0029, so the two branches don't clash. Until E08 merges, the folder has a gap at 0025 to 0029.
- **`state.py` in a worktree** may be missing or invalid, for example if the base predates the factory. The halt still stands, and the record says why (AC-16).
