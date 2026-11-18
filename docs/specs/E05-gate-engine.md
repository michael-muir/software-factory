# E05 · Gate engine core — Spec

Issue: [#5](https://github.com/michael-muir/software-factory/issues/5) · Milestone: M1 · Manual factory (alpha) · Depends on: E01 (done)
Status: **Approved by the product owner, 17 Nov 2026** · Next: Architect design note and ADRs, then failing tests per AC

## Goal

One deterministic command decides whether a change is good enough to merge: format, lint, types, build, tests, coverage and mutation. The verdict is pass or fail, never an opinion. Every later epic relies on it: hooks and CI (E07), PR evidence (E08), the Verifier role and the whole worker pipeline.

## Decisions in force

| Topic | Decision |
| --- | --- |
| Pass/fail | Exit code only. A check passes when its command exits 0. Thresholds reach the tools through their own flags. |
| On failure | Run every check and report every result. |
| Profile selection | `gates.profiles` in `config.toml` when set; otherwise auto-detect from marker files |
| Mutation scope | The gate computes the changed files and passes them to the profile's mutation command |
| Location | Stdlib-only `.factory/gates/gate.py`, shipped in the kit and installed into every repo |
| Dogfooding | This repo installs its own kit |
| Coverage default | 80%, configurable as `gates.coverage_threshold` |
| Mutation default | 60% on changed files (E01 decision) |
| Report | Text on stdout; JSON with `--json`; nothing written to the repo |
| Runtime | Python 3.11+, standard library only (as E01) |

## In scope

- `gate.py`, the profile file format and loader, profile selection, running the checks, changed-file detection, and the report.
- Three new `config.toml` keys, and their validation in `install.py check`.
- Shipping the gate in the kit, and installing the kit into this repo.

## Out of scope

- Real stack profiles: Python and TS/JS are E06, the other six are E30. E05 is tested with fixture profiles.
- Git hooks and CI workflows (E07). The PR evidence format (E08).
- Parsing coverage or mutation reports. Exit codes only.

## Profile format

A profile is `.factory/gates/profiles/<name>.toml`:

```toml
name = "python"
detect = ["pyproject.toml"]            # marker files at the repo root
mutation_paths = ["*.py"]              # globs that select which changed files go to mutation

[checks.format]
command = ["ruff", "format", "--check", "."]

[checks.coverage]
command = ["coverage", "report", "--fail-under={coverage_percent}"]
timeout_s = 900                        # optional; default 600

[checks.mutation]
command = ["mutmut", "run", "--paths-to-mutate", "{changed_files}"]
```

Valid check names: `format`, `lint`, `types`, `build`, `tests`, `coverage`, `mutation`.

**Placeholders** in command arguments:

| Placeholder | Replaced with |
| --- | --- |
| `{coverage_percent}` | `gates.coverage_threshold` as a whole percent, for example `80` |
| `{mutation_percent}` | `gates.mutation_threshold` as a whole percent, for example `60` |
| `{changed_files}` | One argument per file. Allowed only as a whole argument. |

## New `config.toml` keys

| Key | Type | Default | Rule |
| --- | --- | --- | --- |
| `gates.coverage_threshold` | number | 0.8 | 0 to 1 |
| `gates.profiles` | list of strings | `[]` | an empty list means auto-detect |
| `gates.base_ref` | string | `"main"` | not empty |

Existing configs without these keys stay valid; the defaults apply (E01 assumption 3).

## Acceptance criteria

**Running the gate**

- **AC-01** `python .factory/gates/gate.py`, run anywhere inside a repo, gates that repo's git root.
- **AC-02** The gate runs under `python -I -S` and imports only the standard library.
- **AC-03** Exit code 0 means every check passed. 1 means at least one check failed. 2 means a usage, config or profile error stopped the gate before it ran any check.

**Profiles**

- **AC-04** Profiles load from `.factory/gates/profiles/*.toml`. A malformed profile exits 2 and names the file and the problem. Malformed means:
  - invalid TOML
  - a missing `name`
  - an unknown check name
  - a `command` that is not a non-empty list of strings
  - `{changed_files}` used inside a larger argument
- **AC-05** When `gates.profiles` is non-empty, exactly those profiles run. Otherwise every profile whose `detect` marker exists at the repo root runs.
- **AC-06** A profile named in config that does not exist exits 2 and lists the available profiles. If no profile applies, the gate exits 2 with the same list.

**Running checks**

- **AC-07** For each selected profile, checks run in this fixed order: format, lint, types, build, tests, coverage, mutation. A check the profile does not define is reported as not applicable and does not fail the gate.
- **AC-08** A check passes when its command exits 0; any other exit fails it. Every check runs, even after an earlier one fails.
- **AC-09** Commands run from the repo root as argument lists, never through a shell.
- **AC-10** If a command's program is not found, that check fails with "command not found: \<program\>". The gate goes on to the next check.
- **AC-11** A check that runs longer than its timeout is stopped and fails with "timed out after \<n\>s". The timeout is `timeout_s`, or 600 by default.

**Thresholds and changed files**

- **AC-12** `{coverage_percent}` and `{mutation_percent}` are replaced with the configured thresholds as whole percents.
- **AC-13** Changed files are the union of three sets, minus deleted files, then filtered by the profile's `mutation_paths` globs:
  - files changed between `git merge-base <gates.base_ref> HEAD` and the working tree
  - staged changes
  - untracked files that are not ignored

  `{changed_files}` expands to these as repo-relative posix paths, one argument each, sorted. When `gates.mutation_scope = "all"`, it expands to every tracked file matching `mutation_paths` instead.
- **AC-14** If `{changed_files}` would be empty, the mutation check is reported as "skipped: no changed files" and does not fail the gate.
- **AC-15** If `gates.base_ref` does not exist, any check that uses `{changed_files}` fails and names the missing ref. The other checks still run.

**Determinism**

- **AC-16** The gate never changes the repo. If `git status --porcelain --untracked-files=all` differs after a check from before it, that check fails with "modified the repository" and the report lists the changed paths.
- **AC-17** Running the gate twice on the same repo state gives the same verdict and the same status for every check.

**Report**

- **AC-18** The text report has one line per check: profile, check, status (pass, fail, skipped or n/a) and duration. Each failed check also shows its reason and the last 40 lines of its combined output. The report ends with `PASS` or `FAIL`.
- **AC-19** `--json` prints one JSON object with:
  - `verdict`, `base_ref`, `profiles` and `changed_files`
  - `checks`: a list with `profile`, `check`, `status`, `reason`, `exit_code`, `duration_s`, `command` and `output_tail` for each check

**Config**

- **AC-20** `install.py check` validates the three new keys by the rules in the table above, including a new list-of-strings type.

**Kit and dogfooding**

- **AC-21** `gate.py` and an empty `profiles/` directory ship in the kit under `.factory/gates/`. The installer installs and upgrades them like any kit file.
- **AC-22** This repo has its own kit installed by its own installer, and `python install.py` on this repo reports up to date.

**Quality**

- **AC-23** ruff, `ruff format --check` and `mypy --strict` pass on the gate code. Every AC above has at least one test that names its id.

## Assumptions (confirmed with approval, 17 Nov 2026)

1. **Repo root (AC-01).** The gate always gates the git root of the current directory. There is no PATH argument in v1.
2. **Check order (AC-07)** is fixed and cannot be configured.
3. **Base ref (AC-13).** The default is `main`. CI on `main` itself therefore usually sees no changed files, and mutation is skipped there.
4. **Timeout (AC-11).** The default is 600 seconds per check.
5. **Output tail (AC-18).** The report shows the last 40 lines of a failed check's output.
6. **No real profiles in E05.** The first real gate run on this repo comes with E06's Python profile.
7. **Purity check (AC-16).** A formatter that rewrites files instead of only checking them makes its check fail. Profiles must use check-only modes.

## Notes for the Architect (design, not requirements)

- How tests load `gate.py` from the kit path, and whether it stays one file or splits within `.factory/gates/`.
- How the purity check compares `git status` cheaply between checks.
- How fixture profiles call tiny stand-in programs, such as `python -c ...`, so the tests run fast and on every platform.
