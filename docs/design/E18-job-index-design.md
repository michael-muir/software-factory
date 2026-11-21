# E18 · Job index design note

Spec: [E18 spec](../specs/E18-job-index.md) · Issue: [#18](https://github.com/michael-muir/software-factory/issues/18)
Status: **Accepted by the product owner, 21 Nov 2026** · ADRs: [0050](../adr/0050-one-job-owned-by-the-job-index-a-toml-record-with-sidecars-for-other-epics.md) · [0051](../adr/0051-the-sqlite-index-is-derived-from-files-kept-current-by-write-through-and-rebuilt-in-place.md) · [0052](../adr/0052-leases-and-heartbeats-live-only-in-the-index-whose-write-lock-serialises-record-writes.md) · [0053](../adr/0053-the-runner-reaches-the-index-through-jobs-py-loaded-by-path-and-a-failure-is-only-a-warning.md)

## Summary

There is one new kit module, `.factory/control/jobs.py`, standard library only, with five parts:

1. **Job records** (ADR 0050): one TOML file per job, `<git-common-dir>/factory/work/<id>.toml`. Ids and tasks are reserved by atomic `mkdir` and exclusive create. Sidecar files, `work/<id>.<name>.toml`, are where other epics keep their details about a job. E13's pipeline is the first.
2. **The index** (ADR 0051): `<git-common-dir>/factory/index.sqlite`. It is derived from the files: every write updates it, every read first refreshes the worktree state it answers about, and `rebuild` rebuilds it from the files in one transaction. The schema is versioned by `PRAGMA user_version`, and moves forward by migration.
3. **Leases** (ADR 0052): rows that exist only in the index. Claims, heartbeats and releases are short `BEGIN IMMEDIATE` transactions. The same write lock serialises every write to a job record, so there is no separate lock.
4. **Readers:** the runner's files (E16) and each worktree's `.agentic` (E02), parsed with the kit's own `state.py`. `rebuild`, `list`, `show` and `resume` all read them through the same readers.
5. **The CLI and a small Python API.** The API is stable, so E13's driver and `run.py` call functions rather than parse command output.

`run.py` loads `jobs.py` by path from its own install (ADR 0053). After every runner write it asks the index to refresh that runner job. Its daemon sends heartbeats and renews the leases of the jobs it is running commands for. Any failure there is a warning in the runner job's record, never a failed job, and with no `jobs.py` installed the runner works exactly as it does in E16.

## Source layout

```text
kit/.factory/control/jobs.py        # records, index, leases, readers, resume, CLI and API
kit/.factory/runner/run.py          # + index hooks: refresh after writes, daemon heartbeat, lease renewal (T3)
factory_installer/config_schema.py  # + [jobs]: lease_minutes, daemon_timeout_seconds
.agentic/config.toml                # this repo gains [jobs]
.factory/control/jobs.py            # this repo's install of the kit file
docs/GLOSSARY.md                    # + job, runner job, lease
tests/_jobs.py                      # temp repos (reusing tests/_runner.py), a fake clock, the CLI in-process, a subprocess helper
tests/fixtures/jobs/index-v0.sqlite # an empty version-0 index, for the migration test (T2)
tests/test_jobs_*.py                # one file per slice
pyproject.toml                      # + kit/.factory/control in pythonpath, coverage source and mypy files
tests/_repo.py                      # KIT_FILES gains .factory/control/jobs.py
```

## Job records (ADR 0050)

All paths are under `<git-common-dir>/factory/`, beside the runner's `queue/` and `jobs/`:

```text
work/<id>.toml              # the job record
work/<id>.<name>.toml       # a sidecar, owned by another epic (E13: <id>.pipeline.toml)
work/.ids/<id>/             # reserves the id (os.mkdir)
work/.tasks/<task>          # reserves a task for a live job (O_CREAT | O_EXCL), holding the job id
index.sqlite                # the index
```

**The record:**

```toml
version = 1
id = "job-7"
title = "Rate-limit the public search API"
track = "full"          # full | lite | pass-through (E02's tracks)
phase = "spec"          # E02's phases
status = "open"         # open | blocked | done | cancelled
task = "E31-T1"         # the current task
tasks = ["E31-T1"]      # every task the job has had, in order
branch = ""
worktree = ""
owner = "s-build1-4242-9f3a"   # the session that last claimed it, "" before any claim
created = 2026-11-21T10:00:00Z
updated = 2026-11-21T10:05:00Z

[[claims]]
session = "s-build1-4242-9f3a"
at = 2026-11-21T10:05:00Z
forced = false
from = ""               # the session it was taken from, when forced
```

- **Ids:**
  - A given id must match `[a-z0-9][a-z0-9-]{0,29}`, as E13's does, so a runner id built from it with a suffix of up to 10 characters fits E16's 40.
  - A generated id is `job-<n>`, with `n` one more than the highest generated id in `work/.ids/`. If `os.mkdir` loses a race, it tries the next number.
  - The record is then written to a temp file and published with `os.replace`. A reader that finds an id folder with no record yet skips it.
- **Tasks:** a job holds a reservation in `work/.tasks/` for each task in its `tasks`. A second live job asking for one gets exit 1, and the message names the holder. All of a job's task reservations are released when its status becomes `done` or `cancelled`. `rebuild` never recreates reservations: the files themselves are the truth.
- **Writes:** only `new`, `claim` (including `resume`), `set` and `release` write a record. Apart from `new`, each runs inside the index's write transaction (ADR 0052). Records are written with a temp file and `os.replace`, retried on Windows for up to a second while a reader holds the file, as in `run.py`. TOML is written by a small emitter copied from `run.py`.
- **Validation:** `read_job` checks every field's type and value set. A record that fails gives exit 2 on `show`, and is listed under the index's `problems` by `rebuild` rather than stopping it.

**Sidecars, the extension point:**

- **Name:** `work/<id>.<name>.toml`, where `<name>` matches `[a-z][a-z0-9]{0,19}`. Job ids have no dots, so a sidecar can never be mistaken for a record.
- **Who writes it:** its owning epic, atomically, while holding the job's lease. `jobs.write_sidecar(repo, job_id, name, text, session)` does that check and the atomic write for them. `jobs.py` never reads a sidecar's contents.
- **What the index knows:** each job's sidecar names, found by listing `work/`. `show` and `resume` print their paths, and `--json` gives them as `sidecars = {name: path}`.
- **E13's use:**
  - `pipeline.py new <id>` calls `jobs.new_job(..., job_id=<id>, track="full", task=<first task>)`, claims the job, then writes `work/<id>.pipeline.toml` with its stages, approvals and PRs.
  - Its driver claims the job, beats at least once per stage step, and maps its statuses onto the job's: `needs-human` and the two awaiting statuses become `blocked`, `done` becomes `done`, `cancelled` becomes `cancelled`, and anything else `open`.
  - It registers each slice's task with `set --task`, so the runner jobs for that slice belong to the job.

## The index (ADR 0051)

**Connection:**

- `sqlite3.connect(path, timeout=10, isolation_level=None)`, with explicit `BEGIN IMMEDIATE` for every write.
- The default rollback journal, not WAL. Short transactions are enough at this scale, and there are no `-wal` or `-shm` files to go astray.
- Connections are always closed by a context manager, because Windows keeps an open file in use.

**Tables** (version 1 is T1's; T2 and T3 each add one migration):

| Table         | Rows                                                                                                     | Version |
| ------------- | -------------------------------------------------------------------------------------------------------- | ------- |
| `jobs`        | one per record: every field, `path` and `sidecars` (JSON)                                                | 1       |
| `job_tasks`   | `(task, job)` for every task in every job's `tasks`                                                      | 1       |
| `claims`      | the `[[claims]]` of each record                                                                          | 1       |
| `leases`      | `job` (key), `session`, `minutes`, `acquired`, `expires` (Unix seconds): **live data, not derived**      | 1       |
| `problems`    | a record or file that couldn't be read, and why                                                          | 1       |
| `runner_jobs` | one per E16 job: the record's fields, `daemon`, `belongs_to` (the live job whose `tasks` holds its task) | 2       |
| `commands`    | `(runner_job, n)`: argv (JSON), exit code, started, duration, log                                        | 2       |
| `usage`       | `(runner_job, file)`: `usd` (text, exact decimal), `at` (from the file name's `time_ns`)                 | 2       |
| `worktrees`   | path, branch, head, phase, active task, blockers (from `git worktree list` and `.agentic/STATE.md`)      | 2       |
| `tasks`       | `(worktree, task)`: status, review round, open findings (JSON), newest handoff path and `## Next` text   | 2       |
| `daemons`     | `id` (E16's `host:pid:hex`), host, pid, `started`, `beat` (Unix seconds): **live data, not derived**     | 3       |

**Keeping it current:**

- **Writes:** every `jobs.py` write updates its rows in the same transaction as its lease check. `run.py`'s hooks (T3) call `jobs.refresh_runner(common_dir, runner_id)`, which re-reads that one runner job's files and replaces its rows.
- **Reads:** before answering, `show` and `resume` refresh the job's own record, its runner jobs and the worktree it names. `list` refreshes every record and every worktree. A refresh is one transaction, so a reader never sees half of it.
- **Rebuild:** `rebuild` and migrations run the same code. In one `BEGIN IMMEDIATE`, it deletes every derived row and re-reads every file. The live tables, `leases` and `daemons`, are kept, except for the leases of jobs that no longer exist. The swap is atomic for readers, and there is no `os.replace` of an open database on Windows. The spec's "replaces the old one atomically" is met by the transaction.
- **A damaged index:** a `sqlite3.DatabaseError` on open, or on `PRAGMA quick_check`, which runs only after such an error and never on every open. The tool then moves the file aside as `index.sqlite.damaged-<time>` with `os.replace`, prints a warning, creates a new index and rebuilds it. If the move fails because another process holds the file (Windows), it exits 2 and says to stop the other factory processes and run `rebuild`.
- **Version:**
  - `MIGRATIONS` is a tuple of statement tuples, and the schema's version is its length.
  - On open, a `user_version` higher than that exits 2, naming both versions.
  - A lower one runs, in one `BEGIN IMMEDIATE`: re-check the version, run the missing migrations, set `user_version`, rebuild the derived rows, commit.
  - Version 0 is an empty file.

**Readers:**

- **Runner jobs:** `jobs.py` reads E16's files itself: `queue/<id>.toml`, `jobs/<id>/request.toml`, `job.toml`, `commands/`, `closed`, `usage/*.usd`. It doesn't import `run.py`. A test pins that, for the same jobs, its view equals `run.py status --json`. So if E16's format changes, that test fails, not the index silently.
- **Worktrees:** from `git worktree list --porcelain`. Each worktree's files are parsed with the kit's own `state.py`, loaded by path as `docs.py` does (`state.parse`, `state.task_ids`). The newest handoff per task uses the same order as `state.py resume`.
- **A branch with no worktree** (resume, T4): `git ls-tree -r --name-only <branch> .agentic/`, then `git show <branch>:<path>`, parsed with `state.parse`.

## Leases and heartbeats (ADR 0052)

All times are Unix seconds from `time.time()`. The clock is passed into the API, so tests use a fake one.

- **States**, computed when asked:
  - `done` or `cancelled`: the job's status.
  - `unclaimed`: no lease row.
  - `claimed`: a row with `expires > now`.
  - `crashed`: a row with `expires <= now`. A `release` deletes the row, so an expired row means no one let go.
- **`claim`**, in one `BEGIN IMMEDIATE`:
  1. Refuse a `done` or `cancelled` job.
  2. Read the row. If it's live and belongs to another session, refuse with exit 1, unless `--force` is given.
  3. Upsert the row: `expires = now + minutes × 60`, with `minutes` from `jobs.lease_minutes`.
  4. Rewrite the record with `owner` and a new `[[claims]]` entry. A claim by the current holder only renews: no record write and no new entry.
  5. Commit.

  If the commit fails, the record may already name an owner with no lease. That is harmless: the owner can take it back with `beat`, and anyone else can claim.

- **`beat`:** renews a lease the session holds, live or expired, by `now + minutes × 60`. With no row at all, and the session being the record's `owner` (after a lost index), it creates the row. Anyone else gets exit 1. Renewing an expired lease is allowed, because a session that comes back before anyone else claims the job is still its owner.
- **`release`:** deletes the holder's row. Anyone else gets exit 1.
- **Renewal by the runner (T3):** `jobs.renew_for_task(common_dir, task, now)` finds the live job whose `job_tasks` holds the task, and extends its lease to `now + minutes × 60`, only while the lease is still live. It never revives a crashed job.
- **Daemons (T3):** `jobs.daemon_beat(common_dir, daemon_id, now)` upserts the daemon's row. A daemon is `dead` when `now - beat > daemon_timeout_seconds`. A runner job is `stale` when its record says `running` and its `daemon` is dead or has no row. After a lost index, a dead daemon has no row: its jobs show as stale until a live daemon writes a row.
- **Sessions:** `--session`, else `FACTORY_SESSION`, else `s-<host>-<pid>-<4 hex>`, with the host cut down to `[a-z0-9-]`. A given id must match `[A-Za-z0-9._:@-]{1,64}`.
- **The index is needed:** `claim`, `beat`, `release`, `set` and `resume` need the index, and exit 1 with "index unavailable" if it is locked for longer than the 10-second timeout. `new` writes its record first, so a failed index update is a warning there.

## The runner hooks (ADR 0053, T3)

`run.py` gets one function, `_index()`. It loads `Path(__file__).resolve().parents[1] / "control" / "jobs.py"` once with `importlib`, and returns the module, or `None` if the file is missing.

- A missing `jobs.py` means no index and no warning, so a kit without E18, and E16's own tests, behave exactly as before.
- A `jobs.py` that fails to load, or a call that raises, adds one warning per runner job, `index: <reason>`, and the runner carries on.

| Where in `run.py`                                                 | Call                                        |
| ----------------------------------------------------------------- | ------------------------------------------- |
| After `submit`, `send`, `close`, `usage`, `cancel`                | `refresh_runner(common_dir, runner_id)`     |
| `Daemon._save` (every record write)                               | `refresh_runner(common_dir, runner_id)`     |
| `Daemon.tick`, at most once a second                              | `daemon_beat(common_dir, self.name, now)`   |
| `Daemon.tick`, for each job with a command running, once a second | `renew_for_task(common_dir, job.task, now)` |

Once a second gives a margin under the spec's "at least every 2 seconds". The calls are cheap: one short transaction each.

## Resume (T4)

`resume` claims the job (it is `claim`, with the same refusals), refreshes it, and prints these sections in order:

1. **Job:** the record's fields, the new lease and the sidecar paths.
2. **Where:** the branch and worktree, from the record, or else from the newest runner job that belongs to the job. It also says whether each exists. If the worktree has gone and the branch exists, it gives the command `git worktree add <worktree> <branch>`. If both have gone, it says so.
3. **Runner jobs:** each one's id, status, `stale`, last 5 commands with their exit codes, and cost.
4. **Cost:** the total across the job's runner jobs, as an exact decimal.
5. **State:** from the worktree, or from the branch when the worktree has gone. The phase, the active task, the job's task with its status and open findings, and the newest handoff for that task, in full.

`--json` prints one object with the same sections as keys.

## Config

`config_schema.SECTIONS` gains `jobs`, after `runner`:

| Key                      | Kind   | Default | Rule               |
| ------------------------ | ------ | ------- | ------------------ |
| `lease_minutes`          | number | 10      | `_positive`        |
| `daemon_timeout_seconds` | number | 60      | `_between(5, ...)` |

`jobs.py` has its own `JOBS_RULES` and reads the main worktree's `.agentic/config.toml`, as `run.py` does. A test feeds the same good and bad values to both and expects the same verdicts (AC-18).

## API for E13 and the runner

These names are a contract. Tests pin them, so E13 can build on T1:

```python
find_repo(cwd: Path) -> Repo                          # common dir and main worktree
load_config(repo: Repo) -> Config                     # [jobs], validated
new_job(repo, title, *, job_id=None, track="full", task=None, branch="", worktree="", now=None) -> dict
read_job(repo, job_id) -> dict                        # raises UnknownJob
set_job(repo, job_id, session, *, now=None, **fields) -> dict
claim(repo, config, job_id, session, *, force=False, now=None) -> Lease
beat(repo, config, job_id, session, *, now=None) -> Lease
release(repo, job_id, session) -> None
lease_state(repo, job_id, *, now=None) -> str          # unclaimed | claimed | crashed | done | cancelled
sidecar_path(repo, job_id, name) -> Path
write_sidecar(repo, job_id, name, text, session, *, now=None) -> Path
# T2-T3, for run.py:
refresh_runner(common_dir, runner_id) -> None
daemon_beat(common_dir, daemon_id, now) -> None
renew_for_task(common_dir, task, now) -> None
```

The errors are `BadInput` (exit 2), `Refused` (exit 1), `UnknownJob` (a `BadInput`), `IndexTooNew` (a `BadInput`) and `IndexUnavailable` (a `Refused`).

## Test seams

- **In-process CLI and API:** `jobs.main([...])` and the API functions, in temp repos from `tests/_runner.py`'s `runner_repo`, with a fake clock. They cover:
  - ids, the 30-character limit, generated ids and duplicates (AC-02);
  - the record's fields, `show --json` and sidecar paths (AC-03);
  - `set` refusals and validation (AC-04);
  - claim, renew, force with its audit entry, beat, release and expiry at the exact boundary (AC-11, AC-12, AC-13);
  - the states in `list` (AC-10).
- **Concurrency:** 2 to 20 subprocesses started together on a barrier file: `new` without an id (no two get the same id), and claim, beat and usage (AC-07, AC-02). They are marked `slow`.
- **Index robustness:** delete the index, overwrite it with junk bytes, or truncate it. Then `rebuild` and compare `list --json` before and after, minus leases and heartbeats (AC-08). A version-0 fixture and a T1 (version 1) index with a lease both migrate, and the lease survives. A `user_version` of 99 exits 2 (AC-09).
- **Readers:** runner jobs made with real `run.py` CLI calls and a `Daemon.tick` with `FakeTree` from the E16 helpers. The index's view of each is compared with `run.py status --json`. Worktree state is checked after `state.py` writes made directly, with no `jobs.py` call between (AC-05, AC-06).
- **Runner hooks:** `Daemon.tick` with a fake clock:
  - each hook is called;
  - a lease of a few seconds survives a running command;
  - heartbeats; stale after the timeout;
  - an index that raises adds one warning and the job still succeeds;
  - with no `jobs.py`, nothing changes (AC-06, AC-13, AC-14).
- **Done-when:** real processes, marked `slow`, on all three OSes (AC-17). A session process claims the job and beats. A real daemon runs the open runner job. Both are killed: `Popen.kill()` on each OS, plus the daemon's command tree, using E16's `Tree` helpers so nothing outlives the test. A fresh `python jobs.py` in a separate worktree then lists and resumes the job, before and after the lease expires, and again after the index is deleted and rebuilt.
- **Resume from a branch:** remove the worktree with `git worktree remove --force` in a test. `resume` then gives the rebuild command and the handoff read from the branch. With the branch deleted too, it reports what's left (AC-16).
- **Config:** `install.py check`, the default render, and the agreement with `JOBS_RULES` (AC-18).

## Vertical slices

| Task | Slice                                                                                                                                                                                                           | ACs                                             |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| T1   | **Job record and leases**, merged early for E13: `jobs.py` with records, ids, tasks, sidecars, `new`, `show`, `set`, `claim`, `beat` and `release`, the version-1 index, the API, `[jobs]` config, the kit file | AC-01, AC-02, AC-03, AC-04, AC-11, AC-12, AC-18 |
| T2   | **The full index:** readers for runner files and worktrees, migration 2, refresh on read, `list`, `rebuild`, damaged and too-new indexes, many writers at once                                                  | AC-05, AC-07, AC-08, AC-09, AC-10               |
| T3   | **The runner hooks:** `run.py` refreshes the index, daemon heartbeats (migration 3), lease renewal, `daemons`, stale runner jobs, failures as warnings                                                          | AC-06, AC-13, AC-14                             |
| T4   | **Resume and done-when:** `resume`, resume from a branch, the kill-and-resume test on three OSes, the glossary, E18 AC coverage                                                                                 | AC-15, AC-16, AC-17, AC-19                      |

Each AC belongs to one slice. Where a later slice adds to an earlier AC, its tests carry that AC's tag too:

- AC-12's "beat after a rebuild" is tested in T2, which brings `rebuild`.
- AC-06's `jobs.py` writes are tested in T1 and T2, and its `run.py` part in T3, which owns the AC.

Each slice ships on its own:

- **T1:** E13 can create, claim and beat jobs.
- **T2:** sessions can list every job and rebuild the index.
- **T3:** the runner keeps the index and leases current, and dead daemons show.
- **T4:** sessions can resume, and the done-when test passes.

## Risks

- **E13 waits on T1.** T1 is kept to the record, leases and the API, with no readers, so it can merge first. The API is pinned by tests in T1. Any later change to it needs E13's agreement, through the orchestrator.
- **E16's locked tests.** T3 adds hooks to `run.py`, and E16's tests import the kit's `run.py`, so the hooks will run there and write an index in each temp repo. The hooks only add warnings on failure, and E16's tests that pin `warnings == []` run with a working index. T3 runs the whole E16 suite before its implementation commit is pushed. If any locked E16 test has to change, that is a relock, and it stops for the product owner's approval.
- **SQLite on Windows.** Files stay in use while open, so every connection is closed promptly, and the rebuild is done in place, not by replacing the file. A damaged index that another process holds stops with exit 2 and a clear message, rather than guessing.
- **Lock contention.** All writes are short `BEGIN IMMEDIATE` transactions with a 10-second busy timeout. A slow reader, such as a big `list` refresh, holds the write lock for as long as its refresh takes. Refreshes read the files before they begin the transaction, so the lock covers only the inserts.
- **Clock jumps.** Leases use wall-clock time, so a big clock change on the machine can expire or extend leases. That's accepted for one machine. E23's cloud mode will need to say whose clock counts.
- **Case-insensitive file systems.** Task reservations use the task name as a file name. On Windows and macOS, `E18-T1` and `e18-t1` collide, which is safe, since E02's task files collide there too.
- **Slow tests and the mutation gate.** The subprocess tests (concurrency, done-when) are marked `slow`. The fake-clock tests have to cover the lease and index decisions well enough to reach 60% on changed lines.
