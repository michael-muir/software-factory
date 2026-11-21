# E11 · Standards packs design note

Spec: [E11 spec](../specs/E11-standards-packs.md) · Issue: [#11](https://github.com/michael-muir/software-factory/issues/11)
Status: **Proposed, awaiting product owner acceptance** · ADRs: [0033](../adr/0033-standards-packs-are-markdown-rule-tables-read-by-one-standalone-module.md) · [0034](../adr/0034-rule-ids-are-never-reused-and-findings-cite-them-in-a-rule-field.md) · [0035](../adr/0035-which-rules-apply-is-computed-from-globs-markers-and-config.md) · [0036](../adr/0036-kit-seed-files-inside-factory.md) · [0037](../adr/0037-pack-content-is-our-own-words-checked-in-review.md)

## Summary

There are four parts:

1. **One kit module, `.factory/standards/standards.py`,** standard library only, with no kit imports (ADR 0033). It reads and validates packs and the `[standards]` config. It selects the packs and rules in force for a set of files (ADR 0035), and answers "is this rule in force?" for `state.py`. Its CLI is `standards.py check` and `standards.py select [--base-ref REF | FILE ...] [--json]`.
2. **Thirteen packs:** the 12 kit packs, plus the `house` seed that `install.py` creates once and never manages (ADR 0036). Their content follows ADR 0037.
3. **Three small changes to existing modules:**
   - The gate stops with exit 2 on standards problems, before any check runs.
   - `install.py check` reports the same problems, and its config schema gains `[standards]`.
   - `state.py` gains `finding add --rule` and an optional `rule` field, shown by `resume` and `evidence.py` (ADR 0034).
4. **The reviewer:** the `standards-review` skill and the Standards Reviewer card use `select` and `--rule`. The skill's fixture is redone against the real Python pack, and that is the done-when.

## Source layout

```text
kit/.factory/standards/standards.py            # reader, validator, selector, rule_in_force; CLI: check | select
kit/.factory/standards/<pack>/rules.md         # the 12 packs (python ... docs); .gitkeep goes
kit/.factory/standards/house/rules.md          # the house template: a seed file (ADR 0036)
kit/.factory/gates/gate.py                     # + standards_problems(): exit 2 before checks
kit/.factory/state/state.py                    # + finding add --rule, optional findings.rule, resume shows it
kit/.factory/workflow/evidence.py              # + rule in the Findings lines
kit/.factory/skills/standards-review/SKILL.md  # + select, --rule, "no rule, no finding"
kit/.factory/agents/core/standards-reviewer.md # + standards.py in [scope].run
factory_installer/kit.py                       # + SEED_FILES; is_kit_managed excludes them
factory_installer/config_schema.py             # + [standards]: packs (bool table), ignore (rule ids)
factory_installer/cli.py                       # + standards_problems() in run_check
kit/.agentic/config.toml, .agentic/config.toml # + [standards] defaults
.factory/standards/house/rules.md              # this repo's own rules (at least 5)
tests/fixtures/standards/                      # small packs, good and broken, for the validator and selector
tests/fixtures/skills/standards-review/        # redone against the real python pack
tests/test_standards_*.py                      # one file per slice
pyproject.toml                                 # + kit/.factory/standards in mypy_path, files, pythonpath and coverage source
```

## The pack reader and validator (ADR 0033)

- **`read_pack(path) -> Pack | list[Problem]`.**
  - **Front matter:** `+++` lines, read with `tomllib`. Keys: `name`, `title`, `prefix`, `applies_to`, optional `detect` and `replaces`, and `[[sources]]` with `title`, `url` and `licence`. Unknown keys are problems.
  - **Body:** a `# ` heading equal to `title`, a `## Left to the tools` section that isn't empty, and a `## Rules` section with exactly one table.
  - **Rows:** split on unescaped `|`, and `\|` becomes `|`. Each row becomes `Rule(id, severity, text, why, source_url, line)`.
- **`validate(root) -> list[Problem]`** reads every `.factory/standards/*/rules.md` and adds the checks across packs:
  - each prefix is unique
  - each name in `replaces` is a pack, with no cycles
  - each id is unique and in ascending order, with the pack's own prefix
  - each Source URL starts with a source URL from the front matter
  - each kit pack (every pack but `house`) has 15 to 30 rules in force and uses every severity (spec AC-06)

  It also checks `[standards]`: names in `packs` are installed packs, and ids in `ignore` are rules. Problems are sorted by path, then line.

- **`Problem.__str__`** gives `<file>: <where>: <message>`, where `where` is `front matter: <key>`, `line N` or `config: standards.<key>`.
- **Table parsing is strict:** a row with the wrong number of cells, a Source cell that isn't one `[text](https://...)` link, or a second table under `## Rules` is a problem, never a crash.

## Selection (ADR 0035)

- **`select(root, files) -> list[Selected]`,** where `Selected` holds the pack, the files it matched and the rules in force, in name order. A pack is selected when:
  - a file matches its `applies_to` (`fnmatchcase`, POSIX paths)
  - its `detect` globs each match a file at the repo root
  - no selected pack `replaces` it
  - config doesn't switch it off

  Its rules in force exclude `retired` and ignored ids.

- **The file list:**
  - `select FILE ...` uses the files as given.
  - Otherwise, `select` loads the repo's `.factory/gates/gate.py` by path and calls `changed_files(root, base_ref)`, with the ref from `--base-ref` or `gates.base_ref`.
  - No changed files means no packs, and the output says so.
- **Text output:** one block per pack, `<name> (<title>): <n> files`, then `  <id> [<severity>] <rule>` lines. `--json` gives `{"packs": [{"name", "title", "files", "rules": [{"id", "severity", "rule"}]}]}`. Both are deterministic.
- **`rule_in_force(root, rule_id) -> str | None`** returns the reason a rule isn't in force: unknown, retired, ignored, or its pack switched off. It returns None when the rule is in force. `state.py` uses it.

## The house seed (ADR 0036)

- `factory_installer/kit.py` gains `SEED_FILES = frozenset({".factory/standards/house/rules.md"})`. `Kit.is_kit_managed` returns False for them.
- `plan()` already treats paths that aren't kit-managed as seeds: created when missing, skipped or unchanged otherwise, and never in the manifest. So `plan.py` needs no change.
- The template is a valid pack with `prefix = "HOUSE"`, `applies_to = ["*"]`, one source (the repo itself, pointing to `docs/`), and a single example row `HOUSE-001` marked `retired`. `validate` exempts `house` from the 15–30 count and the every-severity rule.

## Config

`config_schema.py` gains a field kind for a table of string to bool, and a check for rule ids:

```toml
[standards]
packs = {}  # pack name = true | false; empty = every pack on
ignore = []  # rule ids switched off in this repo, e.g. ["PY-007"]
```

`toml_value` renders an empty dict as `{}`. The schema checks only types and the id pattern. Existence is checked by `standards.validate`, which `install.py check` also runs.

## Gate and install

- **The gate:** `standards_problems(root)` loads `.factory/standards/standards.py` like `docs.py` and calls `validate`. It runs after `agent_problems`. Any problem raises `GateError("invalid standards packs (python .factory/standards/standards.py check): ...")`, so the gate exits 2 and no check runs. A kit without the module skips it. The gate report doesn't change.
- **`install.py check`:** `standards_problems(repo, kit_root)` runs with the kit's module, as `state_problems` does, and its lines are added to the problems.

## Findings (ADR 0034)

- **`state.py`:** `FINDING_SCHEMA` gains `rule`, checked against `^[A-Z]{2,5}-\d{3}$`, and `check_fields` is called with `optional={"rule"}`. The writer puts `rule` after `severity`, only when it's present.
- **`finding add --rule ID`:**
  1. Loads `<root>/.factory/standards/standards.py`. If it's missing, the command refuses: "no standards packs installed".
  2. Calls `rule_in_force`. A reason means `Refused` and exit 1, with the task file untouched.
  3. Otherwise it appends the finding as today, plus `rule`.
- **`resume`** prints `F1 [minor] PY-002 <summary>`. **`evidence.py`** prints `- F1 [minor] (open) PY-002 <summary>`. Without a rule, both lines are byte for byte as before, so E08's locked tests still hold.

## The reviewer

- **`standards-review` SKILL.md:** step 1 runs `python .factory/standards/standards.py select --base-ref <base>`, and reads only those rules. Step 4 becomes `state.py finding add <task> --severity <s> --rule <id> "<file>:<line> ..."`. The skill takes the rule's severity unless the summary says why not. It keeps the phrases E10's locked test checks: `state.py finding add`, `.factory/standards/`, "rule id", and blocker/major/minor.
- **The card:** `[scope].run` adds the four `standards.py` command forms, and Does gains "list the rules in force with `standards.py select`". `build.py` regenerates the three tools' files.
- **Fixture:** `tests/fixtures/skills/standards-review/`:
  - `before/.factory/standards/python/rules.md` becomes a byte copy of the kit's `python` pack, and `before/.factory/standards/standards.py` a copy of the kit module.
  - `greet.py`'s two breaks map to the pack's docstring rule and its rule against naming a thing for its type.
  - `after/.agentic/tasks/E01-T1.md` gains `rule` on both findings.
  - `RUN.md` cites the real ids.

## Test seams

- **Reader and validator, in-process:** `standards.validate(tmp_root)` on packs built in temp dirs from `tests/fixtures/standards/good/` plus one change each. Each problem in AC-01 to AC-04 has one test that checks the message's file and `where`. The CLI is tested through `standards.main([...])` (exit 0/1) and once through a subprocess.
- **The kit packs:** parametrised over the 12 kit packs. Each test pins:
  - the spec's table (name, prefix, globs, sources)
  - `unreal`'s `detect`/`replaces`, and `tests`/`docs`' `["*"]`
  - the count and severities

  Every pack passes `validate`.

- **Selection:**
  - `select(root, files)` with a fixture repo holding packs with globs, detect and replaces, and config with `packs` and `ignore`
  - `--base-ref` in a temp git repo with a commit, an uncommitted edit and an untracked file
  - the JSON output, compared exactly
- **Config:** `config_schema.validate` for type errors, and `install.py check` for unknown pack names and ids. `render_default()` equals the kit's `config.toml`.
- **Seed:** `plan()` with a kit that holds the seed:
  - it's created when missing and skipped when present
  - it's never in `manifest_files`
  - an upgrade with an edited house pack leaves it byte-identical
  - an edited kit pack is kept on upgrade (E01)
- **Gate:** a temp repo with a broken pack exits 2 with no checks run. A repo without `standards.py` runs as before.
- **Findings:**
  - `state.main(["finding", "add", ...])` refuses each of unknown, retired, ignored and switched-off, with exit 1 and the task file byte-unchanged
  - success writes `rule`
  - `state.validate` accepts a finding with or without `rule`, and flags `rule = "py-2"`
  - `resume`'s and `evidence.draft`'s lines are checked
- **Reviewer and done-when:**
  - skill text checks, and `agents.py check`, `build.py --check` and `docs.py check` stay clean
  - the fixture test checks every new finding's `rule` with `rule_in_force` against the kit's pack, that its `file:line` is in `git diff --no-index before after`, and that the after repo passes `state.validate` and `standards.validate`

## Vertical slices

| Task | Slice                                                                                                                                               | ACs                            |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------ |
| T1   | `standards.py` reader and validator with `check`; the `[standards]` config; the house seed and `SEED_FILES`; the gate and `install.py check` run it | AC-01 to AC-04, AC-09 to AC-11 |
| T2   | The 12 kit packs, written to ADR 0037, and the `.gitkeep` removed                                                                                   | AC-05, AC-06                   |
| T3   | `select` and `rule_in_force`; `finding add --rule` and the `rule` field; `resume` and `evidence.py`; the skill and card, with tool files rebuilt    | AC-07, AC-08, AC-12 to AC-14   |
| T4   | Done-when: the redone fixture and its test; dogfooding (install, this repo's house pack, `[standards]`); E11 AC coverage                            | AC-15 to AC-17                 |

Order: T1, then T2 and T3 (independent: T3's tests use fixture packs), then T4.

## Risks

- **AC-14 needs one relock (product owner approval).** `tests/test_core_roles_prove.py`, locked by E09-T2, pins every limited reviewer's `[scope].run` to exactly the gate and `state.py` commands (`REVIEWER_LIMIT`). Adding `standards.py` to the Standards Reviewer's scope fails it. The proposed change is a `standards-reviewer` entry that also allows the four `standards.py` forms. T3 will stop and report it before relocking. The other option is to leave the card's scope alone and give `select` to the reviewer through `state.py`, which would change AC-14.
- **E10-T3's locked test stays green** (spec assumption 8). It reads whatever pack is in the fixture's "before" repo and checks phrases the new skill keeps. T3 and T4 run it before they push.
- **Pack writing is the bulk of the work:** 12 packs of 15 to 30 rules each, about 250 rules. T2's PR will be large but all Markdown, with the shape checked by tests and the content by review (ADR 0037). If review finds it too large, T2 can split into T2a (Python, TS, JS, shell, tests, docs) and T2b (the six E30 stacks), both under AC-05/AC-06's tests.
- **Mutation on `standards.py`:** the dogfood gate mutates changed lines, at most 100 sampled mutants. The validator has many small branches, so each problem gets its own test in T1 to keep the score above 60%.
- **Shared files with parallel epics:** `tests/_repo.py` (KIT_FILES, STATE_FILES), `factory_installer/config_schema.py`, `.agentic/config.toml`, `.factory/manifest.json` and the generated tool files. Edits stay minimal, and the orchestrator resolves conflicts on merge.
- **Licences:** a source's licence can be misread. Each pack's front matter records it, and T2's PR lists each source with the licence it was checked against.
