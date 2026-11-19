# E03 · Agent schema and tool scoping design note

Spec: [E03 spec](../specs/E03-agent-schema.md) · Issue: [#3](https://github.com/michael-muir/software-factory/issues/3)
Status: **Accepted by the product owner, 18 Nov 2026** · ADRs: [0016](../adr/0016-one-agents-module-on-top-of-state.md) · [0017](../adr/0017-claude-code-hook-resolves-role-and-fails-closed.md) · [0018](../adr/0018-test-locks-are-hash-records-checked-by-the-gate.md)

## Summary

There's one new kit module, `.factory/agents/agents.py`, standard library only. It reuses `state.py`'s front-matter parser, `Problem` type and atomic writer (ADR 0016). It holds:
- the agent schema and validator
- the allow/deny checker
- test lock records and their verification
- the Claude Code hook
- the CLI

The gate and `install.py check` call it the way they call `state.py`. A small shell launcher runs the hook with a Python 3.11+, and this repo registers it in `.claude/settings.json`.

## Source layout

```text
kit/.factory/agents/agents.py      # schema, validate(), allow(), locks, hook, CLI
kit/.factory/agents/claude-hook    # POSIX sh launcher: finds Python 3.11+, runs `agents.py hook claude-code`
kit/.factory/agents/_schema.md     # the format, as tables a test compares with the code
kit/.factory/agents/_template.md   # a role to copy
kit/.agentic/locks/.gitkeep        # new state seed
kit/.factory/gates/gate.py         # + validate agents, then verify locks, before any check
factory_installer/cli.py           # install.py check also validates agents and locks
.claude/settings.json              # this repo only: registers the hook (AC-13)
```

The empty `.factory/agents/.gitkeep` goes away, since the folder now has files.

## agents.py

**Loading state.py.** On import, `agents.py` loads `../state/state.py` (its sibling in the kit) with `importlib` under the name `factory_state`, which is the same name the gate uses. If `state.py` is missing, every command exits 2 with "agents.py needs .factory/state/state.py". The kit always ships both.

**Agent files.** Every `*.md` under `.factory/agents/`, at any depth, is a role, except names starting with `_`. Each is parsed with `state.parse`, then checked against `AGENT_SCHEMA`:

| Key | Kind | Rule |
| --- | --- | --- |
| `name` | str | `[a-z0-9-]+`, equal to the file stem, unique across all folders |
| `title`, `summary` | str | non-empty |
| `model_hint` | str | `strong`, `any` or `different-from` |
| `different_from` | str | another role's name if the hint is `different-from`, else `""` |
| `tools` | strlist | non-empty, from `TOOLS`, no duplicates |
| `scope` | table, optional | only the keys `write` (strlist of globs) and `run` (strlist of prefixes) |

Required headings: `## Scope`, `## Inputs`, `## Outputs`.

**Globs.** Python 3.11 has no `PurePath.full_match`, so `agents.py` has its own matcher. It splits a pattern and a path on `/`:
- `**` matches zero or more segments
- otherwise each segment matches with `fnmatch.fnmatchcase`, where `*` and `?` never cross a `/`

Globs and paths are rejected if they're absolute, contain `\`, or contain a `..` segment.

**The checker.** `allow(root, role, tool, path=None, command=None) -> Decision(allowed, reason)`. It checks in this order, and the first failure decides:
1. The tool is in the role's `tools`.
2. **`edit` or `write`:**
   - The path, resolved against the repo root (symlinks resolved), must be inside the root. The comparison uses `os.path.normcase` so it works on Windows.
   - It must match `[scope].write`, when that's set.
   - It must not be a locked file.
3. **`run`**, when `[scope].run` is set:
   - The command must not contain shell control text: `;`, `&`, `|`, `` ` ``, `$(`, `>`, `<` or a newline. Without this rule, `uv run pytest && rm -rf .` would pass a `uv run pytest` prefix.
   - Its `shlex.split` tokens must start with one prefix's tokens.

`read`, `search` and `web` have no scopes in E03.

**The hook.** `hook claude-code`, covered in ADR 0017:
- reads the JSON on stdin
- resolves the role
- maps `tool_name` with the table below
- takes `tool_input.file_path` for Edit, MultiEdit and Write, `tool_input.notebook_path` for NotebookEdit, and `tool_input.command` for Bash
- calls `allow`

The whole body runs inside `try`/`except BaseException`, so a crash prints the error and exits 2 instead of letting the call through.

| Claude Code | Neutral |
| --- | --- |
| Read | read |
| Glob, Grep | search |
| Edit, MultiEdit, NotebookEdit | edit |
| Write | write |
| Bash | run |
| WebFetch, WebSearch | web |

**Locks** (ADR 0018):
- `lock(root, task, paths, replace=False)`
- `unlock(root, task)`
- `verify_locks(root) -> list[str]`, one line per changed or missing file

The hash is SHA-256 of the file's bytes after CRLF and CR are turned into LF, the same as the manifest (ADR 0004). Writes use `state._write`.

**Validate.** `validate(root) -> list[Problem]` covers the agent files and the lock records. `verify_locks` is separate, because a changed lock is a gate failure (exit 1), not invalid configuration (exit 2).

**CLI** (`main(argv) -> int`): `check`, `allow`, `lock`, `unlock` and `hook claude-code`. The exit codes follow `state.py`:
- 0: success or allow
- 1: a problem, a denial or a refused action
- 2: usage errors and invalid values

The hook itself uses 0 and 2 only.

## Gate change

In `main`, right after the state validation:
1. If `root/.factory/agents/agents.py` exists, load it under the name `factory_agents`, then call `validate(root)`. Problems are printed as `gate: <file>: <where>: <message>`, and the gate returns 2.
2. Call `verify_locks(root)`. Each line is printed as `gate: <path>: locked by <task>: changed|missing`, and the gate returns 1. No check runs.

Both steps run before `--checks` is applied, so the pre-commit hook enforces locks too (AC-10).

## Installer change

`install.py check` loads the kit source's `agents.py` (as `factory_kit_agents`). That module finds its sibling `state.py` in the kit. It reports `validate(target)` problems after the state problems, in the same format, and they count towards exit 1. `install.py check` doesn't verify lock hashes: that's the gate's job.

## Dogfooding (AC-13)

- **`.claude/settings.json`:** a `PreToolUse` hook with matcher `Read|Glob|Grep|Edit|MultiEdit|NotebookEdit|Write|Bash|WebFetch|WebSearch`, command `sh "${CLAUDE_PROJECT_DIR}/.factory/agents/claude-hook"`, `onFailure: "block"` and a 10 s timeout. It's added in T3, once the hook exists.
- **Locks:** T2 and T3 lock their failing tests with `agents.py lock E03-Tn <files>` in the locked-tests commit, before the implementation commit. T1 builds the lock command, so its tests are locked when T1 ends.
- **State:** the tasks E03-T1 to E03-T3 are tracked in `.agentic/`.

## Test seams

- **In-process:** `agents.main([...])` with `tmp_path` repos that hold a copy of `state.py` and `agents.py`. `pyproject.toml` adds `kit/.factory/agents` to `pythonpath`, mypy `files` and coverage `source`.
- **Hook:** a subprocess runs `agents.py hook claude-code` with JSON on stdin, and with and without `FACTORY_ROLE` and `agent_type`. A crash is forced by making `state.py` unloadable, and must exit 2.
- **Launcher:** `claude-hook` is run through `sh`. POSIX only, like the git-hook tests.
- **Gate:** the existing `gate_repo` fixture, plus copies of both modules. A changed locked file gives exit 1 with nothing run; an invalid role file gives exit 2.
- **`_schema.md` sync:** a test parses its Markdown tables and compares them with `agents.AGENT_SCHEMA`, `TOOLS`, `HINTS` and the Claude Code map.

## Vertical slices

| Task | Slice | ACs |
| --- | --- | --- |
| T1 | `agents.py` skeleton on top of `state.py`; lock records, `lock` and `unlock`; `check` for locks; the gate's lock check; `install.py check`; the `.agentic/locks/` seed | AC-03 and AC-04 for locks, AC-09 to AC-11 |
| T2 | Agent file format and validation; `_schema.md`, `_template.md`; `check` for agents; the gate and installer validate roles | AC-01 to AC-04 |
| T3 | The checker; the hook and its launcher; `.claude/settings.json`; the done-when end-to-end test; E03 AC coverage enforced | AC-05 to AC-08, AC-12 to AC-14 |

Locks come first, so T2 and T3 can lock their own tests before they're implemented.

## Risks

- **Locks add friction for humans.** The pre-commit hook rejects any change to a locked test. That's the point, but fixing a mistake in a locked test now needs `agents.py lock --replace`. E02/T2's "fix five mistakes in the locked tests" commit would have needed a relock. The relock shows up in review as a change to `.agentic/locks/`.
- **The hook adds a Python start to every tool call,** about 50 to 100 ms, with a 10 s timeout. That's acceptable for M1. If it isn't, E12 can switch to a long-lived process.
- **Claude Code's hook contract can change.** Only the hook code touches it, and the end-to-end test pins the fields it relies on: `tool_name`, `tool_input`, `agent_type` and exit 2.
- **Mutation cost:** `agents.py` will be roughly 450 lines. Each slice's PR mutates only its changed lines, as in E02.
