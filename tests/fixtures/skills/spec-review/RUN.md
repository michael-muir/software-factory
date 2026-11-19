# Fixture run: spec-review

The Spec Reviewer follows the skill once on slice E01-T1.

1. Resumed from state; read the task, AC-01 to AC-03 (`docs/E01-acs.md`) and the diff (`src/greet.py`, `tests/test_greet.py`).
2. Ran the gate for evidence: green, which only means the existing tests pass.
3. AC-01: met, by `test_greets_by_name`. AC-02: met, by `test_keeps_the_names_case`. AC-03: missing. `greet("")` returns `Hello, !`, and no test covers it.
4. `state.py finding add E01-T1 --severity major "src/greet.py:3 AC-03 is not met: ..."` added F1.
5. Verdict in the handoff: not passed; F1 must be resolved.
