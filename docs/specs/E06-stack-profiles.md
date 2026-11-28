# E06 · Stack profiles: Python and TS/JS — Spec

Issue: [#6](https://github.com/michael-muir/software-factory/issues/6) · Milestone: M1 · Manual factory (alpha) · Depends on: E05 (done)
Status: **Approved by the product owner, 17 Nov 2026** · Next: Architect design note and ADRs, then failing tests per AC

## Goal

Give the E05 gate real work to do. Two profiles, Python and TS/JS, turn the gate's seven checks into concrete tool runs. Each profile is proven against a reference project that passes and seeded-bug projects that fail exactly one check. This repo becomes the first project the gate really checks.

## Decisions in force

| Topic | Decision |
| --- | --- |
| Python mutation tool | **cosmic-ray**, driven by a standard-library score helper. It works on native Windows, unlike mutmut. |
| Tool lookup | **Project environment.** Python tools are called by name, so run the gate inside the project's env (`uv run python .factory/gates/gate.py`). TS/JS uses `npx --no-install <tool>`, so local `node_modules` is used. |
| TS/JS tests | **Vitest**, with coverage thresholds as CLI flags and Stryker's Vitest runner for mutation |
| Reference projects | **Fixtures with real tools** under `tests/fixtures/`. The TS/JS fixture installs from a committed lockfile and is skipped only when Node isn't installed. |
| Pass/fail | Exit codes only (E05). Thresholds reach the tools through E05's placeholders. |

**Found while probing (17 Nov 2026):** if cosmic-ray's test command runs a bare `python`, it can pick a Python without pytest. Every mutant then "dies" from an import error, and the score reads 100%. The helpers therefore pin the interpreter that runs them.

## In scope

- `python.toml` and `ts-js.toml` profiles in the kit.
- Two mutation helpers in `.factory/gates/tools/`.
- Reference and seeded-bug fixtures, plus their tests.
- Dogfooding: this repo's gate runs the Python profile.

## Out of scope

- The other six profiles (E30).
- CI wiring (E07).
- Package managers other than npm (pnpm, yarn).
- Monorepos with several `package.json` or `pyproject.toml` files.

## The profiles

**`python.toml`**: detects `pyproject.toml`, `setup.py` or `setup.cfg`.

| Check | Command |
| --- | --- |
| format | `ruff format --check --extend-exclude ./.factory .` |
| lint | `ruff check --extend-exclude ./.factory .` |
| types | `mypy` (targets come from the project's mypy config) |
| build | — (n/a) |
| tests | `coverage run -m pytest` |
| coverage | `coverage report --fail-under={coverage_percent}` |
| mutation | `python .factory/gates/tools/mutate_python.py --min {mutation_percent} {changed_files}` (timeout 3600 s) |

**`ts-js.toml`**: detects `package.json`.

| Check | Command |
| --- | --- |
| format | `npx --no-install prettier --check .` |
| lint | `npx --no-install eslint .` |
| types | `npx --no-install tsc --noEmit` |
| build | `npm run build --if-present` |
| tests | `npx --no-install vitest run` |
| coverage | `npx --no-install vitest run --coverage --coverage.thresholds.lines={coverage_percent}` |
| mutation | `python .factory/gates/tools/mutate_ts.py --min {mutation_percent} {changed_files}` (timeout 1800 s) |

**Change, 17 Nov 2026 (found in T1):** ruff now runs with `--extend-exclude ./.factory`. Without it, a project's format and lint checks also judged the installed kit by the project's ruff settings. The reference fixture, with ruff's default 88-character lines, failed both checks on the kit's own files. `./.factory` excludes only the root kit, so this repo's kit source under `kit/.factory/` is still checked.

## Acceptance criteria

**Profiles**

- **AC-01** `kit/.factory/gates/profiles/python.toml` defines exactly the commands, detection markers and timeout in the table above. `mutation_paths` is `["*.py"]`.
- **AC-02** `kit/.factory/gates/profiles/ts-js.toml` defines exactly the commands, detection markers and timeout in the table above. `mutation_paths` covers `*.ts`, `*.tsx`, `*.js`, `*.jsx`, `*.mjs` and `*.cjs`.
- **AC-03** Both profiles load without errors in the E05 gate. The installer ships them as kit files, tracked in the manifest.
- **AC-04** Each profile starts with a comment block naming:
  - the tools it needs
  - the cache and report files the project must git-ignore, because of the purity check
  - how to run the gate inside the project's environment

**Mutation helpers**

- **AC-05** `mutate_python.py --min N FILE...` uses only the standard library and runs cosmic-ray:
  - It runs with the interpreter executing the helper, and its test command is `<that interpreter> -m pytest -q -x`.
  - It mutates only the given files that are not tests, excluding `test_*.py`, `*_test.py`, `conftest.py` and anything under a `tests/` or `test/` directory.
  - It never mutates the installed kit under `.factory/`, which is factory machinery, not project code. *(Clarified 17 Nov 2026: with `mutation_scope = "all"`, the fixture runs mutation-tested `.factory/gates/gate.py` and ran for over 10 minutes.)*
  - It exits 0 when the share of mutants killed is at least N%, and 1 when it's below.
- **AC-05b** *(Change, 17 Nov 2026: a design measurement found `gate.py` has 565 mutants, about 1 to 4 hours of serial runs.)* Two settings keep the Python helper inside its timeout. Both live under `[tool.software-factory.mutation]` in the project's `pyproject.toml`:
  - **`max-mutants`** (default 100): at most this many mutants are tested per run. The sample is deterministic: the same set of file contents always selects the same mutants. The score is the kill rate of the sample, and the output says "sampled X of Y".
  - **`test-args`** (default `[]`): extra pytest arguments for the kill test, so a project can narrow it to fast tests. The command becomes `<interpreter> -m pytest -q -x <test-args>`.
- **AC-05c** *(Change, 19 Nov 2026, code review, approved by the product owner: mutation is the slowest check and the Line Monitor's top gate failure, and `mutation_scope = "changed-lines"` had meant changed files.)* With `gates.mutation_scope = "changed-lines"` (the default), both helpers mutate only the lines changed since the merge base of `gates.base_ref` (or `--base-ref`) and HEAD, uncommitted changes included.
  - **What counts:** added and modified lines. New untracked files count in full. Deleted lines produce no mutants. With `"all"`, whole files are mutated, as before.
  - **How the helpers learn the scope:** the gate gains two placeholders, `{mutation_scope}` and `{base_ref}` (E05). The shipped profiles pass `--scope {mutation_scope} --base-ref {base_ref}`, so CI's `--base-ref` reaches the helpers. A helper run without `--scope`, from an older profile, mutates whole files.
  - **Python:** after `cosmic-ray init`, mutants whose start line is outside the changed lines are dropped before sampling, so `max-mutants` samples only mutants on changed lines.
  - **TS/JS:** Stryker's `mutate` list gives each changed range as `file:start-end`.
  - **Output:** each helper says how many mutants are on changed lines, for example "testing 12 mutants on changed lines (of 418 in 3 files)".
  - **No mutants on changed lines** (for example, only comments or deletions changed) means nothing to mutate: exit 0.
- **AC-06** `mutate_ts.py --min N FILE...` uses only the standard library and runs `npx --no-install stryker run` with the Vitest runner:
  - It mutates only the given files that are not tests, excluding `*.test.*`, `*.spec.*` and anything under `__tests__/`.
  - It never mutates the installed kit under `.factory/`, or tool configuration files named `*.config.*` (`eslint.config.js`, `vitest.config.ts` and so on). *(Clarified 17 Nov 2026, product owner decision during T2: config files pulled the reference fixture's score down to 47%.)*
  - It reads the mutation score from Stryker's JSON report and exits 0 at or above N%, 1 below.
- **AC-07** Both helpers:
  - exit 0 with the message "no source files to mutate" when every given file is a test
  - exit 2, with a message naming what's missing, when the mutation tool or test runner isn't installed
- **AC-08** Both helpers write their config, session and report files to a temporary directory outside the repo and delete it afterwards. A helper run leaves the repo unchanged, so the gate's purity check passes.

**Reference projects**

- **AC-09** `tests/fixtures/python-ref/` is a small package with tests. Copied into a fresh git repo with `mutation_scope = "all"`, it passes every Python check at the default thresholds, and the gate exits 0.
- **AC-10** Each defined Python check has a seeded-bug variant that breaks that check and nothing else:
  - an unformatted file (format)
  - an unused import (lint)
  - a type error (types)
  - a failing test (tests)
  - an untested function that pulls coverage under 80% (coverage)
  - weak assertions that pull the mutation score under 60% (mutation)

  For each variant, the gate exits 1, that check fails, and every other check passes or is n/a, with one exception: the **tests** variant also fails mutation, because the kill test fails before any mutation, so no mutant can be scored. *(Changes, 28 Nov 2026; see Changes.)*
- **AC-11** `tests/fixtures/ts-js-ref/` is a small Vitest project with a committed `package-lock.json`. Installed with `npm ci`, it passes every TS/JS check, and the gate exits 0.
- **AC-12** Each TS/JS check has a seeded-bug variant: format, lint, types, build, tests, coverage and mutation. Every variant breaks its own check and nothing else, with two exceptions:
  - The **tests** variant also fails coverage and mutation, because both need a green test suite: the coverage check reruns the tests, and Stryker refuses to start when its initial test run fails.
  - The **types** variant also fails build, because the build compiles with `tsc`, which type-checks.

  *(Changes, 17 Nov 2026, product owner decisions during T2.)*
- **AC-13** The TS/JS fixture tests are skipped, with a stated reason, only when `node` or `npm` is not on PATH. When Node is present, a failed `npm ci` is a test failure, not a skip.

**Dogfooding**

- **AC-14** This repo adds `cosmic-ray` to its dev dependencies, and git-ignores every file its Python checks write. On a clean `main`, `uv run python .factory/gates/gate.py` exits 0. Mutation is skipped there because no files changed.

**Quality**

- **AC-15** ruff, `ruff format --check` and `mypy --strict` pass on both helpers. Every AC above has at least one test tagged `E06-AC-nn`.

## Changes

- **28 Nov 2026, by the product owner, after the live run (#120; AC-10):** `mutate_python.py` runs the kill test once on its copy before mutating. When it failed in the copy and in the project, the helper exited 0 and left the failure to the `tests` check. In the live run on #82, on the product owner's Windows machine, the `tests` check passed but the kill test failed, so mutation passed with no mutant scored, and the helper threw away pytest's output, so nobody could tell which test failed. Now a kill test that fails before any mutation is a mutation failure: the helper exits 1, whatever the `tests` check says, and prints the last 30 lines of pytest's output, its short test summary included, so the failing test is named. A kill test that passes in the project but fails in the copy is still an environment error (exit 2). So AC-10's **tests** variant fails mutation too. PO-approved under the standing approval of 26 Nov 2026. Built in E13-T11.

## Assumptions (confirmed with approval, 17 Nov 2026)

1. **mypy runs without arguments (AC-01).** Projects declare their targets in their mypy config, as this repo does. A project without that config fails the types check, and the error says why.
2. **TS/JS runs its tests twice (AC-02):** once for tests and once with coverage, so the two checks report separately. Coverage enforces the lines threshold only.
3. **Test files are excluded from mutation by naming convention (AC-05, AC-06),** not by configuration.
4. **The mutation timeout is 1800 s** in both profiles. Every other check keeps E05's 600 s default. *(Change, 18 Nov 2026, E07/T4: the Python profile's tests timeout is 1200 s, because this repo's suite timed out at 600 s on a 4-core Windows CI runner, about 82% through. Product owner decision.)* *(Change, 23 Nov 2026: the Python profile's tests timeout is 2400 s, because Windows CI's tests step reached about 1,100 s of 1,200 s (#89), and #93 timed out once when a pytest-xdist worker crashed near the end. Product owner decision.)* *(Change, 20 Nov 2026: the Python profile's mutation timeout is 3600 s, because Windows CI timed out at 1800 s on PRs #70 and #71, which touch large kit files, with no failing mutant or test. Product owner decision.)*
5. **The kill test is pytest with `-x`** (stop at the first failure), which is the fastest way to decide a mutant is killed.
6. **The TS/JS fixture installs from the network** with `npm ci`. Tests share one install per test session, in a cache directory outside the repo.
7. **The dogfood gate run (AC-14) is checked by running it, not by a pytest test.** The gate's tests check runs pytest, so a test that ran the gate would run itself. Evidence goes in the PR now, and in CI from E07.
8. **Profiles don't pin tool versions.** The fixtures' lockfile and this repo's `uv.lock` do.

## Notes for the Architect (design, not requirements)

- How the seeded-bug variants are built: one reference fixture plus a small patch per check, so each variant differs by exactly one change.
- How to keep the TS/JS fixture install fast and shared across tests, and where its cache lives.
- How Stryker's JSON report location and its temp directory are redirected out of the repo.
- cosmic-ray's per-mutant cost: whether `-x` plus a narrowed test selection is enough to keep this repo's own mutation check inside 1800 s.
