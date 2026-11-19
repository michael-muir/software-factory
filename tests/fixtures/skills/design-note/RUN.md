# Fixture run: design-note

The Architect follows the skill once, from the approved spec in `before/` to a design, an ADR and a task in `after/`.

1. Read the spec. The only seam needed is a direct call to `greet`.
2. Wrote `docs/design/E01-greeting-design.md` from the template, with the spec linked and one slice covering AC-01 to AC-03.
3. Recorded one lasting decision as ADR 0001: `greet` returns the string and doesn't print.
4. `docs.py check`: no problems. `state.py task new E01-T1 "greet with names, case and the empty name"`, then filled in its goal, ACs and notes.
5. The product owner accepted; the design and ADR say Accepted.
