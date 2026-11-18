# 0009 · Dogfooding: this repo installs its own kit

Status: Accepted · Date: 2026-11-17 · Epic: E05

## Context

The product owner chose to have this repo install its own kit, so the factory is built under its own gate. That means this repo holds the kit twice: the source in `kit/`, and the installed copy at the repo root in `.factory/` and `.agentic/`.

## Decision

- **Source and installed copy.** `kit/` is the only source of kit files. The root `.factory/` is installer output and is committed. Nobody edits it by hand.
- **Updating the copy.** After changing anything in `kit/`, run `python install.py`. It updates the root copy through the normal upgrade path, including the manifest.
- **Catching drift.** A test runs `python install.py --dry-run --json` on this repo and asserts `up_to_date`. Forgetting the step fails the test suite, and later the gate (spec AC-22).
- **State files.** The root `.agentic/` is this project's real state: its config, and from E02 its `STATE.md`, task files and handoffs. Upgrades never rewrite it (ADR 0003).
- **Tooling scope.** ruff checks both copies, which are identical. mypy checks only the `kit/` copy, to avoid duplicate-module errors. pytest only collects `tests/`.

## Consequences

- Every kit change is exercised by a real upgrade of a real repo before it ships.
- A PR that changes `kit/` also shows the matching diff in `.factory/`. Reviewers can ignore that second diff; the drift test vouches for it.
