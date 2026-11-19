# E01 · Greeting — Spec

Issue: [#1](https://example.com/issues/1) · Milestone: M1 · Depends on: nothing
Status: **Approved by the product owner, 19 Nov 2026** · Next: Architect design note and ADRs

## Goal

`greet` returns a greeting for a name, so the CLI can say hello. Names keep the case the user typed.

## Decisions in force (product owner, 19 Nov 2026)

| Topic | Decision |
| --- | --- |
| Empty name | Greet the world: `Hello, world!` |
| Case | Keep the name exactly as typed |

## In scope

- A `greet(name)` function and its tests.

## Out of scope

- Translations, and the CLI's argument parsing.

## Acceptance criteria

- **AC-01** `greet("Ada")` returns `Hello, Ada!`.
- **AC-02** `greet("McDonald")` keeps the name's case: `Hello, McDonald!`.
- **AC-03** `greet("")` returns `Hello, world!`.

## Assumptions (confirmed with approval, 19 Nov 2026)

1. Leading and trailing spaces are kept as typed.
