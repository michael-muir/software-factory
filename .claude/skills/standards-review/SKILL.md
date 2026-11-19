---
name: standards-review
description: Checks a change against the repo's standards pack and records each rule break as a finding that cites the rule id. Use when a slice has passed the Verifier and needs its standards review.
---

# Standards review

Used by: `standards-reviewer`.

## When to use

- The Verifier has passed a slice, and the reviewers are next.
- Review alone: don't read other reviewers' findings before recording yours.

## Steps

1. Start with skill: resume-from-state. Then read the task, the spec's acceptance criteria for the slice, and the diff (`git diff <base>...HEAD`). Then read the standards pack in `.factory/standards/` for the languages the diff touches.
2. Run the gate for evidence, `python .factory/gates/gate.py`, and read its report. A red gate is a finding in itself.
3. Check each changed line against the pack. Cite every break by its rule id. Leave matters of taste alone: if no rule says it, it isn't a finding.
4. Record each finding: `python .factory/state/state.py finding add <task> --severity <blocker|major|minor> "<file>:<line> <what is wrong, and why>"`. A blocker must not merge, a major must be fixed before merge, and a minor is fixed or explained.
5. Give the verdict in the handoff (skill: handoff): pass, or the open findings that must be resolved. Don't fix anything yourself.

## Done when

- Every finding is in the task file, with a severity (blocker, major or minor) and a `file:line`.
- Every finding cites a rule id that exists in the pack.
- No code, test or doc was changed by the review.
