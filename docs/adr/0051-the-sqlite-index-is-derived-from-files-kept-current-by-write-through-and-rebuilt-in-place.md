# 0051 · The SQLite index is derived from files, kept current by write-through and refresh on read, and rebuilt in place

Status: Proposed · Date: 2026-11-21 · Epic: E18

## Context

The index, `<git-common-dir>/factory/index.sqlite`, answers in one place what every job is doing. It covers the job records (ADR 0050), the runner's files (ADR 0030) and each worktree's `.agentic` (E02). The product owner decided that files stay the truth, that every write updates the index, and that one command rebuilds it. `state.py` doesn't change, so its writes never reach the index directly. The index must survive being deleted or damaged, must work on Windows (where an open file can't be replaced), and must move forward as later epics add tables.

## Decision

- **Write-through.** Every `jobs.py` write updates its rows in the same transaction. `run.py` asks the index to re-read one runner job after each of its writes (ADR 0053).
- **Refresh on read.** `show`, `list` and `resume` first re-read the files they answer about, including the worktrees' `.agentic`. So a `state.py` write is never missed, and `state.py` needs no hook.
- **Rebuild in place.** `rebuild` deletes every derived row and re-reads every file, in one `BEGIN IMMEDIATE` transaction. Readers see the old index or the new one, never a mix, and the file is never replaced while it's open. Leases and daemon heartbeats aren't derived, so a rebuild keeps them. Only a lost or damaged index loses them.
- **A damaged index** (an error from `sqlite3.DatabaseError`) is moved aside as `index.sqlite.damaged-<time>`, then a new one is created and rebuilt, with a warning. If the move fails, the tool exits 2 and asks for the other processes to be stopped.
- **Versions.** The schema's version is `PRAGMA user_version`, and `MIGRATIONS` is an ordered tuple of statement lists. An older index runs the missing migrations and then a rebuild, all in one transaction. A newer one exits 2 and is never downgraded.
- **SQLite settings:** `timeout=10`, `isolation_level=None` with an explicit `BEGIN IMMEDIATE` for every write, the default rollback journal (not WAL), and every connection closed promptly. Readers do their file reading before they begin a transaction.
- **The tables are internal.** The CLI and the API are the interface, so later epics change the tables only through a migration in `jobs.py`.

## Consequences

- The index is a cache that can always be rebuilt. If it's corrupted, the cost is a rebuild and the live leases, never a job.
- Reads cost a few file reads per worktree. That's cheap at the scale of one machine, and it's what keeps `state.py` free of SQLite.
- Each slice that adds tables adds a migration, so migration is tested for real from E18's own history, not just on a fixture.
- Without WAL, a reader briefly blocks a writer. The 10-second busy timeout and short transactions keep that invisible at this scale. WAL can come later by migration, if the dashboard (E27) needs it.
