# E12 · Tool adapters — Spec

Issue: [#12](https://github.com/michael-muir/software-factory/issues/12) · Milestone: M1 · Manual factory (alpha) · Depends on: E09 (done), E10 (done)
Status: **Approved by the product owner, 19 Nov 2026** · Next: Architect design note and ADRs, then failing tests per AC

## Goal

The factory's roles and skills are written once, in the neutral formats of E03 and E10. E12 compiles them into the native files that Claude Code, GitHub Copilot and Cursor each read. It also wires the E03 checker into each tool's `preToolUse` hook, so a role is held to its tools, and locked tests stay locked, whichever tool runs it. E12 delivers:
- **`.factory/adapters/build.py`:** compiles roles, skills and hooks for the three tools, and checks that the committed output is current.
- **Hooks for Copilot and Cursor:** `agents.py hook copilot` and `agents.py hook cursor`, beside E03's `hook claude-code`.
- **A drift check in the gate,** so the tool files can't fall out of step with their source.

**Done when:** the same role runs in all three tools from one source (PRD).

## Decisions in force (product owner, 19 Nov 2026)

| Topic | Decision |
| --- | --- |
| Output | **Native files per tool**, in each tool's own documented format and folder. |
| Generation | **Build, commit and drift check.** `build.py` writes the files, and `install.py` runs it. The files are committed, and the gate fails when one is stale. |
| Hooks | **All three tools.** Each tool's `preToolUse` hook calls the E03 checker. |
| Done-when | **Tests plus a live check.** Automated tests check every generated file against its tool's documented format and hook protocol. Then the product owner runs one role in Copilot and Cursor, and the PR records what they saw. |

## In scope

- Compiling the 16 core roles (and any role a repo adds) into each tool's agent format.
- Copying the skills into each tool's skills folder.
- Generating each tool's hook configuration, and adding `hook copilot` and `hook cursor` to `agents.py`.
- `build.py` and its `--check` mode, run by `install.py` and by the gate.
- Dogfooding: this repo commits its generated files, and CI checks them.

## Out of scope

- Mapping `model_hint` to a model ID per tool (E20). E12 sets no model, so each tool uses its default.
- MCP servers, Copilot's organization-level agents, and Cursor's team or dashboard hooks.
- Tools other than these three, such as Codex. The design should make a fourth adapter easy, but E12 doesn't build one.
- Running a role automatically in a pipeline (E13).

## The outputs

| Source | Claude Code | GitHub Copilot | Cursor |
| --- | --- | --- | --- |
| Role `.factory/agents/**/<name>.md` | `.claude/agents/<name>.md` | `.github/agents/<name>.agent.md` | `.cursor/agents/<name>.md` |
| Skill `.factory/skills/<name>/` | `.claude/skills/<name>/` | `.github/skills/<name>/` | `.cursor/skills/<name>/` |
| The checker (E03) | `.claude/settings.json`, `PreToolUse` | `.github/hooks/factory.json`, `preToolUse` | `.cursor/hooks.json`, `preToolUse` |

**Tool names**

| Neutral (E03) | Claude Code agent `tools` | Copilot agent `tools` | Copilot hook `toolName` | Cursor hook `tool_name` |
| --- | --- | --- | --- | --- |
| `read` | Read | `read` | `view` | `Read` |
| `search` | Glob, Grep | `search` | `glob`, `grep` | `Grep` |
| `edit` | Edit, MultiEdit, NotebookEdit | `edit` | `edit` | `Write` (Cursor matches edits as writes) |
| `write` | Write | `edit` | `create` | `Write` |
| `run` | Bash | `execute` | `bash`, `powershell` | `Shell` |
| `web` | WebFetch, WebSearch | `web` | `web_fetch` | none documented |

**Who is the role**, per tool (E03's ADR 0017 order):
- **Claude Code:** `agent_type`, then `FACTORY_ROLE`.
- **Copilot:** `agentType` (or `agent_type`), then `FACTORY_ROLE`.
- **Cursor:** `FACTORY_ROLE` only, because Cursor's `preToolUse` payload names no agent.

## Acceptance criteria

**Compiling**

- **AC-01** `build.py` writes one agent file per role for each tool:
  - **Claude Code:** YAML front matter with `name`, `description` (the role's `summary`) and `tools` (the role's tools mapped to Claude Code names, comma-separated), then the role card's body.
  - **Copilot:** `.agent.md`, with `name`, `description` and `tools` (a list of Copilot aliases, each once), then the card's body.
  - **Cursor:** `name` and `description`, then the card's body.

  A test pins the tool tables above.
- **AC-02** `build.py` copies each skill folder unchanged into each tool's skills folder. Every file of the folder comes byte for byte.
- **AC-03** `build.py` writes each tool's hook configuration. Each one runs the tool's hook through a `sh` launcher that finds Python 3.11+:
  - **Claude Code:** `.claude/settings.json`, keeping every other setting in the file. E03's entry becomes generated.
  - **Copilot:** `.github/hooks/factory.json`, version 1, `preToolUse`, with a `bash` command (the only one the cloud agent honors), a `powershell` command and a timeout.
  - **Cursor:** `.cursor/hooks.json`, version 1, `preToolUse`, with `failClosed: true` and a timeout.

**The hooks**

- **AC-04** `agents.py hook copilot` reads Copilot's `preToolUse` payload, in either its camelCase form (`toolName`, `toolArgs`) or its VS Code form (`tool_name`, `tool_input`). It maps the tool, resolves the role, and applies E03's `allow`. To deny, it prints `{"permissionDecision": "deny", "permissionDecisionReason": "<reason>"}` and exits 2. To allow, it prints nothing and exits 0.
- **AC-05** `agents.py hook cursor` reads Cursor's `preToolUse` payload (`tool_name`, `tool_input`), maps the tool, resolves the role from `FACTORY_ROLE`, and applies `allow`. To deny, it prints `{"permission": "deny", "user_message": ..., "agent_message": ...}` and exits 2. To allow, it prints nothing and exits 0.
- **AC-06** **Both hooks fail closed,** as E03's does (AC-08 there): bad input, an unknown role, invalid agent files or a crash give a deny with a reason, never an allow. Unmapped tools are denied when a role is set, and allowed when none is. Locked files are always protected.

**Staying in step**

- **AC-07** Output is deterministic: the same source gives the same bytes, with LF line endings. Every generated agent file carries a notice that it's generated by `build.py` and must not be edited, wherever its format allows one.
- **AC-08** `build.py --check` writes nothing. It exits 1 and names each generated file that's missing, stale, or no longer produced, and exits 0 when all are current. **The gate** runs the check on every run, including `--checks` runs. Drift fails the verdict and is listed in the report, but the checks still run (ADR 0020's pattern). A kit without `build.py` skips the check.
- **AC-09** `install.py` runs the build after installing the kit, and `install.py check` reports drift. A repo chooses its tools in `.agentic/config.toml` (`[adapters] tools`, default all three). Files for a tool that's dropped from the list are removed on the next build.

**Done-when**

- **AC-10** **In a test:** from one role source in a temp repo, the build produces the role's agent file for all three tools, each matching its tool's documented format. The same out-of-list call, given in each tool's own payload form, is denied by all three hooks, using each tool's own deny protocol. An in-list call is allowed by all three.
- **AC-11** **Live (product owner):** in this repo, a role is started in Copilot and in Cursor, and in Claude Code, from the generated files. Each tool shows the role, and a call outside its tools is blocked. The PR records what was seen in each tool.

**Dogfooding and quality**

- **AC-12** This repo commits its generated files, and CI's gate checks them for drift on three OSes. ruff, `ruff format --check` and `mypy --strict` pass, `build.py` is standard library only, the kit layout tests list the new kit files, and every AC above has at least one test tagged `E12-AC-nn`, except AC-11.

## Assumptions (confirmed with approval, 19 Nov 2026)

1. **Cursor can't scope a subagent's tools in its own files.** Its subagents have no tool list (only `readonly`), and its `preToolUse` payload doesn't name the agent. So in Cursor a role is enforced through `FACTORY_ROLE` and the hook, and locks always apply. Cursor's agent files carry the card, so the role still runs as itself.
2. **Copilot's `edit` alias covers both editing and creating files,** so the neutral `write` maps to it. `web` isn't available to Copilot's cloud agent, so there it's simply absent.
3. **Copilot's hooks cover its CLI and cloud agent.** VS Code's Copilot hooks are a preview, and E12 doesn't rely on them.
4. **A hook timeout lets the call through** in Copilot (as its docs say) and in Claude Code. The gate, which checks locks, is the backstop.
5. **The exact payload fields for a file's path,** in Copilot's `toolArgs` and Cursor's `tool_input`, are confirmed by the Architect against each tool's documentation before tests are written. The design note records them.
6. **Generated files aren't kit files.** They belong to the repo, are rebuilt from its own roles and skills, and are never kept on upgrade. A hand edit is overwritten by the next build, which is why they carry a notice.
