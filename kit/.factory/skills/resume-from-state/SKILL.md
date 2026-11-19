---
name: resume-from-state
description: Starts a session from the .agentic state files alone, with state.py resume, and checks for work in flight before acting. Use when a session begins, or resumes after a pause, a usage limit or a hand-over.
---

# Resume from state

Used by: `adversary`, `architect`, `debugger`, `docs-writer`, `implementer`, `integrator`, `perf-reviewer`, `release-manager`, `retro`, `router`, `security-reviewer`, `spec-reviewer`, `spec-writer`, `standards-reviewer`, `test-designer`, `verifier`.

## When to use

- At the start of every session in a factory repo.
- After a pause, when work may have moved on without you.

## Steps

1. Run `python .factory/state/state.py resume`. Read the phase, the active task, its open findings and the newest handoff.
2. Fetch, and look for work in flight that the files may not show yet: local and remote branches for the task, open PRs, and uncommitted or unpushed changes. Another session may be working, or may have stopped mid-step.
3. If there is unpushed work for the task, continue from it. Don't start the same work twice. If two sessions might be active, ask a human before touching anything.
4. Follow the handoff's `## Next` steps in order. If a step needs a person's approval, ask for it before doing it.

## Done when

- You can state the active task, its status, and the next step, citing the handoff.
- You've checked branches, PRs and the working tree, and no one else's work was overwritten or repeated.
