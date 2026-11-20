---
name: threat-check
description: Runs a threat check on a change: inputs, secrets, permissions, dependencies and data exposure, rating each threat by likelihood and impact. Use when a slice has passed the Verifier and needs its security review.
---

# Threat check

Used by: `security-reviewer`.

## When to use

- The Verifier has passed a slice, and the reviewers are next.
- Always for changes that touch input handling, auth, secrets, shell or file access, or dependencies.

## Steps

1. Start with skill: resume-from-state. Then read the task, the spec's acceptance criteria for the slice, and the diff (`git diff <base>...HEAD`).
2. Run the gate for evidence, `python .factory/gates/gate.py`, and read its report. A red gate is a finding in itself.
3. Check every input that crosses a trust boundary (command lines, files, network, environment), any secret in code, config or logs, the permissions the change needs, new or bumped dependencies, and what data the change can expose. Rate each threat by its likelihood and impact.
4. Record each finding: `python .factory/state/state.py finding add <task> --severity <blocker|major|minor> "<file>:<line> <what is wrong, and why>"`. A blocker must not merge, a major must be fixed before merge, and a minor is fixed or explained.
5. Give the verdict in the handoff (skill: handoff): pass, or the open findings that must be resolved. Don't fix anything yourself.

## Done when

- Every finding is in the task file, with a severity (blocker, major or minor) and a `file:line`.
- Each threat says where untrusted input enters and what it can reach, and any injection or leaked secret is a blocker.
- No code, test or doc was changed by the review.
