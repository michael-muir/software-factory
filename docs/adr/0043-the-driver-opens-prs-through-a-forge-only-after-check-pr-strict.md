# 0043 · The driver opens PRs through a small forge interface, and only after check-pr --strict

Status: Accepted · Date: 2026-11-21 · Epic: E13

## Context

The ship stage turns a reviewed slice into a PR with E08's evidence, and the merge checkpoint waits for a human to merge it. GitHub's GraphQL API is blocked for this project, but REST works through `gh api`. The done-when test must run on three OSes without a network, against a local bare origin. The Integrator role has no edit tools, and its card says it must not open a PR for a slice that isn't passed. The product owner decided (21 Nov 2026) that the driver opens the PR, and only after the Integrator's body passes `check-pr --strict`.

## Decision

- **`Forge` has two methods:** `open(branch, base, title, body)` returns a reference, and `state(ref, branch, base)` returns `open`, `merged` or `closed`.
  - **`GitHubForge`** uses `gh api repos/<owner>/<repo>/pulls` (REST, never GraphQL). It reads `merged` and `state` from `pulls/<n>`.
  - **`GitForge`** treats the pushed branch as the PR. A branch is merged when its head is an ancestor of `origin/<base>` after a fetch, and closed when the remote branch has gone unmerged.

  `pipeline.forge` chooses between them.

- **The ship stage runs in this order:**
  1. The Integrator writes the body to `FACTORY_PR_BODY` in the worktree's git dir, by following the pull-request-evidence skill.
  2. The driver runs `docs.py check-pr --strict --commits <the branch's commits>`.
  3. It pushes the branch to `factory/<job>-t<n>`.
  4. It calls `Forge.open`.

  A failing body stops the job before anything is pushed.

- **A merge is detected, never approved.** `approve ... merge` is refused. A PR closed without merging stops the job for a human.

## Consequences

- The evidence check decides whether a PR opens. That's the same check CI's `pr-evidence` job runs.
- The tests pin the REST calls with a stub `gh`, and run the whole line against `GitForge` with no network.
- GitLab and Azure can be added as further forges later.
- Changes requested in a PR review aren't seen by E13. A human resolves them, and may `resume` the job.
