# 0041 · The driver is a resumable step machine under the E18 lease, and ends a runner job at every wait

Status: Accepted · Date: 2026-11-21 · Epic: E13

## Context

A full-track job lasts hours or days: it waits for a human to approve the spec and to merge each PR. The driver can crash, or the machine can restart, at any point. The job is E18's (spec decision, 21 Nov 2026): its record and its lease decide who may write. E16's runner job has a time cap that counts time spent waiting, so a runner job can't stay open while a human thinks. The options were:

- **A long-running driver process per job,** holding everything in memory. A crash loses its place, and it would sit on a runner job through every wait.
- **A driver that works out its place from git alone.** That's possible for files, but not for which session was sent, or what it cost.
- **A step machine with a record:** one action per step, written down before it's confirmed.

## Decision

- **The pipeline's own record** is E18's sidecar `<git-common-dir>/factory/work/<job>.pipeline.toml`, beside E18's `work/<job>.toml`, written atomically with `jobs.write_sidecar` while holding the lease. It holds the status, stage, task, tasks and PRs, the runner jobs, every command sent (with its exit code and cost), and every decision.
- **`Driver.step()` does one action:**
  - collect a finished command;
  - submit a runner job;
  - send a session;
  - run a check;
  - move to the next stage;
  - or stop at a wait point.

  The record entry for a command is written before `run.py send`. On restart, an entry the runner doesn't have is sent again, and one it has is waited for, so nothing runs twice.

- **`run` holds E18's lease.** It runs `jobs.py claim` first, `beat` at least every third of the lease, and `release` at each wait point. `approve`, `reject`, `resume` and `cancel` take the lease while they write. The driver keeps E18's `phase`, `task`, `branch`, `worktree` and `status` current with `jobs.py set`.
- **A wait point ends the process and the runner job.** At a checkpoint, a merge or a human, the driver closes the runner job and exits. The next `run` opens a new segment from the last segment's branch: `<job>-p<k>` for the plan, and `<job>-t<n>-<k>` for a slice. So no runner job ever waits on a person.
- **The driver talks to E16 and E18 only through their command lines,** behind `Runner` and `Jobs` ports, with fakes for the fast tests.

## Consequences

- Any session that can claim the lease can carry the job on, from the record alone. E19's router will call the same `run`.
- Each segment gets fresh turn and time caps. The cost cap is per runner job too, so the job's total is the sum, shown in `status` and the summary. E21 adds a per-job budget across segments.
- One more file format to keep stable. It has a `version`, and E18's index can read it later.
- Branches pile up (`factory/<job>-t1-1`, `-t1-2`, ...). Only the pushed PR branch matters. Pruning is out of scope, as it is for E16.
