# E07 · Changelog check — Spec

Issue: [#7](https://example.com/issues/7) · Milestone: M2 · Depends on: nothing
Status: **Draft, awaiting product owner approval** · Next: approval, then design

## Goal

A gate check fails a change to user-facing code that has no changelog entry. Retro found the same finding in two jobs: E05-T1 F1 ("No changelog entry for a user-facing change") and E06-T2 F1 ("Changelog not updated for the new command").

## Decisions in force (product owner, pending)

| Topic | Proposal |
| --- | --- |
| Where | A gate check, the cheapest place that would have caught both |

## In scope

- A check that a diff touching `src/` also touches the changelog's Unreleased section.

## Out of scope

- Judging the entry's wording.

## Acceptance criteria

- **AC-01** A diff that changes `src/` without an Unreleased entry fails the check.
- **AC-02** A diff with an Unreleased entry passes.
- **AC-03** A diff that only changes tests or docs passes.

## Assumptions (to confirm with approval)

1. "User-facing" means files under `src/`.
