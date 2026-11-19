+++
id = "REVIEW-T2"
title = "Code review: lock hashes, mutation on a temp copy, lock status in the gate report"
status = "todo"
review_round = 0
created = 2026-11-19T07:37:03Z
updated = 2026-11-19T07:37:03Z
+++

## Goal

Items 8-10: lock hashes normalise CRLF only (ADR 0004); mutation testing runs on a temporary copy, never the working tree; the gate's JSON report always carries lock status.

## Acceptance criteria

Each with a short ADR amendment.

## Notes

Watchdog kills runaway workers, so an interrupted mutation run must never leave a mutant behind. The Line Monitor shows locked-test counts.
