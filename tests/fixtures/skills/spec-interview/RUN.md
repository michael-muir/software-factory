# Fixture run: spec-interview

The Spec Writer follows the skill once, from `before/REQUEST.md` to `after/docs/specs/E01-greeting.md`.

1. Read the request. Decisions that change the build: what an empty name does, and whether names are re-cased.
2. Asked the requester both, with options: "Greet the world (recommended) / raise an error" and "Keep as typed (recommended) / title-case". Answers: greet the world; keep as typed.
3. Wrote the spec from the template: goal, both decisions, scope, AC-01 to AC-03, one assumption (spaces kept as typed).
4. `docs.py check`: no problems.
5. The requester approved; the status line says Approved, and the assumption is marked confirmed.
