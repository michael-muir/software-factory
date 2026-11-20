---
name: design-note
description: Turns an approved spec into a design note, ADRs for lasting decisions, and one task file per vertical slice. Use when a spec has just been approved and before any test is written.
---

# Design note

Used by: `architect`.

## When to use

- A spec has been approved and has no accepted design yet.
- The work needs splitting into slices that each ship on their own.

## Steps

1. Read the approved spec and the code it touches. Find the seams where tests can reach each acceptance criterion.
2. Write `docs/design/<EPIC>-<slug>.md` from `.factory/workflow/templates/design.md`: the summary, source layout, test seams, vertical slices (each with the ACs it covers) and risks. Link the spec on the `Spec:` line.
3. Record each decision that outlives the epic as an ADR, `docs/adr/NNNN-<slug>.md`, from `.factory/workflow/templates/adr.md`, with its context, decision and consequences.
4. Run `python .factory/workflow/docs.py check`. Then create a task for each slice with `python .factory/state/state.py task new <id> "<title>"`, and fill in its goal, ACs and notes.
5. Ask for acceptance. Once the product owner accepts, set the design and ADRs to **Accepted**, and commit them with the task files.

## Done when

- The design note and ADRs pass `docs.py check`, and every AC in the spec belongs to exactly one slice.
- Each slice has a task file, and `state.py check` passes.
- The product owner has accepted the design.
