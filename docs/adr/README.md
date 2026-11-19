# Architecture Decision Records

Each file in this folder records one decision that shapes the project: what was decided, why, and what follows from it. ADRs outlive any session or model, so write them for a reader who wasn't there.

## Numbering

Files are named `NNNN-short-title.md` with a four-digit number, starting at `0001`. Take the next free number. Numbers are never reused, and an ADR is never deleted: when a decision changes, write a new ADR and set the old one's status to `Superseded by NNNN`.

## Format

```markdown
# NNNN · Title, phrased as the decision

Status: Proposed | Accepted | Superseded by NNNN · Date: YYYY-MM-DD

## Context

The forces at play: the problem, constraints and options considered.

## Decision

What was decided, stated plainly.

## Consequences

What becomes easier or harder, and what must now be true.
```
