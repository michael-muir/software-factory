# 0017 · The Claude Code hook takes the role from the subagent, then FACTORY_ROLE, and fails closed

Status: Accepted · Date: 2026-11-18 · Epic: E03

## Context

The hook has to know which role is making a tool call. Claude Code's `PreToolUse` input includes `agent_type` when the call comes from a subagent, or when the session was started with `--agent`. Hooks from settings files fire inside subagents too. E12 will compile each role into a Claude Code subagent with the same name, so `agent_type` will be the role's name. Until then, and for whole sessions that act as one role, the spec names the `FACTORY_ROLE` environment variable (assumption 1).

Claude Code blocks a call only on exit 2. Any other non-zero exit is a non-blocking error, and the call goes ahead. A timed-out hook doesn't block either, unless the hook is registered with `onFailure: "block"`. So a hook that crashes would let the call through.

Built-in subagents such as Explore also produce an `agent_type`. Those aren't factory roles.

## Decision

- **Role resolution, in order:**
  1. `agent_type`, when it names a factory role file
  2. otherwise `FACTORY_ROLE`, when it's set and not empty
  3. otherwise no role

  An `agent_type` that isn't a factory role, such as Explore, falls through to step 2.
- **Unknown role:** a `FACTORY_ROLE` that names no role file blocks every call, with the message "unknown role".
- **No role:** tool lists don't apply, but edits and writes to locked files are still blocked (spec AC-07).
- **Fails closed:** the hook body catches everything (`BaseException`), prints the reason to stderr, and exits 2. It never exits with any other non-zero code.
- **Registration** (this repo now, E12 for targets): the hook runs through a POSIX `sh` launcher that finds a Python 3.11+, as the E07 git hooks do. It's registered with `onFailure: "block"` and a 10 s timeout.
- **Output:** a denial is exit 2 with the reason on stderr, which Claude Code shows to the model. An allow is exit 0 with no output, so Claude Code's normal permission flow still applies.

## Consequences

- When E12 makes roles subagents, they're enforced without needing an environment variable.
- A built-in subagent working in a factory repo is never locked out. Locks still bind it.
- A broken install blocks every tool call in Claude Code until it's fixed. That's visible and safe, but it can surprise people. The message names `agents.py check`.
- The hook trusts `agent_type` and `FACTORY_ROLE`, both of which the session controls. It guards against mistakes, not against a hostile operator (spec assumption 2).
