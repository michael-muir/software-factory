# E02 · State files design note

Spec: [E02 spec](../specs/E02-state-files.md) · Issue: [#2](https://github.com/michael-muir/software-factory/issues/2)
Status: **Accepted by the product owner, 18 Nov 2026** · ADRs: [0014](../adr/0014-state-files-toml-front-matter.md) · [0015](../adr/0015-one-state-module.md)

## Summary

There is one new kit file, `.factory/state/state.py`, standard library only. It defines three schemas (STATE, task, handoff), a front-matter parser and emitter, a validator, and a command-line interface. The gate and `install.py check` call its validator (ADR 0015). The kit gains two new state seeds under `docs/`, and its `STATE.md` seed becomes valid.

## Source layout

```text
kit/.factory/state/state.py   # schemas, parse/emit, validate(), resume(), CLI
kit/.agentic/STATE.md         # now valid front matter (init output, fixed time)
kit/docs/GLOSSARY.md          # new state seed
kit/docs/adr/README.md        # new state seed: the ADR format
kit/.factory/gates/gate.py    # + validate state before the checks (exit 2)
factory_installer/kit.py      # load_kit also reads kit/docs/ as state seeds
factory_installer/cli.py      # install.py check also validates state
```

## state.py

**Schemas.** Each schema is a tuple of `Field(name, kind, allowed)`, where `kind` is one of `str`, `int`, `datetime` or `strlist`. The task schema also has `[[findings]]`, whose items have their own fields: `id` (`F<n>`), `severity`, `status` and `summary`.

| File | Required body headings |
| --- | --- |
| `STATE.md` | none |
| `tasks/<id>.md` | `## Goal`, `## Acceptance criteria`, `## Notes` |
| `handoffs/*.md` | `## Done`, `## Next`, `## Open questions` |

**Parse.**
1. The text must start with `+++\n`, and the next line that is exactly `+++` closes the block.
2. `tomllib.loads` reads the TOML between them.
3. The result is `(front: dict, body: str)`, or a `Problem`.

CRLF is normalised to LF before parsing.

**Emit.** Fields are written in schema order:
- strings with `json.dumps`
- datetimes as `YYYY-MM-DDTHH:MM:SSZ`
- `strlist` as `["a", "b"]`
- each finding as a `[[findings]]` block

Writing the front matter for an existing file keeps its body bytes unchanged. Every write goes through `_write(path, text)`: write to a temp file in the same folder, then `os.replace`.

**Validate** (`validate(root) -> list[Problem]`):
1. **`STATE.md`:**
   - exactly the E01 placeholder text means "no state yet", with no problems
   - missing front matter is reported as "no front matter; run state.py init"
   - otherwise it's checked against the schema
2. **Each `tasks/*.md`** is checked against the schema. Its `id` must equal the file stem, and finding ids must be unique.
3. **Each `handoffs/*.md`** is checked against the schema. Its `task` must have a task file.
4. **Cross-check:** `active_task`, when it isn't empty, must have a task file.

Problems are sorted by path, then key.

**CLI** (`main(argv) -> int`): `init`, `check`, `task new|set`, `finding add|set`, `start`, `block`, `unblock`, `handoff` and `resume [--json]`.
- **Exit codes:** 0 on success; 1 on a refused action (it exists, unknown id, invalid state on disk); 2 on usage errors and invalid values (argparse, and the value checks).
- **Validation before writing:** every write command validates the files it touches before writing, and refuses (exit 1, printing the problems) if they're already invalid, so it never builds on bad state.
- **Root:** found from `--root` or the current directory, by walking up to the folder that holds `.agentic/`.

**Handoff file names:** `YYYYMMDDTHHMMSSZ-<task>.md`. If that name is taken in the same second, `-2`, `-3`… is added before `.md`, so nothing is ever overwritten.

**Resume.** `resume(root) -> dict`:
- `state`: the front matter and body
- `task`: the active task's front matter, its `open_findings` and its body
- `handoff`: the newest handoff for the active task, by file name, with its front matter and body
- `pending`: tasks that aren't `done`, when there's no active task

The text form prints these as labelled sections. `--json` prints the dict, with datetimes as ISO strings.

**Clock.** Commands take the current time from `_now()`, which tests patch with `monkeypatch`. Subprocess tests check the format instead of the value.

## Gate change

In `main`, after `Settings.load`:
- If `root/.factory/state/state.py` exists, load it with `importlib` under the module name `factory_state` and call `validate(root)`.
- If any problems come back, print `gate: <file>: <where>: <message>` for each to stderr and return 2. No check runs.

This happens before `--checks` matters, so the hooks get the same behaviour.

## Installer changes

- **`load_kit`** reads `.factory/`, `.agentic/` and `docs/` from the kit root. Files under `docs/` are state seeds, like `.agentic/`: not kit-managed, so `Kit.is_kit_managed` is unchanged.
- **The E01 test lists:** `STATE_FILES` gains `docs/GLOSSARY.md` and `docs/adr/README.md`, and `KIT_FILES` gains `.factory/state/state.py`. Those tests' expectations change, a precedent from E05/E06/E07.
- **`install.py check [PATH]`:** after the config report, it loads `kit/.factory/state/state.py` and validates the target. Each problem is printed as `<file>: <where>: <message>`. Any problem makes the exit code 1, with the summary line counting config errors and state problems together.

## Dogfooding (AC-16)

- **This repo** runs `state.py init` (its `STATE.md` is still the E01 placeholder), then creates the tasks `E02-T1` to `E02-T3`. It keeps them current with `start`, `task set`, `finding add` and `handoff` as the slices progress.
- **Live evidence:** at the start of T3, a new Claude Code session is started with only "Resume from .agentic: run `python .factory/state/state.py resume` and continue." It has to identify the active slice and carry on. Its transcript summary goes in the T3 PR.

## Test seams

- **In-process:** `state.main([...])` with `tmp_path` roots, and `capsys` for output. `pyproject.toml` adds `kit/.factory/state` to `pythonpath`, mypy `files` and coverage `source`.
- **AC-15:** two real subprocesses (`sys.executable kit/.factory/state/state.py ...`) that share only the temp repo.
- **Gate:** the existing `gate_repo` fixture plus a copy of `state.py`. Bad state gives exit 2 with nothing run, which a `touches()` marker proves.
- **Installer:** E01 helpers with `install.py check` on targets that hold valid and invalid state.

## Vertical slices

| Task | Slice | ACs |
| --- | --- | --- |
| T1 | Formats, parser, validator, `state.py check`, gate and `install.py check` integration, placeholder rule | AC-01 to AC-05 |
| T2 | Write commands: `init`, `task new/set`, `finding add/set`, `start`, `block/unblock`, `handoff`, atomic writes | AC-06 to AC-11, AC-13 |
| T3 | `resume`, seeds (glossary, ADR README, valid `STATE.md`), two-process resume test, dogfooding and live evidence, E02 AC coverage enforced | AC-12, AC-14 to AC-17 |

## Risks

- **Mutation cost:** `state.py` will be roughly 400 lines, so many mutants. Each slice's PR runs mutation on its changed lines only, and on Windows CI that takes the longest (E07: 461 s on a small change). Keeping slices small keeps this bounded.
- **This repo's own state files are validated by its gate.** A malformed hand edit blocks commits through the pre-commit hook. That's intended, but it's new friction.
