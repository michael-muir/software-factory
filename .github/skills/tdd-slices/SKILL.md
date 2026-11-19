---
name: tdd-slices
description: Builds one vertical slice test-first: failing tests per acceptance criterion, locked, then the smallest change to green. Use when a slice's task file is ready and its tests don't exist yet.
---

# TDD slices

Used by: `test-designer`, `implementer`.

## When to use

- A slice's task file names its ACs, and the design note gives the test seams.
- Not for a one-line fix with an existing test: run that test, fix, and run the gate.

## Steps

1. Read the slice's task file, the spec's ACs it covers, and the design note's test seams.
2. Write at least one test per AC, tagged `@pytest.mark.ac("E<epic>-AC-nn")` (or your stack's equivalent). Write it from the spec, never from the code.
3. Run the new tests and check that each one fails for the right reason, such as a missing module or a wrong result, and not a typo in the test.
4. Lock the test files: `python .factory/agents/agents.py lock <task> <files>` (see skill: lock-tests). Commit the tests and the lock record together, as `test(...)`.
5. Implementer: make the smallest change that turns the locked tests green. Don't edit a locked test. If one is wrong, hand it back to the Test Designer.
6. Run the fast tests and the gate's commit checks, then the full gate (skill: verify-with-evidence). Commit the change as `feat(...)` or `fix(...)`.

## Done when

- Every AC in the slice has a test tagged with its id, and the tests were committed and locked before the implementation commit.
- `python .factory/gates/gate.py` passes on the slice's branch, with `Locks: ... none changed`.
- No locked test changed after it was locked, unless a human approved a relock.
