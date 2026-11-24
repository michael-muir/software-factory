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

1. Start with skill: resume-from-state. Then read the task, the spec's acceptance criteria for the slice, and the diff (`git diff <base>...HEAD`). List the rules in force for the change with `python .factory/standards/standards.py select --base-ref <base>`: it reads the packs in `.factory/standards/` and shows which apply to the changed files, and which of their rules are in force. Read only those rules.
2. Run the gate for evidence, `python .factory/gates/gate.py`, and read its report. A red gate is a finding in itself.
3. Check each changed line against the rules in force. Cite every break by its rule id. If no rule in force covers something, it isn't a finding, however much you'd like it changed: leave matters of taste alone.
4. Record each finding: `python .factory/state/state.py finding add <task> --severity <blocker|major|minor> --rule <id> "<file>:<line> <what is wrong, and why>"`. Use the rule's own severity unless the summary says why not. A blocker must not merge, a major must be fixed before merge, and a minor is fixed or explained. `state.py` refuses a rule id that isn't in force.
5. Give the verdict in the handoff (skill: handoff): pass, or the open findings that must be resolved. Don't fix anything yourself.

## Done when

- Every finding is in the task file, with a severity (blocker, major or minor) and a `file:line`.
- Every finding was recorded with `--rule`, citing a rule id that is in force in the pack.
- No code, test or doc was changed by the review.
