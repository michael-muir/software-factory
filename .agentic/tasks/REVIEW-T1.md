+++
id = "REVIEW-T1"
title = "Code review: behaviour-preserving refactors and shared test fixtures"
status = "done"
review_round = 0
created = 2026-11-19T07:37:03Z
updated = 2026-11-19T13:34:01Z
+++

## Goal

Items 1-7 and 12 from the code review: one module loader per package, one load step in agents.py, public state.py helpers, one repo-path check, one field checker, gate tidy-ups, agents.py main(), and shared fixtures in unlocked tests.

## Acceptance criteria

No behaviour change: the existing tests pass unchanged, except fixture moves in unlocked test files.

## Notes

Product owner approved the plan on 18 Nov 2026, after the design was checked against assets/software-factory-overview.png and assets/line-monitor.png. Item 12 dropped after a closer look: in the unlocked tests only a 4-line clock fixture repeats, and sharing it adds an import for no gain; the larger repeats are in the locked agents tests. Merged in #55 (5060c3e); CI passed on three OSes.
