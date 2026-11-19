---
name: spec-interview
description: Interviews the requester one decision at a time and writes a spec with numbered, testable acceptance criteria from the spec template. Use when a new piece of work needs a spec, or a draft spec has open questions.
---

# Spec interview

Used by: `spec-writer`.

## When to use

- A request has arrived and there's no approved spec for it yet.
- A draft spec has open questions that only the requester can answer.

## Steps

1. Read the request, the PRD or roadmap entry, and related specs and ADRs. List the decisions that would change what gets built: scope, formats, limits and trade-offs.
2. Ask the requester about those decisions, at most four at a time. Give each one options, put your recommendation first, and say why. Don't ask what the sources or sensible defaults already answer.
3. Write `docs/specs/<EPIC>-<slug>.md` from `.factory/workflow/templates/spec.md`: the goal, the decisions in force, what's in and out of scope, numbered acceptance criteria (`- **AC-01**` ...) that a test can check, and the assumptions the requester should confirm.
4. Run `python .factory/workflow/docs.py check`, and fix every problem it reports.
5. Ask for approval. Once the requester approves, set the status line to **Approved** with the date, mark the assumptions confirmed, and commit.

## Done when

- The spec passes `docs.py check`, and every acceptance criterion names something a test can observe.
- Every decision the requester made is in "Decisions in force", and every guess is in "Assumptions".
- The product owner has approved the spec, and its status line says so.
