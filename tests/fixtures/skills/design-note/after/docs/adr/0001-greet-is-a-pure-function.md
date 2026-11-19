# 0001 · greet is a pure function

Status: Accepted · Date: 2026-11-19 · Epic: E01

## Context

The CLI prints the greeting, and tests need to check it. Printing inside `greet` would make tests capture output.

## Decision

`greet` returns the string, and the CLI prints it.

## Consequences

Tests compare strings directly. Any future output format lives in the CLI, not in `greet`.
