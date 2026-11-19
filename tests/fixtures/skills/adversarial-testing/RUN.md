# Fixture run: adversarial-testing

The Adversary follows the skill once on slice E01-T1.

1. Resumed from state; read the task, AC-01 to AC-03 and the diff (`src/greet.py`).
2. Attacks listed: a blank name of only spaces, a name with a newline, and a very long name.
3. Wrote all three in a new file, `tests/test_attack_inputs.py`, and changed no existing file.
4. Ran them: the blank name and the newline broke the change, and the long name held. `state.py finding add` twice, both minor: F1 (line 4) and F2 (line 8).
5. Verdict in the handoff: two findings to resolve. The long-name test is kept, for the Test Designer to adopt.
