# Fixture run: standards-review

The Standards Reviewer follows the skill once on slice E01-T1, whose change is `slice.diff`: it adds `src/greet.py` and `tests/test_greet.py`. The repo installs the kit's real Python pack in `.factory/standards/python/rules.md`.

1. Resumed from state; read the task and the diff. `standards.py select --base-ref main` listed one pack, `python`, for both files, with its 18 rules in force.
2. Ran the gate for evidence: green.
3. Both modules have a docstring, and `greet`'s is a command ending in a period. `greet_list` has type hints, but no docstring (breaks PY-015), and its parameter `str_list` is named for its type (breaks PY-009). Nothing else breaks a rule in force.
4. `state.py finding add --rule` twice, each with the rule's own severity and `src/greet.py:9`: F1 (PY-015, minor) and F2 (PY-009, major).
5. Verdict in the handoff: not yet a pass. F2 is major and must be fixed before merge; F1 is fixed or explained.
