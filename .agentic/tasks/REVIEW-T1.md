+++
id = "REVIEW-T1"
title = "Code review: behaviour-preserving refactors and shared test fixtures"
status = "in-progress"
review_round = 0
created = 2026-11-19T07:37:03Z
updated = 2026-11-19T07:37:03Z
+++

## Goal

Items 1-7 and 12 from the code review: one module loader per package, one load step in agents.py, public state.py helpers, one repo-path check, one field checker, gate tidy-ups, agents.py main(), and shared fixtures in unlocked tests.

## Acceptance criteria

No behaviour change: the existing tests pass unchanged, except fixture moves in unlocked test files.

## Notes

Product owner approved the plan on 18 Nov 2026, after the design was checked against assets/software-factory-overview.png and assets/line-monitor.png.
