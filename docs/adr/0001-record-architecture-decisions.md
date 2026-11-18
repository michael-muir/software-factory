# 0001 · Record architecture decisions

Status: Accepted · Date: 2026-11-17 · Epic: E01

## Context

The blueprint says decisions and the glossary should outlive any single model or session. Agents and people working in later sessions need to know why something is the way it is, not only what it is.

## Decision

- Record each significant decision as a short ADR in `docs/adr/`, named `NNNN-kebab-title.md`.
- Each ADR has these sections: Status, Context, Decision, Consequences.
- Status is one of Proposed, Accepted, Superseded by NNNN, or Rejected.
- An Accepted ADR is never edited for substance. A new ADR supersedes it instead.

## Consequences

- E04 turns this format into the factory's ADR template, and that template is what the kit ships to target repos.
- Reviewers can cite an ADR by number when they flag a change that contradicts it.
