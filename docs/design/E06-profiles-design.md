# E06 · Stack profiles design note

Spec: [E06 spec](../specs/E06-stack-profiles.md) · Issue: [#6](https://github.com/michael-muir/software-factory/issues/6)
Status: **Accepted by the product owner, 17 Nov 2026** · ADRs: [0010](../adr/0010-mutation-helpers.md) · [0011](../adr/0011-profile-fixtures.md)

## Summary

Two TOML profiles and two standard-library helpers, all in the kit:

- `.factory/gates/profiles/python.toml` and `.factory/gates/profiles/ts-js.toml`
- `.factory/gates/tools/mutate_python.py` and `.factory/gates/tools/mutate_ts.py`

Each profile calls tools by name, from the project's own environment. Mutation goes through a helper that turns a mutation tool's result into exit 0 or 1 against `{mutation_percent}`. Real tools prove both profiles: each runs on a reference fixture that must pass, and on seeded-bug variants that must each fail exactly one check.

## Measured cost (17 Nov 2026)

| Module | Mutants | Narrowest sensible kill test |
| --- | --- | --- |
| `kit/.factory/gates/gate.py` | 565 | gate tests: 27.4 s |
| `factory_installer/config_schema.py` | 353 | `test_config.py`: 4.0 s |
| `factory_installer/plan.py` | 210 | installer tests: 9.4 s |
| `factory_installer/cli.py` | 135 | installer tests: 9.4 s |

The full suite takes 34.6 s. Testing every mutant one at a time would take hours, which led to spec AC-05b: a deterministic sample cap plus a project-narrowed kill test.

## Source layout

```text
kit/.factory/gates/
├── profiles/python.toml, profiles/ts-js.toml
└── tools/mutate_python.py, tools/mutate_ts.py     # stdlib only, pinned interpreter
tests/
├── fixtures/python-ref/      # tiny package + tests: passes every Python check
├── fixtures/ts-js-ref/       # tiny Vitest project + package-lock.json: passes every TS/JS check
├── _profile_fixtures.py      # copies a reference into a fresh git repo, applies one seed, runs the gate
├── test_profile_python.py    # reference + 6 seeds + helper behaviour
└── test_profile_ts_js.py     # reference + 7 seeds + helper behaviour (skipped without node)
```

## Seeded-bug variants

A **seed** is a small dict of `{path: new content}` applied over a copy of the reference project, in `_profile_fixtures.py`. Each seed changes the minimum needed to break one check:

| Check | Python seed | TS/JS seed |
| --- | --- | --- |
| format | `calc.py` with bad spacing | `src/calc.ts` with bad spacing |
| lint | an unused `import os` | an unused variable |
| types | `add("1", 2)` in typed code | `const n: number = "x"` |
| build | — | a `build` script that exits 1 |
| tests | an assertion that's wrong | an assertion that's wrong |
| coverage | a new untested function, enough to drop under 80% | the same |
| mutation | assertions weakened to `assert add(2, 3)` | `expect(add(2, 3)).toBeTruthy()` |

The tests assert two things for every seed: its check fails, and every other check passes or is n/a. So a seed that accidentally breaks two checks fails the test.

## Test seams and speed

- **The Python fixture runs with this repo's interpreter.** ruff, mypy, pytest, coverage and cosmic-ray are dev dependencies here. Each test copies the fixture into `tmp_path`, runs `git init`, and runs the gate with `PATH` pointing at this venv's scripts.
- **The TS/JS fixture runs `npm ci` once per lockfile hash,** into a cache under the user's cache directory, outside the repo. Each test links `node_modules` into its copy: a symlink, or a junction on Windows. The fixture's `.gitignore` ignores `node_modules/`.
- **Mutation inside fixtures is kept small:** the reference has about 10 to 20 mutants, and `max-mutants` doesn't kick in.
- **Helper unit tests** check sampling determinism, file exclusion, exit codes and temp-dir cleanup without running a full mutation, by putting a fake `cosmic-ray` and fake `npx` on `PATH`.

**Slow marker (added 17 Nov 2026, after T1):** tests that run real tools through the gate, or a real mutation run, are tagged `@pytest.mark.slow`.
- **While working locally:** run `uv run pytest -m "not slow"`. After T1 that was 170 tests in about 28 s.
- **Before a PR, and in CI (E07):** run everything.

## Vertical slices

| Task | Slice | ACs |
| --- | --- | --- |
| T1 | Python profile and helper (sampling, narrowing), Python reference and 6 seeds | AC-01, AC-03 (Python), AC-04 (Python), AC-05, AC-05b, AC-07 (Python), AC-08 (Python), AC-09, AC-10 |
| T2 | TS/JS profile and helper, TS/JS reference with lockfile and 7 seeds | AC-02, AC-03 (TS/JS), AC-04 (TS/JS), AC-06, AC-07 (TS/JS), AC-08 (TS/JS), AC-11 to AC-13 |
| T3 | Dogfooding: cosmic-ray dev dependency, this repo's mutation settings, `.gitignore`, a real gate run; enforce E06 coverage | AC-14, AC-15 |

## Risks

- **cosmic-ray internals.** Sampling deletes rows from cosmic-ray's session database before `exec`, which couples the helper to that schema. A cosmic-ray upgrade could break it, and the helper tests would catch that. `uv.lock` pins the version used here.
- **Stryker's sandbox.** Stryker copies the project into `.stryker-tmp/` inside the repo while it runs, and deletes it afterwards. The TS/JS profile documents that this must be git-ignored. The purity check then sees no change.
- **Network for `npm ci`.** The first run on a machine downloads Vitest, ESLint, Prettier, TypeScript and Stryker, roughly 150 MB. Later runs use the cache.
- **This repo's own mutation budget.** With `max-mutants = 50`, a `gate.py` change costs about 50 mutants × 5–35 s, roughly 5 to 25 minutes. That fits in 1800 s, but it's slow for a local gate. T3 records the real timing.

## Dogfooding results (T3, 18 Nov 2026)

**This repo's settings** (`pyproject.toml`):

```toml
[tool.software-factory.mutation]
max-mutants = 50
test-args = ["-m", "not slow"]
```

**Parallel tests (product owner decision during T3):**
- **Why:** on a clean `main`, the gate passed, but its tests check took 573 s against E05's 600 s default.
- **What changed:** this repo now runs pytest with pytest-xdist (`-n auto`), and coverage measures the workers with `patch = ["subprocess"]`. `coverage report` combines the workers' data files on its own.
- **Stale data:** that combine also picks up data files left over from earlier runs, which silently raised coverage in a probe from 62% to 75%. So `tests/conftest.py` deletes old `.coverage` files when a coverage run starts, before any worker spawns.
- **Shared npm cache:** the TS/JS `npm ci` cache now installs into a staging directory and renames it into place, so parallel workers can't race on a cold cache.

| Run | Result | Time |
| --- | --- | --- |
| Gate on clean `main`, serial tests | exit 0, mutation skipped (no changed files) | 9 min 34 s (tests 573 s) |
| Gate on the T3 branch, parallel tests | exit 0, mutation: no source files to mutate | 3 min 35 s (tests 213 s) |
| `mutate_python.py` on `factory_installer/report.py` | 25 of 36 killed = 69.4% | 8 min 20 s, about 14 s per mutant |

So a change to a source file costs about 12 minutes of mutation at the 50-mutant cap. That's inside the 1800 s timeout, but still slow for a local loop.

**Kit follow-up:** any Python project that combines the profile with pytest-xdist meets the same stale-data trap, because the coverage check is `coverage report` with no `coverage erase` beforehand. This is worth fixing in the kit later.
