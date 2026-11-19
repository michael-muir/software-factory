# Fixture run: threat-check

The Security Reviewer follows the skill once on slice E01-T1.

1. Resumed from state; read the task and the diff (`src/announce.py`).
2. Ran the gate for evidence: green. Its test only calls `announce("Ada")`.
3. Inputs: `name` comes from the command line, which is untrusted. It reaches `subprocess.run(..., shell=True)`, so a crafted name runs commands with the user's rights (likely, and severe). No secrets, no new dependencies, no data exposure.
4. `state.py finding add E01-T1 --severity blocker "src/announce.py:6 shell injection: ..."` added F1.
5. Verdict in the handoff: blocked until F1 is fixed. No code was changed by the review.
