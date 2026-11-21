# E18 · Job index — Spec

Issue: [#18](https://github.com/michael-muir/software-factory/issues/18) · Milestone: M3 · Unattended line · Depends on: E02 (done); builds on E16 (done)
Status: **Approved by the product owner, 21 Nov 2026** · Next: Architect design note and ADRs, then failing tests per AC

## Change note (21 Nov 2026)

The product owner decided that E13 (the full-track pipeline) and E18 share **one job, owned by E18**. E18's job record (`work/<id>.toml`), its id and its lease are the job. E13's pipeline keeps its stage, approval and PR details in a sidecar file beside the record, keyed by the same id (AC-03), and its driver claims the job with E18's lease and sends heartbeats while it runs. So job ids are at most 30 characters (AC-02), the same as E13's, and E18's first slice (the record, `new`, `show`, `claim`, `beat` and `release`) merges before E13's driver slice. E13's spec carries the matching note.

## Goal

A session that crashes, or a daemon that dies, must not strand its work. Today the work of a job is spread across files: the runner's records under the git directory (E16), and the task files and handoffs in each worktree's own `.agentic` (E02). No session can see all of it, and nothing says whether the session working on a job is still alive. E18 gives the factory a job index:

- **Jobs:** a job is one piece of work, such as a request on the full track. It has its own record, which links it to its `state.py` task and to every E16 runner job that ran for it.
- **An index:** a SQLite database, `<git-common-dir>/factory/index.sqlite`, that every worktree shares. It is built from the files, so it can always be rebuilt, and it answers in one place what each job is doing and where.
- **Leases:** a session claims a job with a lease and keeps it alive with heartbeats. When the heartbeats stop, the job counts as crashed, and any session can resume it from the index. Runner daemons send heartbeats too, so jobs left by a dead daemon show as stale.
- **`.factory/control/jobs.py`:** a standard-library tool for creating, listing, claiming and resuming jobs, and for rebuilding the index.

The router (E19), the cost controls (E21), the watchdog (E22) and the Line Monitor (E27) all read the index or write to it. E18 sets up the tables and commands they build on, but none of their behaviour.

**Done when:** any session resumes any job after a crash (PRD).

## Decisions in force (product owner, 21 Nov 2026)

| Topic                  | Decision                                                                                                                                                                                                                                                                                                                                                                                                                  |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| What a job is          | **Its own record:** id, title, track, phase, status, task, branch, worktree and owner. A person creates it with a new command now, and the router (E19) will later. It links to its `state.py` task, and to every E16 runner job that ran for it through the runner's `--task`.                                                                                                                                           |
| Source of truth        | **Files stay the truth.** A job is one TOML file beside the runner's files under `<git-common-dir>/factory/`. The SQLite database is a query index over those files, the runner's records and each worktree's `.agentic`. Every write updates it, and one command rebuilds it from the files. Losing the index loses only live leases and heartbeats.                                                                     |
| Where the index lives  | **`<git-common-dir>/factory/index.sqlite`.** Every worktree of the repo shares it, and git never tracks it.                                                                                                                                                                                                                                                                                                               |
| Claiming a job         | **A lease with a heartbeat.** A claim gives a session a lease, 10 minutes by default (set in config). A heartbeat command renews it, and so does the runner while it runs the job's commands. An expired lease means the job crashed, and anyone may resume it. `--force` takes a live lease, and the job's record says so.                                                                                               |
| A daemon that dies     | **E18 detects it and hands the job over.** Daemons write heartbeats into the index, and the runner jobs of a dead daemon show as stale. Resume gives the new session the worktree, branch, last commands, cost so far and latest handoff, or, if the worktree has gone, how to rebuild it from its branch. Repairing records, claims and worktrees stays with E22.                                                        |
| Locking                | **None in `state.py`.** One job per worktree, plus the lease, means one writer per `.agentic`. That is the rule: a session writes to a job's `.agentic` only while it holds the job's lease. `resume` refuses a job whose lease is live.                                                                                                                                                                                  |
| Settled by the sources | SQLite, through the standard library's `sqlite3` (PRD). The code is standard library only, Python 3.11+, and works on Ubuntu, macOS and Windows. E16's file store (ADR 0030) stays lock-free and keeps its meaning: E18 only reads it, and adds index updates to `run.py`. New config keys are validated by `install.py check`. The kit file is installed by `install.py`, and this repo commits its install. No network. |

## In scope

- `.factory/control/jobs.py` and its commands: `new`, `set`, `show`, `list`, `claim`, `beat`, `release`, `resume`, `daemons` and `rebuild`.
- The job record file, the index's tables, its schema version and migrations.
- Keeping the index up to date: from `jobs.py`, from `run.py` (runner records, usage reports and daemon heartbeats) and from the worktrees' `.agentic` files.
- Leases, heartbeats, crash and stale detection, and resume.
- A new `[jobs]` config section, and its validation in `install.py check`.
- Glossary entries for job, runner job and lease.
- Shipping the tool in the kit, and installing it into this repo.

## Out of scope

- Choosing, dispatching or ordering jobs, and creating jobs from requests (E19).
- The daily budget, real metering and any halt on spend (E20, E21). E18 indexes usage with its time, so E21 can add it up per day.
- Repairing anything a crash leaves behind: runner records stuck at `running`, worktree claims, orphaned worktrees and stray processes (E22).
- Tables for gate results and approvals (E21, E27), and the dashboard (E27).
- Locking in `state.py`, and any `state.py` change. `state.py` doesn't touch the index; the index reads its files.
- The network and cloud transport (E23). The index is per clone, on one machine.
- Deleting or archiving jobs, and pruning the index.

## Where things live

| What               | Where                                       |
| ------------------ | ------------------------------------------- |
| The tool           | `.factory/control/jobs.py` (kit file)       |
| Job records        | `<git-common-dir>/factory/work/<id>.toml`   |
| The index          | `<git-common-dir>/factory/index.sqlite`     |
| Runner files (E16) | `<git-common-dir>/factory/queue/`, `jobs/`  |
| A job's state      | its worktree's `.agentic/`, or its branch's |

`<git-common-dir>` is what `git rev-parse --git-common-dir` prints, as in E16, so the main checkout and every worktree find the same records and index. Nothing under it is ever tracked by git.

**Words used below:** a **job** is E18's record of one piece of work. A **runner job** is an E16 job: a worktree and the commands run in it. A runner job **belongs to** a job when its `--task` is one of the job's tasks. A **session** is anything that works on a job and has an id: an agent session, a person or the router.

## New `config.toml` keys

| Key                           | Type   | Default | Rule           |
| ----------------------------- | ------ | ------- | -------------- |
| `jobs.lease_minutes`          | number | 10      | greater than 0 |
| `jobs.daemon_timeout_seconds` | number | 60      | 5 or greater   |

`lease_minutes` is a number, not an integer, so tests can set a fraction of a minute. A daemon whose last heartbeat is older than `daemon_timeout_seconds` is dead. Existing configs without `[jobs]` stay valid, and the defaults apply.

## Acceptance criteria

**The tool and job records**

- **AC-01** `jobs.py` runs under `python -I -S` with Python 3.11+, and imports only the standard library. Run anywhere inside a repo, from the main checkout or from any worktree, it uses that repo's records and the one index at `<git-common-dir>/factory/index.sqlite`, and creates the index if it's missing. Exit code 0 means the command did what it was asked. 1 means it was refused, for example by a live lease. 2 means bad input: a bad argument, an invalid config, an unknown job, or a directory that isn't in a git repo with at least one commit.
- **AC-02** `jobs.py new "<title>" [--id ID] [--track T] [--task TASK] [--branch B] [--worktree PATH]` writes a new job record and prints its id.
  - **Ids:** a generated id is `job-<n>`, the next free number from 1. A given id must match `[a-z0-9][a-z0-9-]{0,29}`, at most 30 characters, so runner job ids built from it fit E16's 40. Ids are reserved atomically, so two `new` commands run at the same time never get the same id, and a used id is refused with exit 2.
  - **Defaults:** `track = "full"`, `phase = "spec"`, `status = "open"`, `task` = the job's id, and an empty branch and worktree.
  - **Tasks:** a task id must match `state.py`'s `[A-Za-z0-9._-]+`. A task held by another job that isn't `done` or `cancelled` is refused with exit 1.
- **AC-03** A job record is one TOML file, `work/<id>.toml`, and is always written atomically: no reader ever sees a half-written file. It holds:
  - `id`, `title`, `track` (from E02's tracks), `phase` (from E02's phases) and `status` (`open`, `blocked`, `done` or `cancelled`);
  - `task`, and `tasks`, every task the job has had, in order;
  - `branch` and `worktree`;
  - `owner`, the session that last claimed it;
  - `created` and `updated`;
  - a `[[claims]]` table per claim: the session, the time, `forced`, and the session it was taken from.

  Other epics may keep their own details about a job in **sidecar files** beside the record, `work/<id>.<name>.toml`, where `<name>` matches `[a-z][a-z0-9]{0,19}`: E13's pipeline keeps its stages, approvals and PRs in `work/<id>.pipeline.toml`. `jobs.py` never writes or validates a sidecar, and a sidecar never changes the job's record.

  `jobs.py show <job> [--json]` prints the record, and the paths of its sidecars. `--json` prints the same fields as JSON.

- **AC-04** `jobs.py set <job> --session S` takes `--title`, `--track`, `--phase`, `--status`, `--task`, `--branch` and `--worktree`, and updates those fields and `updated`. Only the session holding the job's live lease may set fields; anyone else gets exit 1. A new `--task` is appended to `tasks`, under the same rule as AC-02. An invalid value exits 2 and changes nothing.

**The index**

- **AC-05** **What the index holds.**
  - every job record;
  - every runner job: its record's fields (AC-04 of E16), its commands with their exit codes, its daemon, and the job it belongs to;
  - every usage report, with its amount, its time and its runner job;
  - for each worktree the repo has, the `.agentic` state: the phase, the active task, each task's status and the newest handoff per task;
  - each daemon's last heartbeat;
  - each live lease.

  The tables are an internal format. The commands below are the interface, and later epics read the tables through it.

- **AC-06** **Kept up to date.**
  - After every `jobs.py` command that writes a record, and every `run.py` command or daemon step that writes a runner record or a usage report, the index already shows the change: no `rebuild` is needed.
  - Before `show`, `list` or `resume` answers about a job, it reads that job's worktree `.agentic` files again, so a `state.py` write is never missed.
  - A write to the index never fails the file write it follows. If the index can't be written (it's locked for longer than 10 seconds, or damaged), the file write still stands, `jobs.py` prints a warning, and `run.py` adds a warning to the runner job's record and carries on.
- **AC-07** **Many writers at once.** 20 processes run at the same time, each claiming its own job, sending heartbeats and reporting usage. None of them fails with a locked database, and the index then holds every one of the leases and reports.
- **AC-08** **Rebuild.** `jobs.py rebuild` builds a new index from the files alone, and replaces the old one atomically. With the index deleted, damaged or replaced by junk bytes, `rebuild` and then `list --json` print the same jobs, runner jobs, usage and worktree state as before. Only the live leases and daemon heartbeats are gone. Any other command that finds the index damaged rebuilds it first and prints a warning.
- **AC-09** **Schema version.** The index records its schema version. A command that opens an index with an older version applies each migration in order, in one transaction, before going on. An index with a newer version than the tool knows exits 2, names both versions, and changes nothing. A test migrates an index from a version-0 fixture.
- **AC-10** `jobs.py list [--status S] [--json]` prints every job with its id, title, track, phase, status, task, branch, owner and `state`:
  - `unclaimed`: no lease;
  - `claimed`: a live lease, with its session and expiry;
  - `crashed`: an expired lease that no one has released;
  - `done` or `cancelled`: the job's status.

  A job with a running runner job whose daemon is dead is also marked `stale`.

**Leases**

- **AC-11** **Claim.** `jobs.py claim <job> [--session S] [--force]` gives a session the job's lease for `jobs.lease_minutes`, sets `owner`, adds a `[[claims]]` entry, prints the session id and the expiry, and exits 0.
  - The session id is `--session`, or else `FACTORY_SESSION`, or else a generated one.
  - A job that's unclaimed or crashed can be claimed. A session that already holds the lease just renews it.
  - A live lease held by another session is refused with exit 1, naming the holder and the expiry. With `--force`, the claim takes the lease, and the claim entry records `forced = true` and the session it was taken from.
  - A `done` or `cancelled` job is refused with exit 1.
- **AC-12** **Heartbeat and release.** `jobs.py beat <job> --session S` renews the holder's lease for another `lease_minutes`. `jobs.py release <job> --session S` ends it, and the job is unclaimed again. Both exit 1 for a session that doesn't hold the lease. After a rebuild, the job's `owner` can `beat` to take back a lease that no one else holds.
- **AC-13** **Expiry.** A lease that isn't renewed within `lease_minutes` expires, and the job is then `crashed` (AC-10). While a runner job that belongs to a claimed job is running a command, the runner renews that job's lease at least every 2 seconds, so a long build doesn't look like a crash. A test sets a lease of a few seconds, runs a longer command, and checks that the lease is still live.

**Daemons**

- **AC-14** A runner daemon writes a heartbeat into the index when it starts, and at least every 2 seconds after that, under the daemon id that E16's records already carry. `jobs.py daemons [--json]` lists each daemon with its host, process id, last heartbeat and `alive` or `dead`. A daemon is dead when its last heartbeat is older than `jobs.daemon_timeout_seconds`. A runner job that is `running` in its record, under a dead daemon, is shown as `stale` by `daemons`, `list` and `resume`. E18 changes none of its files.

**Resume**

- **AC-15** **Resume.** `jobs.py resume <job> [--session S] [--force] [--json]` claims the job by AC-11's rules (so it refuses a live lease held by another session unless `--force` is given), and then prints everything a new session needs to carry on:
  - the job's record and its new lease;
  - its branch and worktree, and whether each still exists. If the job's own fields are empty, they come from its newest runner job.
  - each runner job that belongs to it: its id, status, whether it's stale, its last 5 commands with their exit codes, and its cost;
  - the job's total cost so far, across its runner jobs;
  - the worktree's phase and active task, its task's status and open findings, and the newest handoff for its task, in full.

  `--json` prints the same as JSON.

- **AC-16** **A worktree that has gone.** When the job's worktree no longer exists but its branch does, `resume` says so, and prints the `git worktree add` command that rebuilds the worktree from the branch. It takes the task and the newest handoff from that branch's committed files instead. When the branch has gone too, it says so and exits 0 with what the index still has.
- **AC-17** **Done-when: any session resumes any job after a crash.** In a test, on Ubuntu, macOS and Windows:
  1. A job is created and claimed by session A, a separate process, with a lease of a few seconds.
  2. An open runner job for the job's task is submitted to a real daemon. It is sent one command that writes a handoff with `state.py`, and then a command that waits.
  3. Session A and the daemon are killed without warning.
  4. A fresh process in another checkout of the same repo (a separate worktree), sharing nothing but the repo, runs `jobs.py list`. The job is `claimed` until the lease expires, and `resume` refuses it until then.
  5. Once the lease has expired, the job is `crashed`, its runner job is `stale`, and `resume --session B` exits 0. Its output names the job, task, worktree, branch, the runner job's commands and the handoff's `## Next` section.

  The test then deletes the index, runs `rebuild`, and resumes again with the same result.

**Config, kit and quality**

- **AC-18** `install.py check` validates the `[jobs]` keys by the rules in the table above. The default config that `install.py` writes includes `[jobs]` with its defaults and comments. A config without `[jobs]` stays valid. This repo's `.agentic/config.toml` gets the section, and `jobs.py` and `install.py` agree on every key, as a test pins.
- **AC-19** `jobs.py` is a kit file, installed by `install.py` and listed in the kit layout tests, and this repo commits its install. `docs/GLOSSARY.md` gains job, runner job and lease. CI runs the index tests on Ubuntu, macOS and Windows. ruff, `ruff format --check` and `mypy --strict` pass, and every AC above has at least one test tagged `E18-AC-nn`.

## Assumptions (confirmed with approval, 21 Nov 2026)

1. **The tool is `.factory/control/jobs.py`.** The blueprint already names `control/watchdog`, so the control plane gets one folder.
2. **The schema has a version and moves forward by migration** (AC-09). Since the index can always be rebuilt from files, an index from a newer kit is refused, never downgraded.
3. **Usage is indexed with its time,** taken from the E16 usage file's name, so E21 can add up spend per day without reading the files.
4. **Gate-result and approval tables come with E21 and E27.** E18 adds none.
5. **The done-when test (AC-17)** kills a session and a daemon mid-job, and then resumes the job from another checkout.
6. **`state.py` doesn't change.** The index reads the `.agentic` files again before it answers about a job (AC-06), so `state.py` never has to write to the index.
7. **A task belongs to one live job at a time** (AC-02), so a runner job's `--task` always names one job.
8. **Only the lease holder can change a job's record** (AC-04). Without a lock, that keeps job records to one writer at a time, like the `.agentic` rule.
9. **Daemons beat every 2 seconds, and the runner renews leases at the same pace.** These are fixed limits, not settings. Only the lease length and the daemon timeout are configurable.
10. **One clone, one machine.** Sessions on other machines reach the index through E23, not through a shared file system. SQLite on a network drive isn't supported.
11. **A Python built without `sqlite3`** is rare. There, `jobs.py` exits 2 and says so, and `run.py` carries on without the index, with a warning in each runner job's record.

## Notes for the Architect (design, not requirements)

- `run.py`'s E16 tests are locked. The index updates in `run.py` (AC-06, AC-13, AC-14) must leave its behaviour, records and exit codes as they are. A failure to reach the index is a warning, never a failed job.
- `run.py` and `jobs.py` are separate kit files. Decide whether `run.py` imports `jobs.py` by path, or keeps its own small writer that the tests pin against `jobs.py`. E16 did the same with its config rules.
- SQLite settings that are worth considering: a busy timeout of about 10 seconds; WAL mode, which works on all three OSes on a local disk; and short transactions. A rebuild can write a temp file and `os.replace` it, but on Windows that fails while another process has the index open, so it needs a retry or a fallback such as rebuilding in place inside one transaction.
- Job ids can be reserved by exclusive create, with an atomic rename to publish the record, as in ADR 0030.
- To read a branch's handoffs when its worktree has gone (AC-16), use `git ls-tree` and `git show`; `state.py`'s parser can read text passed to it.
- E01's expected default config and the kit file list change with this epic. Update them in the test commit, and flag that in the PR.
