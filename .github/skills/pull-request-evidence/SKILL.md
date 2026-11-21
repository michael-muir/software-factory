---
name: pull-request-evidence
description: Drafts a slice's PR body from the gate's JSON report with evidence.py, fills in what only the author knows, and checks it with check-pr --strict before the PR opens. Use when a slice has passed the Verifier and its reviewers, and is ready for a pull request.
---

# Pull request evidence

Used by: `integrator`.

## When to use

- A slice's branch passes the gate, its reviewers' findings are recorded in its task file, and it needs a PR.
- Not for a PR that spans several tasks: `evidence.py` drafts for one task. Write that body by hand from `.factory/workflow/templates/pr-evidence.md`, and still check it with `check-pr --strict`.

## Steps

1. Commit everything first. A report from a tree with uncommitted changes proves no commit, and `evidence.py` refuses it.
2. Run the full gate and save its JSON report from the same run: `python .factory/gates/gate.py --json-out gate-report.json`. Keep the report outside the repo, or ignored by git, so the tree stays clean.
3. Draft the body: `python .factory/workflow/evidence.py <task> --gate-report gate-report.json --out pr-body.md`. It writes the first line with the ACs and the issue, the AC trace from the locked tests' tags, the tests and their lock commit, the gate's summary line (the commit and its patch-id) with the full report in `<details>`, and the task's findings.
4. Replace every `TODO(author)` placeholder: the summary sentence after `<EPIC>/<Tn>:`, and "What changes", one bullet per change with what it does and why. If the task has no lock record, write the trace by hand. Add what a reviewer needs and the draft can't know: relocks, changed tests of other epics, where the gate ran.
5. Check it: `python .factory/workflow/docs.py check-pr --strict pr-body.md --commits $(git rev-list <base>..HEAD)`. Fix each problem it prints and check again until it exits 0.
6. Push the branch and open the PR with the body. Then watch CI, where the `pr-evidence` job runs the same check on every edit.
7. If the branch is rebased later, `--commits` still matches the evidence's commit by its patch-id, as long as the rebase didn't change that commit. If it did, or new commits change the code, rerun the gate and draft again. A body written before `evidence.py` recorded patch-ids has none, so after a rebase, add `(patch-id <id>)` beside its commit, with the ID in backticks, using the ID from `git show <sha> | git patch-id --stable`.

## Done when

- The PR body passes `docs.py check-pr --strict --commits` with the PR's own commits, and no `TODO(author)` is left.
- The gate evidence names a commit of the PR, from a clean tree, and holds the full report.
- Every AC the slice covers lists the tests that prove it, and every finding is listed with its status.
