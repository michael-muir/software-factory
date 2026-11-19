# Fixture run: perf-budget

The Perf Reviewer follows the skill once on slice E01-T1, against `docs/perf-budgets.md`.

1. Resumed from state; read the task, the diff and the budgets (`greet_many`: 10 ms for 10,000 names).
2. Ran the gate for evidence: green. The tests don't measure time.
3. `greet_many` is on the budgeted hot path. Its `greeting not in result` on a list makes it O(n²). Reading settles it, so no benchmark is needed: 10,000 names means about 50 million comparisons, which is far over 10 ms.
4. `state.py finding add E01-T1 --severity major "src/greet.py:11 greet_many ... over the greet_many budget ..."` added F1.
5. Verdict in the handoff: not passed until F1 is fixed (a `set` of seen greetings).
