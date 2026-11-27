---
name: debugging
description: Finds and fixes the root cause of a red gate or failing test, one hypothesis at a time, and adds a regression test. Use when the gate goes red and the cause isn't obvious from the first error.
---

# Debugging

Used by: `debugger`.

## When to use

- The gate or a test fails, and the first error doesn't explain why.
- The same failure has come back after a fix.

## Steps

1. Reproduce the failure with the exact command that failed, and keep its output. If you can't reproduce it, record what you tried and stop there.
2. Form one hypothesis about the root cause, and write it down: "X fails because Y".
3. Test the hypothesis with the smallest experiment that could prove it wrong: a print, a narrower test or a bisect. If it's wrong, go back to step 2 with what you learned.
4. If the fix needs a relock or a human's decision, record a blocker finding saying what (`python .factory/state/state.py finding add <task> --severity blocker "<what is needed and why>"`), and stop.
5. Fix the root cause, not the symptom. Add a regression test that fails without the fix and passes with it. Never edit a locked test, skip a check or loosen a threshold.
6. Run the full gate, and write the root cause and the fix in the handoff (skill: handoff).

## Done when

- The failing command passes, and the full gate passes.
- A regression test exists that fails without the fix.
- The handoff states the root cause in one sentence, and what proved it.
