# 0032 · A job is a worktree and a stream of commands, driven by one polling loop that enforces the caps

Status: Proposed · Date: 2026-11-19 · Epic: E16

## Context

The runner has to stay agent-neutral. A job may be a single build, or a cloud session sending one command at a time (E23). One command is one turn. Cost is reported by the caller, and the daemon checks the caps after every command and every report (spec decisions). Three caps (turns, cost, time) must halt a job within 2 seconds, even mid-command. At most `max_parallel` jobs run at once. The code must be standard library only, testable fast enough for the mutation gate, and the same on three OSes.

The options were:

- **A thread per job,** blocking on its command. That means locks around shared state, and the tests become hard to make deterministic.
- **asyncio subprocesses.** Their support differs across platforms on Windows, and they don't fit the Windows host handshake of ADR 0031.
- **One loop that polls,** with no threads.

## Decision

- **A job is a worktree plus an ordered stream of commands.** `submit -- argv` makes a one-command job, closed at birth. `submit --open` makes an open job, which takes commands from `send` until `close`.
- **The daemon is one single-threaded loop.** `Daemon.tick(now)` does one pass, and `--daemon` calls it about every 0.2 seconds. Each pass:
  1. Stops if a stop request or Ctrl+C has arrived, halting every running job.
  2. Claims queued requests, oldest first, while fewer than `max_parallel` jobs are running.
  3. For each running job, in this order:
     - applies a cancel;
     - collects a finished command, recording its exit code and duration and counting the turn;
     - reads the usage total, and records the warning once;
     - checks the caps: cost, then time, then turns;
     - starts the next command, or ends the job by the result rule.

  The clock is passed in. The process starter is a small `Tree` interface (start, poll, kill; ADR 0031), so the loop can be tested in-process with a fake clock.

- **The halt is one function,** used by every cap, by `cancel` and by `stop`. It kills the tree, records the reason, drops the queued commands, writes the handoff with the worktree's own `state.py`, and keeps the worktree.
- **The caps are read once,** when the daemon starts:
  - turns: `runner.max_turns`;
  - cost: `budgets.per_job_usd × budgets.halt_at`, with the warning at `× warn_at`;
  - time: `runner.job_timeout_minutes`, from the job's start.

  `run.py` validates them itself, with the same rules as `factory_installer/config_schema.py`. A test pins that the two agree.

## Consequences

- No shared-state threads and no locks inside the daemon. Every decision happens in `tick`, and the tests drive it step by step.
- The 0.2-second pass keeps pickup and halts well within the spec's 2 seconds. An idle daemon costs a few file listings a second.
- A slow pass, such as `git worktree add` on a big repo, delays the other jobs' cap checks by as long as the pass takes. The design accepts that. Worktree creation is the only slow step, and it can move to a helper process later without changing the job model.
- A new cap or a new intake source is one more step in `tick`, or one more source behind the intake interface (ADR 0030).
