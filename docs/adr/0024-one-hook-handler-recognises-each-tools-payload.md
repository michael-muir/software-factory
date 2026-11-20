# 0024 · One hook handler recognises each tool's payload and answers in its protocol

Status: Accepted · Date: 2026-11-19 · Epic: E12

## Context

E03 built `agents.py hook claude-code` (ADR 0017). E12 adds Copilot and Cursor, whose `preToolUse` hooks differ from Claude Code's, and from each other's:

| | Claude Code | Copilot | Cursor |
| --- | --- | --- | --- |
| Tool field | `tool_name` | `toolName` (or `tool_name` in VS Code's form) | `tool_name` |
| Arguments | `tool_input` | `toolArgs`, a JSON string (or `tool_input`) | `tool_input` |
| Agent field | `agent_type` | `agentType` / `agent_type` | none |
| Deny | exit 2, reason on stderr | `permissionDecision: "deny"` JSON, or exit 2 | `permission: "deny"` JSON, or exit 2 |
| On error | exit codes other than 2 let the call through | other non-zero exits deny; timeouts let it through | fails open unless `failClosed: true` |

Tools also read each other's configuration. VS Code's Copilot reads `.claude/settings.json`, and Cursor maps Claude Code hooks to its own. So the handler started by `.claude/settings.json` can receive a Copilot or Cursor payload.

## Decision

- **One handler, three entry points.** `hook claude-code`, `hook copilot` and `hook cursor` all call the same function.
- **The handler recognises the payload by its shape,** not by the entry point it was called through:
  - `toolName`, or a Copilot tool name, means Copilot
  - `workspace_roots` or `conversation_id` means Cursor
  - anything else means Claude Code
- **It maps the tool name with that tool's table,** reads that tool's path and agent fields, resolves the role, and calls E03's `allow`.
- **It answers in that tool's protocol,** and always exits 2 on a deny, which every one of the three treats as a deny. An allow is exit 0, with no output, except in Cursor, whose permission hooks must answer with JSON: there an allow prints `{"permission": "allow"}` (amended 20 Nov 2026, after the Cursor CLI live check).
- **It fails closed in every case it controls:**
  - every error takes the deny path
  - Cursor's hook is registered with `failClosed: true`
  - Claude Code's keeps `onFailure: "block"`

  Timeouts in Copilot and Claude Code still let the call through. The gate's lock check is the backstop for that.
- **Cursor's `Write` passes for a role that lists `edit` or `write`,** because Cursor matches both as `Write`. Cursor can't name the calling agent, so its role comes from `FACTORY_ROLE` only.

## Consequences

- A call is judged the same way whichever config fired the hook, so a hook that fires twice gives the same answer both times.
- Adding a fourth tool means one row in each table: a recognition rule, a name map and a deny protocol.
- Shape recognition can be wrong if two tools converge on the same payload. The tests use each tool's documented payloads, and a recognition change goes in a new ADR.
- In Cursor, a role set by `FACTORY_ROLE` applies to every subagent of the session, because Cursor can't distinguish them. Roles there are coarser than in Claude Code or Copilot.
