# E09 · 16 core role definitions — Spec

Issue: [#9](https://github.com/michael-muir/software-factory/issues/9) · Milestone: M1 · Manual factory (alpha) · Depends on: E03 (done)
Status: **Approved by the product owner, 19 Nov 2026** · Next: Architect design note and ADRs, then failing tests per AC

## Goal

The line's 16 core agents become role files in the E03 format. Each file states what the role does and must not do, what it reads and produces, who it hands off to, the tools it may use, and a model hint. Installing the kit gives every factory repo the same crew, and the E03 hook holds each role to its tool list. E10 adds the skills these roles name, and E12 compiles the roles for Claude Code, Copilot and Cursor. E09 delivers:
- **`.factory/agents/core/`:** 16 role files, from the Router to Retro.
- **Tool lists and limits** that put the blueprint's rules into practice. Reviewers and the Verifier can't change code, and nobody can edit a locked test.

**Done when:** each role has scope, tools, inputs, outputs and a model hint (PRD).

## Decisions in force (product owner, 19 Nov 2026)

| Topic | Decision |
| --- | --- |
| The 16 | The blueprint's core agents, **including the Release Manager**. E09 defines that role; E29 builds the semver release flow it runs. |
| Scopes | **Tool lists, plus run limits** for the Verifier and the four code reviewers: they can only run the gate, the state tool and read-only git commands. No default path globs, because the kit installs into repos of any layout. Locks protect the tests (E03). A repo may tighten any role. |
| Body | **A role card** of about a page: `## Scope` (does, and must not), `## Inputs`, `## Outputs` and `## Hand-off`. Procedures live in E10 skills, which the cards name. |
| Model hints | **Blueprint defaults:** `strong` for the roles that decide or build, `different-from` the author for every reviewer and the Adversary, and `any` for the Docs Writer, Release Manager and Retro. |

## In scope

- 16 role files as kit files, all valid under E03's `agents.py check`.
- Tool lists, run limits and model hints as in the tables below, pinned by tests.
- Role cards whose hand-offs name real roles.
- Dogfooding: this repo installs the roles, and a session started as one of them is held to it by the hook.

## Out of scope

- The skills the cards name (E10). A card may name a skill before it exists.
- Compiling roles into Claude Code subagents, Copilot or Cursor (E12).
- Running the pipeline, the review rounds or the Router's dispatch (E13, E14, E19).
- Mapping hints to real models (E20).
- Domain experts and the release flow (E29). The Watchdog and the triage filter are control services, not roles (E22, E25).

## The roles

| Role (`name`) | Stage | Tools | Run limit | Model hint |
| --- | --- | --- | --- | --- |
| Router (`router`) | Coordinate | read, search, run | none | strong |
| Spec Writer (`spec-writer`) | Specify | read, search, edit, write, web | none | strong |
| Architect (`architect`) | Specify | read, search, edit, write, web | none | strong |
| Test Designer (`test-designer`) | Make | read, search, edit, write, run | none | strong |
| Implementer (`implementer`) | Make | read, search, edit, write, run | none | strong |
| Debugger (`debugger`) | Make | read, search, edit, write, run | none | strong |
| Docs Writer (`docs-writer`) | Make | read, search, edit, write | none | any |
| Verifier (`verifier`) | Prove | read, search, run | reviewer limit | any |
| Spec Reviewer (`spec-reviewer`) | Prove | read, search, run | reviewer limit | different-from `implementer` |
| Standards Reviewer (`standards-reviewer`) | Prove | read, search, run | reviewer limit | different-from `implementer` |
| Security Reviewer (`security-reviewer`) | Prove | read, search, run | reviewer limit | different-from `implementer` |
| Perf Reviewer (`perf-reviewer`) | Prove | read, search, run | reviewer limit | different-from `implementer` |
| Adversary (`adversary`) | Prove | read, search, write, run | none | different-from `implementer` |
| Integrator (`integrator`) | Deliver | read, search, run | none | any |
| Release Manager (`release-manager`) | Deliver | read, search, edit, write, run | none | any |
| Retro (`retro`) | Learn | read, search, edit, write | none | any |

**The reviewer limit** (`[scope].run`) is a set of command prefixes. It allows the gate (`.factory/gates/gate.py`) and the state tool (`.factory/state/state.py`), each through `python`, `python3`, `py` or `uv run python`. It also allows `git diff`, `git log`, `git show` and `git status`. Reviewers record findings through the state tool (E02).

## Acceptance criteria

**The files**

- **AC-01** The kit ships `.factory/agents/core/` with exactly the 16 files named in the table, and `agents.py check` passes on them. Each one's `name` matches its file and its `title` matches the table.
- **AC-02** Each role's `tools` are exactly those in the table.
- **AC-03** The Verifier and the four code reviewers have exactly the reviewer limit as `[scope].run`. No other role has a `[scope]`.
- **AC-04** Each role's `model_hint` and `different_from` match the table.

**The role cards**

- **AC-05** Each body has these headings:
  - `## Scope`, with a `Does:` list and a `Must not:` list
  - `## Inputs`
  - `## Outputs`
  - `## Hand-off`, naming at least one role by its `name` in backticks, and only names that exist. Retro may hand off to `human`.
- **AC-06** Each `summary` is one sentence that states the blueprint's one-liner for the role. For example, the Verifier's: "Runs the gate; a claim without a report counts for nothing." A test pins the 16 summaries.
- **AC-07** Each card's `Must not:` list has at least one item. These rules must appear:
  - Implementer: editing locked tests
  - Test Designer: writing tests from the code instead of the spec
  - every reviewer, and the Verifier: changing code
  - Integrator: merging without approval

**Held to it by the hook**

- **AC-08** **Done-when, in a test:** in a temp repo with the kit installed, the E03 hook enforces the roles.
  - With `FACTORY_ROLE` set to each of the 16, every tool the role lists is allowed (given a path or command that's in bounds), and every tool it doesn't list is blocked.
  - `spec-reviewer` can run the gate and `git diff`, but `rm -rf build` and an Edit are blocked.
  - `implementer` is blocked from editing a locked test.

**Installing and dogfooding**

- **AC-09** The roles are kit files: `install.py` installs them, `install.py check` passes, and a repo's own edit to a role (for example, a tighter limit) is kept on upgrade, under E01's rules.
- **AC-10** **This repo** installs the roles, and its gate passes with them in place. The PR records a live check of a session started with `FACTORY_ROLE=verifier`: the gate runs, and an Edit is blocked.
- **AC-11** ruff, `ruff format --check` and `mypy --strict` pass. The kit layout tests list the 16 files. Every AC above has at least one test tagged `E09-AC-nn`, except the live part of AC-10.

## Assumptions (confirmed with approval, 19 Nov 2026)

1. **Hints for the three roles the decision didn't name:** the Test Designer is `strong`, and the Verifier and Integrator are `any`, because the gate does the Verifier's judging and the Integrator's work is mechanical.
2. **The Adversary and the Integrator have no run limit.** The Adversary runs its attacks with the project's own test tools. The Integrator needs `git` and `gh` to commit and open PRs. The Integrator can't write files at all. The Adversary has `write` but not `edit`; `write` can also replace a file, so its card forbids changing existing code, and review and the gate catch it if it does. Locked tests stay locked.
3. **Reviewers are `different-from` the Implementer,** the author of the code under review. The Spec Reviewer checks the diff against the spec, as the blueprint says, so it differs from the Implementer, not the Spec Writer.
4. **Skill names in the cards are provisional.** E10 may rename them, and E10 updates the cards when it does.
5. **The Router is one role.** The blueprint's "Router · Orchestrator" is a single long-lived session.
