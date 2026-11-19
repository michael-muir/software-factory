---
name: handoff
description: Writes a handoff note with state.py so the next session can carry on from files alone. Use when a session ends, a task changes hands, or work pauses for a decision.
---

# Handoff

Used by: `adversary`, `architect`, `debugger`, `docs-writer`, `implementer`, `integrator`, `perf-reviewer`, `release-manager`, `retro`, `router`, `security-reviewer`, `spec-reviewer`, `spec-writer`, `standards-reviewer`, `test-designer`, `verifier`.

## When to use

- At the end of every session, and before any pause that could outlast it, such as waiting for an approval or nearing a usage limit.
- When a task passes from one role to another.

## Steps

1. Update the task's status: `python .factory/state/state.py task set <task> --status <status>`.
2. Write the note with three headings:
   - `## Done`: what changed, with commit ids, gate results and PR numbers
   - `## Next`: numbered steps, in order
   - `## Open questions`: what needs a person, or "None."
3. Record it: `python .factory/state/state.py handoff <task> --from "<who>" --body-file <file>` (or pipe it on stdin).
4. Run `python .factory/state/state.py check`, and commit the `.agentic/` changes with the work they describe.

## Done when

- The handoff file exists in `.agentic/handoffs/` with `## Done`, `## Next` and `## Open questions`, and `state.py check` passes.
- A new session that runs skill: resume-from-state can say what to do next without asking.
- Nothing the next step depends on exists only in the session's memory or an unpushed scratch file.
