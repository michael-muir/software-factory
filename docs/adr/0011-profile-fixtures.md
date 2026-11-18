# 0011 · Profiles are proven by a reference fixture plus one-change seeds, run with real tools

Status: Accepted · Date: 2026-11-17 · Epic: E06

## Context

The PRD defines E06 as done when each profile passes a reference repo and fails a seeded-bug repo. The product owner chose fixtures that run real tools. Real tools are slow, though, and the TS/JS toolchain needs about 150 MB of npm packages.

## Decision

- **One reference project per stack** lives in `tests/fixtures/<stack>-ref/`. Tests copy it into `tmp_path`, initialise git with one commit on `main`, and set `mutation_scope = "all"` so mutation actually runs.
- **Seeds are data.** Each seed is a `{path: content}` overlay in `tests/_profile_fixtures.py` that breaks one check, so a reviewer reads the whole bug in a few lines.
- **Strict assertions.** For each seed, the targeted check fails, and every other check passes or is n/a.
- **Python tools come from this repo's dev environment.** The tests put the venv's scripts directory first on `PATH` for the gate subprocess, so the profile's bare tool names resolve to it, as they would for a user running under `uv run`.
- **One npm install per lockfile hash.**
  - The TS/JS reference commits its `package-lock.json`.
  - A session fixture runs `npm ci` into `<user cache>/software-factory/ts-js-ref-<lockfile sha256[:12]>/` once, and reuses it while the hash matches.
  - Each test links `node_modules` into its copy: a symlink, falling back to a Windows junction, and to a copy as a last resort.
- **Skips:** TS/JS tests skip with a reason only when `node` or `npm` is missing from `PATH`. An install failure is a test error.

## Consequences

- Every profile command is exercised by the real tool on every test run. A tool upgrade that changes behaviour shows up as a failing seed.
- The first TS/JS run on a machine needs network access and about a minute to install. Later runs reuse the cache.
- The fixture cache lives outside the repo, so it never affects the purity check or `git status`.
