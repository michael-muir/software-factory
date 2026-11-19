---
name: verify-with-evidence
description: Runs the full gate on a slice and keeps its report as the evidence; a claim of done without a report counts for nothing. Use when a slice is ready for review, or anyone says it passes.
---

# Verify with evidence

Used by: `verifier`.

## When to use

- A slice says it's green and is ready for the reviewers.
- Anyone claims a change passes, and the claim has no report behind it.

## Steps

1. Check out the exact commit under review, with a clean working tree. Don't edit files while the gate runs: a change mid-run spoils the result. Use a separate worktree if others are working.
2. Run the full gate: `python .factory/gates/gate.py` (or `uv run python .factory/gates/gate.py`). Keep the whole report.
3. Read the report: `Locks` must say none changed, `Docs` must have no problems, and every check must pass or be `n/a`.
4. For each AC in the slice, find a passing test tagged with its id.
5. Record the result: the verdict, the commit, and each check with its time, in the handoff and later the PR.

## Done when

- The report is from the commit under review, from a full run with no `--checks`, and its verdict is PASS.
- Every AC in the slice has a passing test tagged with its id.
- The report is recorded in the handoff, with the commit it ran on.
