---
name: perf-budget
description: Finds the hot paths a change touches and checks them against the repo's performance budgets. Use when a slice has passed the Verifier and needs its performance review.
---

# Perf budget

Used by: `perf-reviewer`.

## When to use

- The Verifier has passed a slice, and the reviewers are next.
- The diff touches code on a hot path: a loop over user data, a request handler, a build step.

## Steps

1. Start with skill: resume-from-state. Then read the task, the spec's acceptance criteria for the slice, and the diff (`git diff <base>...HEAD`). Then read the repo's performance budgets (for example `docs/perf-budgets.md`, or the spec).
2. Run the gate for evidence, `python .factory/gates/gate.py`, and read its report. A red gate is a finding in itself.
3. Find each hot path the diff touches, and check it against its budget: its complexity, its I/O in loops, and its allocations. When reading the code can't settle it, ask for a benchmark rather than guess.
4. Record each finding: `python .factory/state/state.py finding add <task> --severity <blocker|major|minor> "<file>:<line> <what is wrong, and why>"`. A blocker must not merge, a major must be fixed before merge, and a minor is fixed or explained.
5. Give the verdict in the handoff (skill: handoff): pass, or the open findings that must be resolved. Don't fix anything yourself.

## Done when

- Every finding is in the task file, with a severity (blocker, major or minor) and a `file:line`.
- Every finding names the budget it breaks, or says that no budget covers the hot path.
- No code, test or doc was changed by the review.
