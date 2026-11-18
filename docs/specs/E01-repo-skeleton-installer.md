# E01 · Repo skeleton and installer v0 — Spec

Issue: [#1](https://github.com/michael-muir/software-factory/issues/1) · Milestone: M1 · Manual factory (alpha) · Depends on: none
Status: **Approved by the product owner, 17 Nov 2026** · Next: Architect design note and ADRs, then failing tests per AC

## Goal

One command installs the Software Factory kit into any git repository, new or existing, and can later bring an older install up to date without touching the user's own edits. Every later epic writes into the layout this epic creates.

## Decisions in force

| Topic | Decision |
| --- | --- |
| Command | `python install.py [TARGET]`, run from a clone or download of this repo; no PyPI package in v0 |
| Runtime | Python 3.11+, standard library only |
| Layout in target repo | Kit files under `.factory/`; project state under `.agentic/`; nothing else at the repo root |
| Conflicts | Never overwrite an existing file; skip and report; `--force` overwrites explicitly |
| Upgrades | In scope: re-running updates untouched kit files and keeps locally edited ones |
| This repo's own tooling | uv, ruff (format + lint), mypy --strict, pytest, coverage.py; license Apache-2.0 |

## In scope

- `install.py` and the kit content it copies (structure and placeholders only).
- The `.factory/` and `.agentic/` layouts.
- The `config.toml` schema with v1 defaults and a validator.
- A manifest that records what was installed, for idempotence and upgrades.
- This repo's bootstrap: `LICENSE`, `pyproject.toml`, ruff/mypy/pytest configuration.

## Out of scope

- Real content of roles, skills, standards and gate profiles (E06, E09–E11).
- The gate engine (E05), hooks and CI (E07), tool adapters (E12).
- Content of the state files beyond placeholders (E02).
- A PyPI package or any network access.

## Target layout (after a fresh install)

```text
<repo>/
├── .factory/
│   ├── manifest.json        # kit version + SHA-256 per installed kit file
│   ├── agents/              # E03, E09
│   ├── skills/              # E10
│   ├── standards/           # E11
│   ├── gates/               # E05–E07
│   ├── workflow/            # E04, E13, E15
│   └── adapters/            # E12
└── .agentic/
    ├── config.toml          # schema below
    ├── STATE.md             # placeholder; E02 defines content
    ├── tasks/
    └── handoffs/
```

Empty directories carry a `.gitkeep` so the layout survives a commit.

## `config.toml` v1 defaults

```toml
schema_version = 1

[hosting]
mode = "local"                  # "local" | "cloud"

[budgets]
per_job_usd = 15
per_day_usd = 120
warn_at = 0.8                   # fraction of budget
halt_at = 1.0

[review]
max_rounds = 3

[gates]
mutation_threshold = 0.6
mutation_scope = "changed-lines"

[models]
cross_model_vendor = "openai"

[telemetry]
enabled = false
```

### Validation rules (confirmed 17 Nov 2026, during T2)

| Key | Type | Rule |
| --- | --- | --- |
| `schema_version` | integer | must be 1 |
| `hosting.mode` | string | `local` or `cloud` |
| `budgets.per_job_usd` | number | > 0, and ≤ `per_day_usd` |
| `budgets.per_day_usd` | number | > 0 |
| `budgets.warn_at` | number | > 0, and ≤ `halt_at` |
| `budgets.halt_at` | number | ≤ 1 |
| `review.max_rounds` | integer | 1 to 10 |
| `gates.mutation_threshold` | number | 0 to 1 |
| `gates.mutation_scope` | string | `changed-lines` or `all` |
| `models.cross_model_vendor` | string | not empty |
| `telemetry.enabled` | boolean | — |

- A number is an integer or a float, but never a boolean.
- A key that is missing is allowed: its default applies, and `check` lists it as information while still exiting 0 (assumption 3).
- An unknown key or unknown section is an error.
- **Change, 17 Nov 2026:** `factory.kit_version` was removed from the config. Upgrades never rewrite `config.toml` (ADR 0003), so the value would go stale. The installed kit version lives only in `.factory/manifest.json`. A `[factory]` section is now an unknown section.

## Acceptance criteria

**Running the installer**

- **AC-01** `python install.py` with no argument installs into the current directory, and `python install.py PATH` installs into PATH. On success it exits 0.
- **AC-02** The installer and its tests run in a fresh virtual environment with no third-party packages installed.
- **AC-03** On Python older than 3.11 it exits non-zero, names the required version, and writes nothing.
- **AC-04** If the target is not inside a git working tree, it exits non-zero with a message saying so, and writes nothing.
- **AC-05** `--dry-run` prints every file it would create, skip, overwrite, update or keep, and writes nothing.

**Fresh install**

- **AC-06** In an empty git repo, it creates exactly the layout above, including `.gitkeep` files, and nothing outside `.factory/` and `.agentic/`.
- **AC-07** The written `config.toml` parses with `tomllib` and passes the validator (AC-15).
- **AC-08** `.factory/manifest.json` records the kit version and a SHA-256 hash for every kit file written. State files under `.agentic/` are not in the manifest.

**Existing repo and conflicts**

- **AC-09** If a file it would write already exists, the installer leaves it byte-for-byte unchanged and lists it as skipped. The run still exits 0.
- **AC-10** With `--force`, conflicting kit files under `.factory/` are overwritten and listed as overwritten. State files under `.agentic/` are never overwritten, even with `--force`; they stay skipped (ADR 0003; product owner decision, 17 Nov 2026).
- **AC-11** The final summary reports counts for created, skipped, overwritten, updated, kept and removed files.

**Re-runs and upgrades**

- **AC-12** Running the same kit version twice changes no files. The second run reports "up to date", and `git status` is clean afterwards.
- **AC-13** Running a newer kit version replaces each kit file whose current hash still matches the manifest, and reports it as updated.
- **AC-14** A kit file whose hash differs from the manifest (edited locally) is left unchanged and reported as "kept (modified locally)". The new version is written beside it as `<name>.factory-new` so the user can merge it.
- **AC-15** A kit file dropped from the newer kit is deleted if untouched, or kept and reported if modified.
- **AC-16** An upgrade never rewrites existing files in `.agentic/`. New state files are created only where they are missing.
- **AC-17** After an upgrade, the manifest holds the new kit version and the hashes of the files as they now stand.

**Config validation**

- **AC-18** `python install.py check [PATH]` validates `.agentic/config.toml`. An unknown key, a wrong type or an out-of-range value (for example `warn_at > halt_at`, or a negative budget) gives exit 1 and names the file, the key and the reason. A valid file gives exit 0.

**Safety and portability**

- **AC-19** The installer never writes outside the target directory. A path that resolves outside it, for example through a symlink, aborts the run before anything is written.
- **AC-20** Files are written UTF-8 with LF line endings. The test suite passes on Windows and Linux.
- **AC-21** `--json` prints the same report as AC-11 as machine-readable JSON, so later epics can attach it as evidence.

**This repo's bootstrap**

- **AC-22** This repo has `LICENSE` (Apache-2.0) and a `pyproject.toml` with `requires-python = ">=3.11"`, managed by uv.
- **AC-23** `ruff format --check`, `ruff check` and `mypy --strict` pass on the installer code. `pytest` passes, with every AC above covered by at least one test that names its AC id.

## Assumptions (confirmed with approval, 17 Nov 2026)

1. **Git required (AC-04).** Installing into a folder that isn't a git repo is refused.
2. **Upgrade conflicts (AC-14).** A locally edited kit file gets a `.factory-new` copy beside it rather than a merge.
3. **Config on upgrade (AC-16).** `config.toml` is never rewritten on upgrade. New keys added in later kit versions fall back to their defaults when read.
4. **Versioning.** The kit uses semver and starts at `0.1.0`.
5. **Spec location.** Specs live in `docs/specs/` in this repo, until E04 defines the template and its home.

## Notes for the Architect (design, not requirements)

- Where the kit's source files sit in this repo (for example `kit/.factory/` and `kit/.agentic/`), and whether `install.py` is one file or a small stdlib package.
- How the validator describes the schema without third-party libraries.
- How to test the upgrade path by building two kit versions inside the tests.
