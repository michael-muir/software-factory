# E03 · Agent schema and tool scoping — Spec

Issue: [#3](https://github.com/michael-muir/software-factory/issues/3) · Milestone: M1 · Manual factory (alpha) · Depends on: E01 (done)
Status: **Approved by the product owner, 18 Nov 2026** · Next: Architect design note and ADRs, then failing tests per AC

## Goal

Every agent role is a plain file in one neutral format, and each role can use only the tools its file lists. The blueprint's rule "the author never grades the work" depends on this: an Implementer that can rewrite the tests that judge it is grading its own work. E03 delivers:
- **`.factory/agents/_schema.md`:** the agent file format, including `model_hint` and the tool list.
- **`.factory/agents/agents.py`:** a standard-library tool that validates agent files, decides whether a role may make a given tool call, records test locks, and acts as a Claude Code hook.
- **Test locks:** a record of the locked test files, checked by the gate on every run.

**Done when:** a role can't call a tool outside its list, and an edit to a locked test is rejected.

## Decisions in force (product owner, 18 Nov 2026)

| Topic | Decision |
| --- | --- |
| Enforcement | A **checker** in `agents.py` decides allow or deny for each tool call. E03 wires it into a **Claude Code `PreToolUse` hook**. E12 wires the same checker into Copilot and Cursor. |
| Test locks | The Test Designer **records locked test files with their hashes** in `.agentic/locks/`. The **gate fails** if a locked file changes, and the checker **denies edits** to locked files. |
| File format | Markdown with **TOML front matter** between `+++` lines, the same as the state files (ADR 0014). Adapters (E12) convert it to each tool's own format. |
| Tool grain | A **neutral vocabulary**: `read`, `search`, `edit`, `write`, `run` and `web`. It has optional **scopes**: path globs for `edit` and `write`, and command prefixes for `run`. |

## In scope

- The agent file format, `_schema.md`, and a `_template.md` to copy from.
- Agent file validation in `agents.py check`, `install.py check` and the gate.
- The allow/deny checker and the Claude Code hook.
- Test lock records, the `lock` and `unlock` commands, and the gate's lock check.
- Dogfooding: this repo runs the hook and locks its own E03 tests.

## Out of scope

- The 16 core role definitions (E09). E03 tests use fixture roles.
- Compiling roles for Copilot and Cursor, and installing hooks into a target repo's tool settings (E12).
- Mapping `model_hint` to real models (E20). E03 only defines and validates the hint.
- Delegation, meaning one agent starting another (E13 and E19).
- OS-level sandboxing. The hook guards tool calls, and the gate is the backstop (assumption 2).

## The files

**`.factory/agents/<name>.md`**, one per role. Core roles go in `core/` (E09) and domain experts in `domains/` (E29). Files whose names start with `_` aren't roles.

```markdown
+++
name = "implementer"              # matches the file name; [a-z0-9-]+
title = "Implementer"
summary = "Smallest change to green."
model_hint = "strong"             # strong | any | different-from
different_from = ""               # a role name; required only for different-from
tools = ["read", "search", "edit", "write", "run"]

[scope]                           # optional; each key narrows one tool
write = ["src/**", "tests/**"]    # globs for edit and write; default: the whole repo
run = ["uv run pytest", "python .factory/gates/gate.py"]   # command prefixes; default: any
+++

## Scope
## Inputs
## Outputs
```

**The tool vocabulary**

| Tool | Means | Claude Code tools |
| --- | --- | --- |
| `read` | read a file | Read |
| `search` | find files or text | Glob, Grep |
| `edit` | change an existing file | Edit, MultiEdit, NotebookEdit |
| `write` | create or replace a file | Write |
| `run` | run a shell command | Bash, PowerShell (hook only) |
| `web` | fetch or search the web | WebFetch, WebSearch |

**`.agentic/locks/<task>.toml`**, written by `agents.py lock`:

```toml
task = "E03-T1"
locked = 2026-11-19T03:00:00Z

[[files]]
path = "tests/test_agents_schema.py"
sha256 = "…"                      # of the LF-normalised content (ADR 0004)
```

## Acceptance criteria

**Format and validation**

- **AC-01** An agent file is valid when:
  - it has `+++` TOML front matter with exactly the keys above, of the right types
  - `name` matches its file name and is `[a-z0-9-]+`, and no two agent files share a name
  - `tools` is a non-empty list of vocabulary tools with no duplicates
  - `model_hint` is `strong`, `any` or `different-from`
  - `different_from` names another agent file when the hint is `different-from`, and is `""` otherwise
  - `[scope].write` appears only with `edit` or `write`, and `[scope].run` only with `run`
  - globs and paths are relative, use `/`, and contain no `..`
  - the body has the `## Scope`, `## Inputs` and `## Outputs` headings
- **AC-02** `_schema.md` documents every key, every tool and the meaning of each hint. A test checks that its tables list exactly the keys, tools and hints the validator accepts. `_template.md`, copied to a new role name, is a valid agent file.
- **AC-03** `agents.py check` validates every agent file under `.factory/agents/` and every lock record. It prints one line per problem, as `<file>: <key or heading>: <problem>`, and exits 1 if there are any problems, else 0.
- **AC-04** `install.py check` runs the same validation and reports problems in the same format. The gate runs it before any check, exits 2 on problems, and runs nothing. Both skip it when `agents.py` is absent, for kits older than E03.

**The checker**

- **AC-05** `agents.py allow <role> <tool> [--path P] [--command C]` exits 0 to allow and 1 to deny, and prints the reason for a denial. It denies when:
  - the tool isn't in the role's `tools`
  - an `edit` or `write` path is outside the repo, or outside `[scope].write`
  - an `edit` or `write` path is a locked file
  - a `run` command doesn't start with one of the `[scope].run` prefixes, matched on whole words

  An unknown role, or invalid agent files, exits 2. `*` matches within one path segment and `**` matches any depth.
- **AC-06** **Claude Code hook:** `agents.py hook claude-code` reads Claude Code's `PreToolUse` JSON from stdin, maps the tool name with the table above, and applies AC-05 for the role named by the `FACTORY_ROLE` environment variable. It exits 0 to allow. It exits 2 to block, with the reason on stderr (Claude Code's blocking convention). A tool name that isn't in the table is denied whenever a role is set.
- **AC-07** **No role set:** when `FACTORY_ROLE` is unset or empty, tool lists don't apply, but edits and writes to locked files are still denied.
- **AC-08** **Fails closed:** malformed hook input, an unknown role, or invalid agent files block the call with a message, and never allow it.

**Test locks**

- **AC-09** `agents.py lock <task> <path>...` writes `.agentic/locks/<task>.toml` with each file's SHA-256, taken after normalising line endings (ADR 0004). `<task>` must have an E02 task file, and every path must be an existing file in the repo. It refuses to replace an existing lock unless `--replace` is given. `agents.py unlock <task>` removes the record. Both write atomically.
- **AC-10** **The gate checks locks** on every run, including `--checks` runs and therefore the pre-commit hook. If a locked file is changed or missing, the gate prints `<path>: locked by <task>: changed` (or `missing`) for each one, fails with exit 1, and runs no other checks.
- **AC-11** Lock records are validated by AC-03: exact keys and types, a 64-hex `sha256`, a task file that exists, and no path locked by two tasks.

**End to end and dogfooding**

- **AC-12** **Done-when, in a test:** a temp repo has a fixture role with `tools = ["read", "search"]`. With `FACTORY_ROLE` set to it, the hook allows Read and Grep, and blocks Edit, Write and Bash. With a fixture Implementer role, the hook blocks an Edit to a locked test. Changing that locked file on disk makes the gate fail.
- **AC-13** **This repo** registers the hook in `.claude/settings.json`, and locks E03's own failing tests with `agents.py lock` before each implementation commit. CI's gate verifies the locks on three OSes.

**Quality**

- **AC-14** ruff, `ruff format --check` and `mypy --strict` pass. `agents.py` stays standard-library only. The kit layout tests list the new kit files, and `.agentic/locks/` as a state seed. Every AC above has at least one test tagged `E03-AC-nn`, except the live parts of AC-13.

## Assumptions (confirmed with approval, 18 Nov 2026)

1. **The role comes from `FACTORY_ROLE`.** The Architect checks whether Claude Code's hook input names the subagent, and may use that too. The decision goes in an ADR.
2. **The hook is a guard, not a sandbox.** A `run` command can still change a locked file, for example through `sed -i`. The gate's lock check catches that before anything is merged.
3. **Locks list files, not folders.** Adding a test to a locked task means relocking with `--replace`, which is a human's decision.
4. **One writer at a time,** as in E02.
5. **Delegation tools are unmapped,** so they're denied while a role is set, until E13 and E19 add a `delegate` tool.

## Changes

- **20 Nov 2026, approved by the product owner (E12 PR #68):** the Claude Code hook maps the `PowerShell` tool, Claude Code's shell on Windows, to `run`, as it maps `Bash`. Agent files still list `Bash` only. A `run` scope's shell control check also treats PowerShell syntax as control: `$`, `(`, `)`, `@` at the start of a word, and line or paragraph separators, beside `;`, `&`, `|`, `` ` ``, `>`, `<` and newlines.
