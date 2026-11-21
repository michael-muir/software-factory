# 0052 · Leases and heartbeats live only in the index, and its write lock serialises every job record write

Status: Proposed · Date: 2026-11-21 · Epic: E18

## Context

"Any session resumes any job after a crash" needs two things: a way to tell a crashed owner from a live one, and a guarantee that two sessions don't both work on one job. The product owner chose a lease with a heartbeat, 10 minutes by default. The runner renews it while it runs the job's commands, an expired lease means the job crashed, and `--force` takes a live lease and is recorded. There is no lock in `state.py`: the lease is what makes one writer per `.agentic`. Leases change often and matter only while someone is alive, so they don't need to be files. Job records, though, are files with several possible writers, and E16's lock-free tricks don't cover a read-modify-write.

## Decision

- **A lease is a row in `leases`:** job, session, minutes, acquired and expires, in Unix seconds. A daemon's heartbeat is a row in `daemons`. Neither is derived from files, and both are kept by a rebuild.
- **States are computed from the row and the clock:** `unclaimed` (no row), `claimed` (`expires > now`), `crashed` (`expires <= now`), or the job's own `done` or `cancelled`. `release` deletes the row, so an expired row always means no one let go.
- **`claim`, `beat`, `release` and `set` each run in one `BEGIN IMMEDIATE` transaction:** check the lease, write the record file if needed, update the rows, commit. The index's write lock is the only lock, and it also serialises every record write.
- **`--force`** takes a live lease. The new `[[claims]]` entry in the record says `forced = true` and names the session it was taken from, so the audit trail survives a lost index.
- **`beat`** renews the holder's lease, even an expired one if no one else has claimed the job. It lets the record's `owner` take back a lease lost with the index.
- **The runner** extends only a live lease, for the job whose tasks hold the runner job's task. It never revives a crashed job. Daemons beat at least every 2 seconds, and are dead after `jobs.daemon_timeout_seconds`. A `running` runner job under a dead or unknown daemon is `stale`.
- **The clock** is `time.time()`, passed into the API so tests can fake it.

## Consequences

- A crash shows up on its own when the heartbeats stop. No process has to notice it, and E22's watchdog can act on the same states.
- Without the index, nothing can be claimed: `claim`, `beat`, `release`, `set` and `resume` exit 1 with "index unavailable". `new` still writes its record, with a warning.
- Losing the index loses only live leases and heartbeats. Owners get their leases back with `beat`, and a dead daemon's jobs show as stale until they're repaired.
- Wall-clock time is trusted. On one machine that's acceptable. E23 will have to say whose clock counts.
