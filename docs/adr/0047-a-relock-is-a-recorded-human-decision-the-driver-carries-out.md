# 0047 · A relock is a recorded human decision the driver carries out

Status: Accepted · Date: 2026-11-26 · Epic: E13

## Context

The live run on #82 (#109) needed E08-T2's locked tests relocked. No role in the pipeline may edit a locked file or relock one (E03), so the Debugger said in prose that a human was needed. `claude -p` exits 0 whatever the agent decides, so the driver read the session as a success and spent its `gate_retries` rerunning a gate that couldn't pass. `agents.py` had no way to record who approved a relock, and `pipeline.py approve` knew only `spec`, `design` and `merge`. The orchestrator relocked by hand on the job's branch (`dc006d3`). The options were:

- **Let a role relock.** That breaks the rule that a locked test changes only with a human's approval.
- **Leave relocks to a human's hand fix, then `resume`.** That works, but the decision isn't recorded, and the human has to know `#79`'s rule that `--replace` keeps only the files listed.
- **Record the decision with a command, and have the driver carry it out.**

## Decision

The product owner's decisions of 26 Nov 2026:

1. **`agents.py lock --approved-by NAME`** writes `approved_by` into the lock record (from `dc006d3`, byte for byte). `agents.py check` accepts it as an optional non-empty string. A blank name is refused, and a record without it stays valid.
2. **`pipeline.py approve <job> relock --task <id> --by NAME [--files f...]`** is accepted only while the job is `needs-human`, at a slice stage. It reads the task's lock record on the slice's last branch. `--files` defaults to the locked files whose hashes no longer match there. It refuses when nothing changed and no files are named, when a named file isn't on the branch, and when a changed file isn't approved. It records the decision with its files and the Debugger's blocker findings, raises the attempt, and sets the job `ready`, as `resume` does. If a test's content must change, the product owner commits that on the slice branch before approving.
3. **The next `run` carries it out,** before the stopped stage reruns, as driver commands on the slice's runner job:
   - It checks that only the approved files' hashes changed against the committed record. Otherwise it stops for a human, and nothing is written.
   - It sends `agents.py lock --replace <task> <every file already in the record, plus the approved ones> --approved-by NAME`. Listing every file keeps `#79` from dropping one.
   - It marks the Debugger's blocker findings that stopped the job `fixed` with `state.py finding set`: the human's decision answers them, so the review stage doesn't stop on them again.
   - It commits the lock record (and the task file) as `test(<task>): relock approved by NAME`.
   - Then the stage reruns from its start, with fresh gate retries.
4. **The Debugger asks for a human with a finding,** not with prose or an exit code: `state.py finding add <task> --severity blocker "<what is needed>"`. After each Debugger session in the gate stage, the driver reads the task file in the worktree. An open blocker that the gated commit didn't have stops the job as `needs-human`, lists the findings, and spends no more retries. If the Debugger left the finding uncommitted, the driver commits it first, so it's on the branch.

## Consequences

- A relock always names who approved it, in the lock record, the pipeline record and the commit.
- `approve relock` changes no branch. Only the driver writes, through the runner, so every step is in the runner's log and survives a crash like any other command.
- Only `approve` knows `relock`. `reject relock` is bad input: a relock the human won't approve is answered with `resume --note` or `cancel`.
- A blocker finding is now the one way any slice role can stop the job on purpose. The review stage already stopped on one. The gate stage now does too, for the Debugger.
- The relock step adds two or three runner commands to the segment, within E16's turn cap.
