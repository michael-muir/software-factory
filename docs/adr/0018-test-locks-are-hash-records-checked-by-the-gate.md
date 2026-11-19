# 0018 · Test locks are hash records in .agentic, checked by the gate on every run

Status: Accepted · Date: 2026-11-18 · Epic: E03

## Context

Until now, tests have been "locked" only by commit convention: a `test(...)` commit lands before the `feat(...)` commit. Nothing stops a later change to those tests. The spec requires that the gate fail on a change to a locked test and that the hook block edits to one.

The options:
1. **Compare against the locking commit in git.** This needs history: CI checkouts are shallow, and the gate is meant to work without git.
2. **Store each file's hash in a record in the repo.**
3. **Make the files read-only.** This doesn't survive git, and it doesn't work the same way on Windows.

## Decision

Option 2:
- **Record:** `.agentic/locks/<task>.toml` holds the `task`, a `locked` time and one `[[files]]` entry per file, each with a `path` and a `sha256`. It's state (ADR 0003): seeded as an empty folder and never overwritten by installs.
- **Hash:** SHA-256 of the bytes after normalising CRLF and CR to LF, the same as the manifest (ADR 0004), so a checkout with `autocrlf` doesn't break a lock.
- **Writing:** only `agents.py lock` and `unlock` write records, atomically. `lock` refuses to replace an existing record without `--replace`.
- **Gate:** `verify_locks` runs on every gate run, after validation and before any check, including `--checks` runs. A changed or missing locked file fails the gate with exit 1, and nothing else runs.
- **Hook:** `edit` and `write` calls on a locked path are denied for every role, and when no role is set.

## Consequences

- Locks work in shallow CI checkouts and without git.
- Changing a locked test takes a deliberate relock, which shows up in review as a change to `.agentic/locks/`. Whether a relock is allowed is a review decision (E14), not something the gate checks.
- A `run` command can still change a locked file. The hook doesn't parse shell commands, so the gate is what catches it, before merge.
- A lock that passes on one OS passes on all three, because hashes ignore line endings.
