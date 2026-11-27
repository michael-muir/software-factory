# Fixture run: debugging

The Debugger follows the skill once on `before/`, where `test_keeps_the_names_case` is red.

1. Reproduced: `pytest -q` fails `test_keeps_the_names_case` with `'Hello, Mcdonald!' != 'Hello, McDonald!'`.
2. Hypothesis: `greet` re-cases the name, because it calls `name.title()`.
3. Experiment: `"McDonald".title()` gives `"Mcdonald"`. Confirmed. The same call would also break `"van der Berg"`.
4. The fix needs no relock and no human's decision: it changes only `greet`, and the new test is a new file. So no blocker finding.
5. Fixed the root cause by dropping `.title()`, and added the regression test `test_does_not_recapitalise_particles`, which fails without the fix.
6. All four tests pass. Root cause for the handoff: "`greet` called `str.title()`, which re-cases names; it now keeps them as typed."
