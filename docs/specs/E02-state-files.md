# E02 · State files — Spec

Issue: [#2](https://github.com/michael-muir/software-factory/issues/2) · Milestone: M1 · Manual factory (alpha) · Depends on: E01 (done)
Status: **Approved by the product owner, 18 Nov 2026** · Next: Architect design note and ADRs, then failing tests per AC

## Goal

All factory state lives in files in git, so any session (or any tool) can pick up where the last one stopped. E02 defines those files and gives sessions a small tool to write them and to resume from them:
- **`STATE.md`:** the current phase, track, active task and blockers.
- **One task file per slice:** status, review round and findings.
- **Handoff notes:** context passed between sessions.
- **ADRs and a glossary:** decisions and shared vocabulary that outlive any model.

**Done when:** a second session resumes a task from the files alone.

## Decisions in force

| Topic | Decision |
| --- | --- |
| File format | Markdown, with a **TOML front matter** block between `+++` lines. The front matter holds strict, machine-readable fields, parsed with the standard library's `tomllib`. The body holds prose for people and agents. |
| Tooling | A **standard-library CLI in the kit**, `.factory/state/state.py`. It creates and updates the files, validates them, and prints a resume summary. |
| Validation | `install.py check` and the gate both validate the state files. A malformed file fails the gate, so bad state can't be merged. |
| Glossary and ADRs | `docs/GLOSSARY.md` and `docs/adr/README.md` are **state seeds**: created only when missing and never overwritten (ADR 0003). |

## In scope

- The formats of `STATE.md`, task files and handoff notes.
- `state.py` and its commands.
- Validation in `install.py check` and in the gate.
- The glossary and ADR seeds.
- Dogfooding: this repo tracks its own work in these files.

## Out of scope

- The SQLite job index and crash recovery (E18).
- Review round limits and what happens when they're reached (E14). E02 only records the round.
- Spec, task, ADR and PR templates and their linter (E04).
- The handoff skill, the procedure an agent follows (E10). E02 provides the file and the command.
- Locking for several sessions writing at once (E16 and E18).

## The files

**`.agentic/STATE.md`**

```markdown
+++
phase = "build"            # spec | design | test | build | gate | review | docs | ship | learn
track = "full"             # full | lite | pass-through
active_task = "E02-T1"     # a task id, or "" when idle
blockers = []              # short strings
updated = 2026-11-18T21:30:00Z
+++

Free notes for the next session.
```

**`.agentic/tasks/<id>.md`**, one per slice, where `<id>` is the file name without `.md`:

```markdown
+++
id = "E02-T1"
title = "State file formats and validator"
status = "in-progress"     # todo | in-progress | in-review | blocked | done
review_round = 0           # 0 until the first review
created = 2026-11-18T21:30:00Z
updated = 2026-11-18T21:30:00Z

[[findings]]
id = "F1"
severity = "major"         # blocker | major | minor
status = "open"            # open | fixed | wont-fix
summary = "One line"
+++

## Goal
## Acceptance criteria
## Notes
```

**`.agentic/handoffs/<timestamp>-<task>.md`**, for example `20261118T213000Z-E02-T1.md`:

```markdown
+++
task = "E02-T1"
from = "builder"           # who is handing off
to = ""                    # who should pick it up, or "" for anyone
created = 2026-11-18T21:30:00Z
+++

## Done
## Next
## Open questions
```

## Acceptance criteria

**Formats and validation**

- **AC-01** A state file is valid when:
  - it starts with a `+++` line, followed by TOML, then a closing `+++` line
  - its front matter has exactly the required keys above, of the right types, with values from the listed sets
  - a task's `id` matches its file name
  - a handoff's `task` names an existing task file

  Other keys in the front matter are an error. Nothing is checked in the body except, for task files and handoffs, that the listed `##` headings are present.
- **AC-02** `state.py check [PATH]` validates `STATE.md`, every task file and every handoff. It prints one line per problem, as `<file>: <key or heading>: <problem>`, and exits 1 if there are any problems, else 0. It also checks that `STATE.md`'s `active_task`, when it isn't empty, names an existing task file.
- **AC-03** `install.py check` runs the same validation, and reports problems in the same format beside its config results.
- **AC-04** The gate validates the state files before running any check. If any are invalid, it exits 2, printing the same problem lines and running nothing.
- **AC-05** **Upgrade path:** a repo whose `STATE.md` is still E01's placeholder, the exact old seed text, is treated as "no state yet", which is valid. `state.py init` replaces that placeholder with a valid `STATE.md`. Any other `STATE.md` without front matter is an error that names `state.py init`.

**`state.py` commands** (standard library only, Python 3.11+)

- **AC-06** `state.py init` writes a valid `STATE.md` with:
  - `phase = "spec"`, `track = "full"` and `active_task = ""`
  - no blockers
  - `updated` set to now

  It refuses to overwrite a `STATE.md` with front matter unless `--force` is given.
- **AC-07** `state.py task new <id> "<title>"` creates `tasks/<id>.md` with `status = "todo"`, round 0, no findings and the three headings. It exits 1 if the id already exists or isn't `[A-Za-z0-9._-]+`.
- **AC-08** `state.py task set <id>` takes `--status S` and/or `--round N`. It updates those keys and `updated`, and leaves the body byte-for-byte unchanged. Invalid values exit 2 and change nothing.
- **AC-09** `state.py finding add <id> --severity S "<summary>"` appends a finding with the next free id (`F1`, `F2`…) and status `open`. `state.py finding set <id> <finding-id> --status S` changes a finding's status.
- **AC-10** `state.py start <id>` makes `<id>` the active task:
  - it sets `active_task`, and sets the task's status to `in-progress`
  - `--phase P` and `--track T` set `STATE.md`'s phase and track

  `state.py block "<reason>"` and `state.py unblock [<reason>]` add and remove blockers; `unblock` with no reason removes them all.
- **AC-11** `state.py handoff <task> --from F [--to T]` writes a new handoff file named with the current UTC time. Its body comes from `--body-file FILE`, or from stdin when that's not given, and must contain the three `##` headings. It never overwrites an existing file.
- **AC-12** `state.py resume` prints everything a new session needs, from the files alone:
  - the phase, track and blockers
  - the active task's front matter, open findings and body
  - the newest handoff for that task, in full

  With no active task, it says so and lists the tasks that aren't `done`. `--json` prints the same as JSON.
- **AC-13** Every command that writes:
  - writes atomically, to a temp file followed by a rename
  - keeps LF endings
  - updates `STATE.md`'s `updated` when it touches `STATE.md`
  - leaves the file valid, or changes nothing and exits non-zero

**Seeds**

- **AC-14** The kit's state seeds gain `docs/GLOSSARY.md` and `docs/adr/README.md`, and the `STATE.md` seed becomes a valid file (`state.py init`'s output, with a fixed `updated`):
  - **`GLOSSARY.md`:** a heading, a one-line purpose, and a table of term and meaning, with the factory's own terms filled in: gate, profile, kit, slice, handoff, track, phase.
  - **`docs/adr/README.md`:** the ADR format this repo uses (title, status, context, decision, consequences) and the numbering rule.

  Like all state seeds, they're created only when missing and never overwritten.

**Resume, end to end**

- **AC-15** **A second session resumes from files alone.** In a test, one process:
  1. starts a task
  2. records a finding and bumps the round
  3. writes a handoff
  4. ends

  A fresh process, sharing nothing but the repo, runs `state.py resume`. Its output contains the task id, status, round, the open finding and the handoff's "Next" section.
- **AC-16** **This repo** uses its own state files: `STATE.md` and a task file for each E02 slice, kept current while E02 is built. **Live evidence:** a new Claude Code session, told only "resume from .agentic", reads `state.py resume` and continues the next E02 slice correctly. The PR records this.

**Quality**

- **AC-17** ruff, `ruff format --check` and `mypy --strict` pass. `state.py` stays standard-library only. Every AC above has at least one test tagged `E02-AC-nn`, except the live evidence in AC-16.

## Assumptions (confirmed with approval, 18 Nov 2026)

1. **One writer at a time.** Two sessions editing the same state file at once can lose an update. E16 and E18 add locking.
2. **Times are UTC,** written as TOML offset datetimes ending in `Z`.
3. **Handoffs are never edited or deleted** by `state.py`. They're an append-only log; cleanup is out of scope.
4. **The gate validates state, not workflow.** For example, it doesn't check that a `done` task has no open findings. Workflow rules arrive with E13 and E14.
5. **The phase and track lists follow the blueprint:** spec, design, test, build, gate, review, docs, ship, learn; and full, lite, pass-through.
