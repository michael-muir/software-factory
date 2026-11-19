# 0020 · Document problems fail the verdict, not the run

Status: Accepted · Date: 2026-11-19 · Epic: E04

## Context

The gate already handles three kinds of problem found before any check runs:
- **Invalid configuration, state or agent files:** exit 2, nothing runs. The gate can't trust its inputs.
- **A broken test lock:** verdict `fail`, exit 1, nothing runs (ADR 0018). The tests can no longer be trusted to judge the code.

A spec missing its acceptance criteria is different. The code and tests are still trustworthy; only the paperwork is incomplete. The product owner chose that it fails the verdict (spec decision). Whether the checks still run was left to the design.

## Decision

- **Document problems fail the verdict (exit 1), and the checks still run.** An author then sees every problem in one gate run, document and code alike, instead of fixing a heading only to learn of a failing test next.
- **The report always carries document status.** The text report has `Docs: N checked, M problems` followed by one line each. The JSON has `"docs": {"checked": N, "problems": [...]}`. The Verifier, PR evidence (E08) and the Line Monitor read it, as they read lock status (ADR 0018, amended).
- **Order:** validation of config, state and agents (exit 2), then locks (stop on breach), then documents (record), then the checks.

## Consequences

- One gate run gives the full picture. Gate health on the Line Monitor can show document failures separately from check failures.
- A repo with a malformed document can't merge until it's fixed, even when its code is perfect. That's the intent: "done" includes the documents.
- The three kinds of pre-check problem now behave differently (stop, stop, record). The report states which ones apply, so the difference is visible rather than hidden.
