---
name: adversarial-testing
description: Writes attack tests in new files that try to break a change, and records each attack that works as a finding. Use when a slice has passed the Verifier and needs its adversarial review.
---

# Adversarial testing

Used by: `adversary`.

## When to use

- The Verifier has passed a slice, and the reviewers are next.
- Review alone: don't read other reviewers' findings before recording yours.

## Steps

1. Start with skill: resume-from-state. Then read the task, the spec's acceptance criteria for the slice, and the diff (`git diff <base>...HEAD`).
2. List the attacks: edge cases, bad or hostile input, misuse of the API, ordering and races, and resource limits.
3. Write each attack as a test in a new file, `tests/test_attack_<topic>.py`. Never edit an existing file: if an attack needs a fixture changed, record that as a finding instead.
4. Record each finding: `python .factory/state/state.py finding add <task> --severity <blocker|major|minor> "<file>:<line> <what is wrong, and why>"`. A blocker must not merge, a major must be fixed before merge, and a minor is fixed or explained.
5. Give the verdict in the handoff (skill: handoff): pass, or the open findings that must be resolved. Don't fix anything yourself.

## Done when

- Every attack is in a new file, and no existing file changed apart from the task file.
- Every attack that broke the change is a finding, with its severity and the `file:line` of the attack.
- Attacks that didn't break anything are kept, so the Test Designer can adopt them.
