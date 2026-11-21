# 0027 · PR evidence matches rebased commits by patch-id

Status: Accepted · Date: 2026-11-20 · Epic: E08

## Context

`check-pr --commits` (E08 AC-10) required the gate evidence's commit to be one of the PR's commits. #74 was rebased before it merged. That gave every commit a new SHA, so the check failed the evidence, even though the change was the same.

The product owner decided that a clean rebase still counts, and a changed commit still fails, by comparing `git patch-id --stable`. CI then needs the evidence commit's patch-id when that commit is no longer on the branch.

- **Fetching the commit by SHA:** GitHub serves orphaned commits today. #74's 673a350 could still be fetched. But no documented guarantee covers it, and `refs/pull/<n>/head` follows the latest push. An unreachable commit can be garbage-collected.
- **Recording the patch-id:** `evidence.py` drafts the body from the commit the gate ran on, which is in the author's clone. It can compute the patch-id there and write it beside the SHA.

## Decision

- **`evidence.py` records the patch-id** in the summary line, after the commit: ``on `<sha>` (patch-id `<40 hex>`)``. It does this when git in the repo has the commit and the commit has a diff. Otherwise the line is as before.
- **`check-pr --commits`** matches by SHA first. If that fails, it computes the patch-id of each of the PR's commits with git in the root, and matches the evidence's patch-id against them.
- **The evidence's patch-id** is the commit's own, when git has the commit. Otherwise it's the one the body records. A recorded patch-id that disagrees with the commit is therefore ignored, not trusted.
- **CI fetches nothing extra.** The `pr-evidence` job already has the PR's commits (`fetch-depth: 0`). The job's command line doesn't change.

## Consequences

- A rebase no longer needs a gate rerun and a redrafted body just to satisfy `--commits`. A rebase that changes a commit's diff still does.
- The match is per commit: the evidence commit's own diff, not the whole branch. A rebase onto a moved base passes, although the gate ran on the old base. CI's gate run on the PR's head covers the new base.
- The recorded patch-id is author-written text, as the SHA is. CI checks that the patch-id belongs to the PR, not that the gate ran there. That's the same trust as before.
- `check-pr --commits` now runs git when the SHA doesn't match. Without git, or outside a repo, only the SHA can match.
