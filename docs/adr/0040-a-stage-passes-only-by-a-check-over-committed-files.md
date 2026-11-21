# 0040 · A stage passes only by a check over committed files, from one stage table

Status: Proposed · Date: 2026-11-21 · Epic: E13

## Context

The full track has nine stages, each owned by a role (E09) running headless (E13). An agent's own report of success is exactly what the factory doesn't trust: the gates are code, and the author never grades the work (PRD). The stages are also described for people in `pipeline.md`, and in each session's prompt, so the same facts would otherwise live in three places. The options were:

- **Trust the session:** a stage passes when the session exits 0. That's simple, but a session that says "done" without doing the work would pass.
- **An agent judges the stage:** a reviewer session decides whether the stage passed. That puts an LLM's opinion where a check belongs.
- **A check in code for each stage,** reading what the stage left in git.

## Decision

- **Every stage has one check function** in `pipeline.py`. It reads a checkout's committed files and history (`git show`, `git log`, `git diff base..head`), and the gate's JSON report where the stage needs it. Uncommitted files never count. The checks reuse the existing validators: `docs.lint`, `state.py check`, `evidence.trace_file`, `agents.py check` and `check-pr --strict`.
- **A session's exit code only says whether to run the check.** A non-zero exit stops the job for a human. A zero exit still has to pass the check.
- **One stage table, `STAGES`,** holds each stage's name, roles, skills, scope, checkpoint, pass condition text and check. The driver moves on only through `next_stage`, a pure function of the table and the record. The prompts take the pass condition text from it, and a test pins `pipeline.md`'s table to it.
- **`pipeline.py check`** runs a check on any checkout, with or without a job, and changes nothing. So a person driving the track by hand gets the same verdict as the driver.

## Consequences

- A session that claims work it didn't do fails its stage, and the job stops with problems that name the missing files.
- Adding a stage, or changing a condition, is one edit to `STAGES` and its check. The tests then make the docs and the prompts follow.
- The checks only see git. Work that isn't committed is lost to the pipeline, so every prompt ends with "commit your work".
- Each condition is a separate branch with a passing test and a failing test, which also feeds the mutation gate.
