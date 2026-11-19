# E10 · Skills library (16) design note

Spec: [E10 spec](../specs/E10-skills-library.md) · Issue: [#10](https://github.com/michael-muir/software-factory/issues/10)
Status: **Accepted by the product owner, 19 Nov 2026** · ADRs: [0022](../adr/0022-skills-are-validated-by-agents-py-with-a-yaml-subset.md)

## Summary

There are three parts:
1. **Skill validation joins `agents.py`** (ADR 0022). `agents.validate(root)` already feeds the gate (exit 2) and `install.py check`, so adding skill problems to it covers spec AC-03, with no change to either. `agents.py check` is the CLI. A small reader parses the YAML subset the spec allows.
2. **The 16 skills** are kit data in `kit/.factory/skills/<name>/SKILL.md`. As with the core roles (ADR 0021), the factory's own conventions are pinned by tests on the kit's files, not by the validator: the sections, `Used by:`, the commands each skill relies on, and the links to role cards.
3. **The exercise record** is a test that holds a table: each skill, and how it was exercised. The live ones name their commits. The fixture ones each have a folder of before-and-after state, checked by the factory's tools.

## Source layout

```text
kit/.factory/agents/agents.py            # + SKILLS_REL, read_yaml_front(), skill problems in validate()
kit/.factory/agents/_schema.md           # unchanged (roles only)
kit/.factory/skills/<name>/SKILL.md      # 16 skills; .factory/skills/.gitkeep goes
kit/.factory/agents/core/*.md            # skill: lines for handoff, resume-from-state and the new skills
.factory/...                             # this repo's own install (AC-09)
tests/test_skills_format.py              # T1: the validator (AC-02, AC-03)
tests/test_skills_flow.py                # T1: the five workflow skills
tests/test_skills_make.py                # T2: six Specify, Make and Deliver skills, and their fixture runs
tests/test_skills_prove.py               # T3: five review skills, their fixture runs, the record, the whole set
tests/fixtures/skills/<name>/            # fixture runs (AC-07): before/, after/ and RUN.md
```

**The YAML subset** (ADR 0022):
- The front matter is the lines between the first `---` line and the next one.
- Each top-level line is `key: value`. A value is plain, or a single- or double-quoted string, with the usual escapes for double quotes.
- `metadata:` with no value opens a map of indented `key: value` lines, one level deep.
- Comments (`# ...` lines) and blank lines are skipped.
- Anything else is reported as `<file>: front matter: unsupported YAML on line N`: lists, flow syntax, block scalars (`|`, `>`), anchors and tabs.

**Skill problems** follow the spec's AC-02 rules, field by field. Every `SKILL.md` under `.factory/skills/*/` is checked. Other files there, such as `scripts/` or `references/`, are allowed and not checked.

## The slices' skills

| Task | Skills                                                                                                       | Exercised                                                                              |
| ---- | ------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------- |
| T1   | `tdd-slices`, `lock-tests`, `handoff`, `resume-from-state`, `verify-with-evidence`                           | Live, while T2 and T3 are built: each slice resumes, locks, hands off and runs the gate |
| T2   | `spec-interview`, `design-note`, `debugging`, `dependency-bump`, `retro`, `release`                          | Fixture runs                                                                           |
| T3   | `spec-review`, `standards-review`, `threat-check`, `perf-budget`, `adversarial-testing`                      | Fixture runs                                                                           |

The workflow skills come first, so the later slices can use them live.

## Test seams

- **Validator:** `agents.validate` on `tmp_path` repos holding `SKILL.md` files, with one test per AC-02 rule. Unsupported YAML is reported, never raised. The gate (exit 2, nothing run) and `install.py check` use the E03 fixtures.
- **Conventions (AC-04 to AC-06):** the tests read each kit `SKILL.md`, split the front matter with the same reader, and check:
  - the three headings
  - a numbered `## Steps` list
  - a `## Done when` list
  - `Used by:`, with roles that exist and whose cards name the skill
  - "Use when" in the description
  - under 500 lines
  - the commands each skill must name, as phrases
- **Fixture runs (AC-07):** `tests/fixtures/skills/<name>/` holds:
  - `before/`: a minimal repo, with just the files the skill reads
  - `after/`: the same repo after one run of the skill
  - `RUN.md`: which step produced which change

  The test copies `after/` into a temp git repo with the kit installed, then runs `state.py check`, `agents.py check` and `docs.py check` as they apply. Then it checks the skill's own done-when, for example:
  - `threat-check`: a finding with a severity, in the task file
  - `release`: a dated version section, and an empty "Unreleased"
- **Exercise record:** `EXERCISED = {skill: ("live", "<commit>, <commit>") | ("fixture", "")}` in `tests/test_skills_prove.py`. A test checks the keys are the 16 skills, and that every fixture entry has its folder.

## Vertical slices

| Task | Slice                                                                                                                                         | ACs                                                                   |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| T1   | Skill validation in `agents.py`; the five workflow skills; `skill:` lines for them in the cards                                               | AC-02, AC-03; AC-04 and AC-06 for these skills                        |
| T2   | Six Specify, Make and Deliver skills, and a fixture run for each; their `skill:` lines                                                        | AC-04, AC-06 and AC-07 for these skills                               |
| T3   | Five review skills, and a fixture run for each; the exercise record; exactly 16; every card linked; install and upgrade; dogfooding; coverage | AC-01, AC-05, AC-07 (the record), AC-08 to AC-10; AC-04 and AC-06 for these |

## Risks

- **The YAML subset may reject a skill written elsewhere,** for example one with a block-scalar description. That's deliberate: a clear "unsupported" beats parsing it wrongly. A later epic can widen the reader if real skills need it.
- **Fixture runs are written by the person who wrote the skill.** They prove the steps can be followed and give checkable results, not that the skill is the best possible. E13's first full-track run is the stronger test.
- **Changing the cards touches E09's locked tests' subjects,** but not the tests themselves. Adding `skill:` lines under `## Inputs` keeps every E09 assertion true. If one isn't, that's a sign to stop, not to relock.
- **`agents.py` grows by about 150 lines,** and mutation testing scores only the changed lines, as before.
