# E05 · Gate engine design note

Spec: [E05 spec](../specs/E05-gate-engine.md) · Issue: [#5](https://github.com/michael-muir/software-factory/issues/5)
Status: **Accepted by the product owner, 17 Nov 2026** · ADRs: [0007](../adr/0007-gate-is-one-stdlib-file-in-the-kit.md) · [0008](../adr/0008-running-checks-safely-and-purely.md) · [0009](../adr/0009-dogfooding-the-kit-in-this-repo.md)

## Summary

The gate is one standard-library file, `kit/.factory/gates/gate.py`, which the installer copies into every repo. It runs in five steps:

1. **Settings:** read the `gates.*` settings from `.agentic/config.toml`.
2. **Profiles:** load and select the profiles.
3. **Changed files:** work them out, but only when a command asks for `{changed_files}`.
4. **Checks:** run each check as an argument list, never through a shell. A check is timed, has its output captured, and is bracketed by a purity snapshot.
5. **Report:** print the report as text or JSON, then exit 0, 1 or 2.

Validating config stays in `install.py check` (E01). The gate reads only what it needs and uses the same defaults.

## Source layout

```text
kit/.factory/gates/
├── gate.py              # the engine: one stdlib file, a CLI entry and small pure functions
└── profiles/.gitkeep    # real profiles arrive with E06 and E30
factory_installer/config_schema.py   # + gates.coverage_threshold, gates.profiles, gates.base_ref; list type
tests/
├── _gate.py             # fixture builder: a git repo with installed gate, fixture profiles, config
└── test_gate_*.py       # one file per slice, every test tagged @pytest.mark.ac("E05-AC-nn")
pyproject.toml           # mypy_path and pytest pythonpath include kit/.factory/gates, so tests `import gate`
.factory/, .agentic/     # this repo's own installed kit (ADR 0009)
```

## Inside `gate.py`

| Part | Responsibility | Pure? |
| --- | --- | --- |
| `Settings.load(root)` | reads `gates.*` keys; falls back to the defaults, which mirror `config_schema`; bad values exit 2 | reads one file |
| `load_profiles(dir)` | parses and validates every profile (E05 AC-04) | reads files |
| `select(profiles, settings, root)` | uses the config list, or detects by marker files (AC-05, AC-06) | yes |
| `expand(command, values)` | fills in the placeholders and splices `{changed_files}` (AC-12, AC-13) | yes |
| `changed_files(root, base_ref, globs, scope)` | runs `git merge-base`, `git diff`, `git ls-files` (AC-13, AC-15) | runs git |
| `run_check(...)` | `shutil.which`, then subprocess with a timeout; purity snapshot before and after (AC-08 to AC-11, AC-16) | runs the command |
| `Report` | text and JSON (AC-18, AC-19) | yes |
| `main(argv) -> int` | wires it together; exit codes (AC-03) | — |

**Two traceability fixes, the first a change to E01's checker:**
- E05's AC ids collide with E01's (`AC-01` and so on). Tests therefore tag them `E05-AC-nn`.
- The AC-23 traceability checker in `tests/_ac.py` learns to read every spec in `docs/specs/`. That is a support-module change, not a change to a locked test.

## Test seams

- **Fixture profiles are written per test,** with commands such as `[sys.executable, "-c", "import sys; sys.exit(1)"]`. Tests stay fast and work on every platform, and the profile format needs no special placeholder for the interpreter.
- **Fixture repos are real `git init` repos with one commit on `main`.** That lets the changed-files and purity tests use real git.
- **Pure functions** (`select`, `expand`, `Report`) are tested directly. `main(argv)` is tested end to end. One subprocess test runs `python -I -S gate.py` for AC-02.

## Vertical slices

| Task | Slice | ACs |
| --- | --- | --- |
| T1 | Config keys and list type in `install.py check`; AC traceability across both specs | AC-20, AC-23 (part) |
| T2 | Gate CLI, settings, profile load, validation and selection, report text and JSON, exit codes | AC-01 to AC-07, AC-18, AC-19 |
| T3 | Running checks: run-all, no shell, not found, timeout, purity, determinism | AC-08 to AC-11, AC-16, AC-17 |
| T4 | Thresholds, changed files, mutation skip, missing base ref | AC-12 to AC-15 |
| T5 | Ship in the kit, install the kit into this repo, quality bar | AC-21 to AC-23 |

## Risks

- **Windows program lookup.** A subprocess given an argument list does not apply `PATHEXT`, so `npm`, which is really `npm.cmd`, would look missing. The gate resolves every program with `shutil.which` first (ADR 0008).
- **Timeouts and child processes.** `subprocess.run(timeout=…)` kills only the direct child, so grandchildren can outlive a timeout. On POSIX the gate starts each check in its own process group and kills the group. On Windows it kills the process tree with `taskkill /T /F`.
- **Purity check cost.** Each check costs two `git status` calls plus a hash of the diff. That is fine for 7 checks per profile.
- **Kit copy drift.** This repo's installed `.factory/gates/gate.py` can fall behind `kit/`. The AC-22 test ("up to date") catches it (ADR 0009).
