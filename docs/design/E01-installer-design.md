# E01 · Installer design note

Spec: [E01 spec](../specs/E01-repo-skeleton-installer.md) · Issue: [#1](https://github.com/michael-muir/software-factory/issues/1)
Status: **Accepted by the product owner, 17 Nov 2026** · ADRs: [0001](../adr/0001-record-architecture-decisions.md) · [0002](../adr/0002-installer-runs-from-clone-stdlib-only.md) · [0003](../adr/0003-kit-files-vs-state-files.md) · [0004](../adr/0004-lf-line-endings-and-normalised-hashes.md) · [0005](../adr/0005-upgrade-decision-table.md)

## Summary

`install.py` is a thin shim at the repo root. It checks the Python version using syntax any Python can parse, then hands off to a small standard-library package, `factory_installer`. The installer works in three steps:

1. **Read**: collect the kit files, the target's current files and the existing manifest.
2. **Plan**: a pure function turns those inputs into a list of actions. It does no I/O, so most tests target it directly.
3. **Apply**: check every path first, then write, and write the manifest last.

A failed check writes nothing. A crash part-way through leaves the old manifest in place, so the next run re-plans from a known state.

## Source layout (this repo)

```text
software-factory/
├── install.py                 # shim: version check, then factory_installer.cli.main()
├── factory_installer/
│   ├── __init__.py
│   ├── cli.py                 # argparse: install [PATH] (default), check [PATH]; --dry-run --force --json
│   ├── kit.py                 # reads kit/ → {relpath: bytes}, kit version
│   ├── target.py              # git-root detection, reads target files, path containment
│   ├── plan.py                # PURE: (kit, target, manifest, force) → Plan
│   ├── apply.py               # executes a Plan; atomic writes, LF, UTF-8
│   ├── manifest.py            # load/save .factory/manifest.json
│   ├── config_schema.py       # schema + validate(); also renders the default config.toml
│   └── report.py              # counts + human text + JSON
├── kit/
│   ├── VERSION                # "0.1.0" — single source of the kit version
│   ├── .factory/              # kit-managed files (tracked in the manifest)
│   └── .agentic/              # state seeds (created only if missing)
├── tests/
│   ├── conftest.py            # tmp git repo + kit builder fixtures
│   └── test_*.py              # each test tagged @pytest.mark.ac("AC-nn")
├── pyproject.toml             # requires-python >=3.11; uv; ruff, mypy --strict, pytest config
├── .gitattributes             # * text=auto eol=lf
└── LICENSE                    # Apache-2.0
```

## Key flows

| Command | Flow |
| --- | --- |
| `python install.py [PATH]` | shim version check → find git root of PATH → read kit, target, manifest → plan → check paths → apply → write manifest → report |
| `--dry-run` | same flow up to plan, then report without applying |
| `--json` | report printed as JSON instead of text (same counts and file lists) |
| `python install.py check [PATH]` | `tomllib` load of `.agentic/config.toml` → `config_schema.validate` → errors with file, key, reason |

## Plan actions

| Action | When | Writes |
| --- | --- | --- |
| `create` | file absent, not in manifest | kit content |
| `skip` | file present, not in manifest, no `--force` | nothing |
| `overwrite` | file present, not in manifest, `--force` | kit content |
| `unchanged` | file matches the new kit content | nothing |
| `update` | file matches its manifest hash, and the kit changed it | new kit content |
| `keep` | file differs from its manifest hash (edited locally) | `<name>.factory-new` beside it |
| `remove` | dropped from the kit, file still matches its manifest hash | deletes the file |
| `keep-dropped` | dropped from the kit, file edited locally | nothing |
| `deleted-locally` | in the manifest but missing on disk | nothing; dropped from the manifest so it stays deleted |

State seeds under `.agentic/` only ever produce `create` or `skip`. They are never in the manifest (AC-08, AC-16).

## Test seams

- **`plan.py` is pure.** Its inputs are plain dicts of paths to hashes, so the upgrade decision table (AC-12 to AC-17) is tested exhaustively without touching disk.
- **The kit directory is injectable.** A fixture builds kit v1 and v2 in temporary directories, which lets the tests run real upgrades end to end.
- **`cli.main(argv) -> int`** returns the exit code, so CLI tests need no subprocess. Two subprocess tests remain:
  - AC-02 runs `python -I -S install.py` in a fresh venv to prove there are no third-party imports.
  - AC-03 tests the shim's version check with a patched `sys.version_info`.
- **AC traceability.** Every test carries `@pytest.mark.ac("AC-nn")`. A meta-test fails if any spec AC id has no test (AC-23).

## Vertical slices (task order)

| Task | Slice | ACs |
| --- | --- | --- |
| T1 | Bootstrap: `LICENSE`, `pyproject.toml`, `.gitattributes`, `kit/VERSION`, test scaffolding and the AC marker meta-test | AC-22, AC-23 |
| T2 | Config schema, default `config.toml` rendering, `check` command | AC-07, AC-18 |
| T3 | Fresh install end to end: shim, CLI, git detection, kit tree, create/skip, manifest, report, `--json`, `--dry-run`, containment, LF | AC-01 to AC-06, AC-08, AC-09, AC-11, AC-19 to AC-21 |
| T4 | `--force` | AC-10 |
| T5 | Re-runs and upgrades | AC-12 to AC-17 |

Each task goes through the factory loop: failing tests from the spec are written and locked first, then the implementation.

## Risks

- **autocrlf on Windows.** Git with `core.autocrlf=true` rewrites line endings on checkout. If hashes covered raw bytes, every file would look edited and upgrades would never update anything. Mitigated by ADR 0004.
- **Partial writes.** Mitigated by atomic per-file writes (write a temp file, then `os.replace`) and by writing the manifest last. A crash re-plans safely, because a half-applied file either matches the new kit (`unchanged`) or its old manifest hash (`update`).
