---
name: spec-review
description: Checks a change against every acceptance criterion in its spec and records each gap as a finding. Use when a slice has passed the Verifier and needs its spec review.
---

# Spec review

Used by: `spec-reviewer`.

## When to use

- The Verifier has passed a slice, and the reviewers are next.
- Review alone: don't read other reviewers' findings before recording yours.

## Steps

1. Start with skill: resume-from-state. Then read the task, the spec's acceptance criteria for the slice, and the diff (`git diff <base>...HEAD`).
2. Run the gate for evidence, `python .factory/gates/gate.py`, and read its report. A red gate is a finding in itself.
3. For each AC in the slice, find the code that meets it and the test that proves it, and mark it met, partly met or missing. Flag any behaviour in the diff that no AC asked for.
4. Record each finding: `python .factory/state/state.py finding add <task> --severity <blocker|major|minor> "<file>:<line> <what is wrong, and why>"`. A blocker must not merge, a major must be fixed before merge, and a minor is fixed or explained.
5. Give the verdict in the handoff (skill: handoff): pass, or the open findings that must be resolved. Don't fix anything yourself.

## Done when

- Every finding is in the task file, with a severity (blocker, major or minor) and a `file:line`.
- Each AC in the slice is marked met, partly met or missing, and every gap names its `AC-nn`.
- No code, test or doc was changed by the review.
