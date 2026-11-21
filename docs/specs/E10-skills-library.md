# E10 · Skills library (16) — Spec

Issue: [#10](https://github.com/michael-muir/software-factory/issues/10) · Milestone: M1 · Manual factory (alpha) · Depends on: E09 (done)
Status: **Approved by the product owner, 19 Nov 2026** · Next: Architect design note and ADRs, then failing tests per AC

## Goal

The procedures the roles follow become skills: one folder per skill, each with a `SKILL.md` in the open Agent Skills format. The E09 role cards already name most of them. A role says what it owns; a skill says how to do one job well, step by step, and how to tell it's done. E12 compiles the skills for Claude Code, Copilot and Cursor. E10 delivers:
- **`.factory/skills/<name>/SKILL.md`** for 16 skills.
- **A standard-library validator** for the Agent Skills format, run by the gate and `install.py check`.
- **Proof that each skill has been used end to end,** either live while building the factory or in a scripted run in a fixture repo.

**Done when:** each skill is exercised in at least one end-to-end run (PRD).

## Decisions in force (product owner, 19 Nov 2026)

| Topic | Decision |
| --- | --- |
| The 16 | The 12 skills the role cards name, apart from `pull-request-evidence`, which belongs to E08. Plus `handoff` (blueprint), and three this spec proposes: `resume-from-state`, `lock-tests` and `dependency-bump`. |
| Format | The **Agent Skills standard**: YAML front matter between `---` lines with `name` and `description`, then Markdown instructions. Claude Code reads it natively. The kit's validator reads it with the standard library. |
| Done-when | **Dogfood plus fixture runs.** Skills the factory uses on itself are exercised live while E10 is built, as recorded in its PRs. Every other skill gets one scripted run in a fixture repo, checked by a test. |

## In scope

- 16 skills as kit files, in `.factory/skills/<name>/SKILL.md`.
- A validator for the Agent Skills front matter, run by its CLI, the gate and `install.py check`.
- The factory's conventions for its own skills: the sections, who uses each skill, and the commands they rely on.
- Linking the role cards to real skills.
- The exercise record: a live use or a fixture run for every skill.

## Out of scope

- `pull-request-evidence` (E08). Until E08 ships it, the Integrator's card names it as an exception.
- Compiling skills into each tool's folder, such as `.claude/skills/` (E12).
- Running skills automatically in a pipeline (E13). E10's runs are done by a person or a session following the skill.
- Domain-expert skills (E29), and skills that publish to a marketplace.

## The skills

| Skill | Used by | What it covers |
| --- | --- | --- |
| `spec-interview` | `spec-writer` | Interview the requester one decision at a time; write and check the spec. |
| `design-note` | `architect` | Write the design note and ADRs, plan the slices and create their task files. |
| `tdd-slices` | `test-designer`, `implementer` | Write failing tests per AC, lock them, then make the smallest change to green. |
| `lock-tests` | `test-designer` | Lock, verify and (with approval) relock tests with `agents.py`. |
| `handoff` | every role | Write a handoff with `state.py handoff`: done, next, open questions. |
| `resume-from-state` | every role | Start a session from `.agentic/` alone, with `state.py resume`. |
| `verify-with-evidence` | `verifier` | Run the full gate, keep the report, and check each AC's test. |
| `spec-review` | `spec-reviewer` | Check the diff against every AC; record findings. |
| `standards-review` | `standards-reviewer` | Check the diff against the standards pack; cite rule ids. |
| `threat-check` | `security-reviewer` | Check inputs, secrets, permissions, dependencies and data exposure. |
| `perf-budget` | `perf-reviewer` | Find hot paths and check them against budgets. |
| `adversarial-testing` | `adversary` | Write attack tests in new files; record what breaks. |
| `debugging` | `debugger` | Reproduce, form a hypothesis, test it, fix the root cause, and add a regression test. |
| `retro` | `retro` | Find recurring failures; propose checks and standards as drafts. |
| `release` | `release-manager` | Pick the semver bump, date the changelog, and prepare a tag for a human. |
| `dependency-bump` | `router`, `implementer` | Bump one dependency on the lite track, with the full gate. |

## Acceptance criteria

**The files and the format**

- **AC-01** The kit ships `.factory/skills/<name>/SKILL.md` for exactly the 16 skills in the table. The kit's `.factory/skills/.gitkeep` goes.
- **AC-02** **A skill is valid** under the Agent Skills specification when:
  - it starts with YAML front matter between `---` lines, holding only the standard fields
  - `name` is 1 to 64 characters of `a-z`, `0-9` and `-`, with no leading, trailing or doubled hyphen, and matches its folder
  - `description` is 1 to 1024 characters
  - `license`, if present, is a string
  - `compatibility`, if present, is 1 to 500 characters
  - `metadata`, if present, maps strings to strings
  - `allowed-tools`, if present, is a string

  Problems are reported as `<file>: <field>: <problem>`. Front matter the standard-library reader can't read is a problem too, not a crash.
- **AC-03** The validator runs:
  - from its CLI, with exit 0 when clean and 1 on problems
  - in the gate, before any check (problems mean exit 2, and nothing runs, as with agent files)
  - in `install.py check`

  A kit without the validator skips it.

**The factory's skills**

- **AC-04** Each kit skill's body has:
  - `## When to use`
  - `## Steps`, as a numbered list
  - `## Done when`, as a list a reviewer can check

  It also has a `Used by:` line naming, in backticks, the roles in the table, all of which exist. Its `description` says what the skill does and, after "Use when", when to use it. Its `SKILL.md` stays under 500 lines.
- **AC-05** Every `skill: <name>` in a core role card names a kit skill, except `pull-request-evidence` until E08 ships it. Every skill's `Used by:` roles name it in their cards, and `handoff` and `resume-from-state` are named by all 16.
- **AC-06** The skills use the factory's real commands:
  - `tdd-slices` and `lock-tests` use `agents.py lock`
  - `handoff` uses `state.py handoff`, with the three headings
  - `resume-from-state` uses `state.py resume`
  - `verify-with-evidence` runs `.factory/gates/gate.py`
  - the review skills (`spec-review`, `standards-review`, `threat-check`, `perf-budget`, `adversarial-testing`) record findings with `state.py finding add`
  - `spec-interview` and `design-note` use the E04 templates and `docs.py check`

  `lock-tests` says that relocking needs a human's approval.

**Exercised end to end**

- **AC-07** **Done-when:** every skill is exercised once, and the record says how.
  - **Live:** the PR that shipped the skill, or a later E10 PR, names the skill and the commits where a session followed it.
  - **Fixture:** `tests/fixtures/skills/<name>/` holds a repo before and after a session followed the skill once. A test checks the "after" state with the factory's own tools (the gate, `state.py check`, `agents.py check` and `docs.py check`), and against the skill's `## Done when`.

  A test holds the record, and fails if any of the 16 is missing.

**Installing and dogfooding**

- **AC-08** Skills are kit files: `install.py` installs them, `install.py check` passes, and a repo's edit to a skill is kept on upgrade (E01).
- **AC-09** **This repo** installs the 16 skills, and its gate validates them.
- **AC-10** ruff, `ruff format --check` and `mypy --strict` pass. The validator is standard library only. The kit layout tests list the new files. Every AC above has at least one test tagged `E10-AC-nn`, except the live parts of AC-07.

## Assumptions (confirmed with approval, 19 Nov 2026)

1. **The three proposed skills:**
   - `resume-from-state`: E02's resume, as a procedure every role starts with
   - `lock-tests`: E03's locks, including the relock rule
   - `dependency-bump`: the lite track's first job, which E15 builds on
2. **The validator reads a YAML subset:** `key: value` lines with plain or quoted strings, and `metadata` as a one-level map. Anything else is reported as unsupported, rather than parsed wrongly. The kit's own skills use only that subset.
3. **Skills live in `.factory/skills/`,** like the rest of the kit. The blueprint's `skills/` is shorthand for it, and E12 copies them to each tool's skills folder.
4. **Kit skills don't set `allowed-tools`.** A role's tool list governs what a session may do (E03), and the field is still experimental in the standard.
5. **A live exercise counts once it's recorded.** The PR or handoff names the skill and the commits. A fixture run is the fallback for skills that building E10 doesn't use, such as `threat-check` or `release`.

## Changes

- **20 Nov 2026, approved by the product owner (E08-T5):** E08 ships `pull-request-evidence`, the skill the Integrator card already named, so the kit has 17 skills. AC-01's count and the table stand for the 16 that E10 delivered. AC-05's exception for `pull-request-evidence` is gone, and every `skill:` a card names is a kit skill. Its exercise record is live: E08's PRs #77 and #78 were drafted with `evidence.py` and checked with `check-pr --strict`. E10-T3's locked test was relocked for this, with approval.
