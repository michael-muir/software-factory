# 0044 · Approvals commit status lines with git plumbing, without a checkout

Status: Proposed · Date: 2026-11-21 · Epic: E13

## Context

`pipeline.py approve` must record the approval and change the spec's or design note's status line, committed on the plan branch (spec AC-11). At a checkpoint the driver has closed its runner job (ADR 0041), so there may be no worktree for that branch. The approver may run `approve` from the main checkout, whose working tree must not be touched. The options were:

- **Leave the edit to the next `run`,** in a new segment. That delays the commit, and the spec says `approve` does it.
- **Add a temporary worktree,** edit, commit and remove it. It's slow, and it leaves debris if interrupted.
- **Commit with git plumbing.**

## Decision

`approve` builds the commit directly:

1. Read the document with `git show <branch>:<path>`, and replace its `Status:` line. It checks the new text with `docs.lint`, so a bad edit never lands.
2. Write the blob with `git hash-object -w`.
3. With a temporary `GIT_INDEX_FILE`, run `read-tree <branch>`, then `update-index --cacheinfo`, then `write-tree`.
4. Create the commit with `commit-tree -p <branch>`.
5. Move the branch with `git update-ref refs/heads/<branch> <new> <old>`. If the branch moved in the meantime, the update is refused and nothing changes.

The commit's author is the approver's git identity, and its message is `docs(<EPIC>): spec approved by <name>` or `design accepted by <name>`.

## Consequences

- No working tree is touched, and an interrupted `approve` leaves at most an unreferenced object.
- The same helper can later commit other small file changes for E19 or E24, such as approvals from GitHub threads.
- Plumbing is less familiar than porcelain. The tests check the resulting tree, the parent and the refusal on a moved branch.
