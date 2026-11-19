+++
id = "REVIEW-T3"
title = "Code review: changed-lines mutation"
status = "done"
review_round = 0
created = 2026-11-19T07:37:03Z
updated = 2026-11-19T15:52:37Z
+++

## Goal

Item 11: mutation_scope changed-lines mutates only changed lines (cosmic-ray mutant line numbers; Stryker line ranges).

## Acceptance criteria

A short spec note, approved by the product owner before the tests.

## Notes

Mutation is the slowest check and the Line Monitor's top gate failure. Merged in #57; CI passed on three OSes.
