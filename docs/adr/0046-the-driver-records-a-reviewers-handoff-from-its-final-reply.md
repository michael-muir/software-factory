# 0046 · The driver records a reviewer's handoff from its final reply

Status: Accepted · Date: 2026-11-26 · Epic: E13

## Context

In the live run on #82 (issue #106), the Verifier and the Spec Reviewer couldn't record a handoff. Five reviewer roles have a scoped `run` and no Write tool: `verifier`, `spec-reviewer`, `standards-reviewer`, `security-reviewer` and `perf-reviewer`. For them the E03 hook refuses any command with shell control characters or line breaks. So a handoff body can't reach `state.py handoff`, whether by stdin, a heredoc, multi-line text or a body file. Each also reran the full gate, which takes about 60 minutes on the product owner's Windows machine. The options were:

- **A `state.py handoff --body -`** that reads stdin. The hook still refuses the pipe or the heredoc that would feed it.
- **A scoped Write to `.agentic/handoffs/`.** That's a new tool rule in the hook and in every adapter, for one file.
- **The driver records the note** from the session's final reply.

## Decision

The product owner chose the third option on 26 Nov 2026.

- **The prompt.** A role without a shell (no `run`, or a scoped `run`) gets the last line "Don't commit: the driver commits your files. End with your handoff note as your final reply, and stop." The driver knows which from the role's card (`has_shell`) and passes it to `prompt()`.
- **The reply.** After the session of a reviewer without a shell, the driver reads the session's log: the `result` field of its JSON output, or the plain output when there's no JSON. If the reply has the three handoff headings, the driver writes it intact to the worktree's scratch folder and sends one internal command, `pipeline.py _handoff TASK ROLE BODY MESSAGE -- PATH...`. That runs `state.py handoff <task> --from <role> --body-file <body>` and commits the new note with the task file's findings. A reply without the headings adds a warning to the record, and the stage goes on. The session's entry records which it was, so a crash never records a note twice.
- **The gate report.** Every review session gets the task's newest gate report as `$FACTORY_GATE_REPORT`. The Verifier checks the report instead of running the gate. The other reviewers may run one targeted check with `gate.py --checks <name>`.

## Consequences

- There's no hook change and no new tool, so the E03 hook still holds the reviewers to read-only commands.
- The note is the reply as the reviewer wrote it. The Verifier's `VERDICT:` line (E13-T6) stays in it.
- A reply the driver can't read as a handoff loses only the note, not the stage. The warning says which session it was.
- The spec-writer, the architect and the docs-writer get the same last line, but the driver records a handoff only at the review stage. Their replies stay in the session logs.
