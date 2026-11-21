# 0053 · The runner reaches the index through jobs.py loaded by path, and an index failure is only a warning

Status: Accepted · Date: 2026-11-21 · Epic: E18

## Context

The index has to see runner jobs, usage and daemon heartbeats as they happen, and the runner has to renew leases while it runs a job's commands (E18 spec AC-06, AC-13, AC-14). `run.py` and `jobs.py` are separate kit files, both standard library only. E16's tests are locked, and they import the kit's `run.py` and pin its records, including `warnings == []` in places. A Python built without `sqlite3`, or a locked or damaged index, must never stop a build. `docs.py` already loads `state.py` by path with `importlib`.

The options were:

- A second, small SQLite writer inside `run.py`. That's two copies of the schema to keep in step.
- `run.py` calling `jobs.py` as a subprocess. That adds a process start per record write, and it's slow in the daemon loop.
- **`run.py` importing `jobs.py` by path,** from its own install, and calling a few functions.

## Decision

- `run.py` loads `<its .factory>/control/jobs.py` once, with `importlib`. A missing file means no index: no calls and no warnings, so a kit without E18 behaves exactly as E16 does.
- **It makes three kinds of call:**
  - `refresh_runner(common_dir, runner_id)`, after each CLI write and each `Daemon._save`;
  - `daemon_beat(common_dir, daemon_id, now)`, at most once a second;
  - `renew_for_task(common_dir, task, now)`, once a second for each job with a command running.
- **`jobs.py` reads the runner's files itself,** and doesn't import `run.py`. A test pins that its view of a runner job equals `run.py status --json`.
- **A failure is a warning.** A load error or an exception from any call adds one `index: <reason>` warning to that runner job's record, and the runner carries on. Nothing in a runner job's result depends on the index.

## Consequences

- There's one schema and one writer of the index, in `jobs.py`. `run.py` gains about thirty lines.
- E16's locked tests run with the hooks active, against a working index in each temp repo, so their records are unchanged. A test that would have to change is a relock, and needs the product owner's approval.
- The two modules depend on each other only through the three functions and the file formats of ADR 0030, and both are pinned by tests.
