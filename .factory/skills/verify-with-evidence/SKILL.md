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

1. **When the driver hands you a report:** in a pipeline session, `$FACTORY_GATE_REPORT` names the JSON report of the driver's own full gate run. Use it, don't run the gate, and go on to step 3. On a slow machine a full run outlasts a session.
2. Otherwise, check out the exact commit under review, with a clean working tree. Don't edit files while the gate runs: a change mid-run spoils the result. Use a separate worktree if others are working. Run the full gate: `python .factory/gates/gate.py` (or `uv run python .factory/gates/gate.py`). Keep the whole report.
3. Read the report: `Locks` must say none changed, `Docs` must have no problems, and every check must pass or be `n/a`. For a report the driver handed you, also check that it was a full run from a clean tree: `dirty` is false, and no check was skipped as `not selected` (that's what `--checks` leaves). Its `commit` must be `HEAD`, or `git diff --stat <commit> HEAD` shows changes only under `.agentic/`.
4. For each AC in the slice, find a passing test tagged with its id.
5. Record the result: the verdict, the commit, and each check with its time, in the handoff and later the PR. In a pipeline session you can't commit or write a handoff file, so end with your handoff note, under its three headings, as your final reply. The driver records and commits it.
6. In a pipeline session, end that final reply with the line `VERDICT: pass`, or `VERDICT: fail <checks>` naming the failing checks. The driver reads the last such line, and a reply without one counts as a fail.

## Done when

- The report is from the commit under review (or, handed over by the driver, from a commit that differs from it only under `.agentic/`), from a full run with no `--checks`, and its verdict is PASS.
- Every AC in the slice has a passing test tagged with its id.
- The report is recorded in the handoff, with the commit it ran on. In a pipeline session, the handoff is your final reply.
