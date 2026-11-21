# E11 · Standards packs (12) — Spec

Issue: [#11](https://github.com/michael-muir/software-factory/issues/11) · Milestone: M1 · Manual factory (alpha) · Depends on: E06 (done)
Status: **Draft, awaiting product owner approval** · Next: Architect design note and ADRs, then failing tests per AC

## Goal

The Standards Reviewer (E09) and its `standards-review` skill (E10) already check a diff against "the house standards pack" and cite each rule by its id. But the kit's `.factory/standards/` folder is empty, and nothing checks that a cited id is real. E11 fills the folder and makes the citation checkable:

- **12 standards packs** in `.factory/standards/<pack>/rules.md`. Nine cover the stacks the gate profiles cover now or will in E30. Three are shared: shell, tests and docs. Each pack holds 15–30 rules that a reviewer has to judge, in our own words, each with an id, a severity and a link to its source.
- **A standard-library validator and selector**, `.factory/standards/standards.py`. It checks the packs and the repo's `[standards]` config, and lists the rules that apply to a change. The gate and `install.py check` run it.
- **A repo-owned `house` pack** for local rules, which the kit never overwrites. This repo dogfoods it.
- **`state.py finding add --rule <id>`**, which refuses an id that doesn't name a rule in force. The `standards-review` skill requires it.

**Done when:** the Standards Reviewer cites pack rules by id (PRD).

## Decisions in force (product owner, 21 Nov 2026)

| Topic           | Decision                                                                                                                                                                                                                                                                                                                                                                                               |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| The 12 packs    | **9 stacks plus 3 shared.** Stacks: Python (PEP 8 and PEP 257, plus typing), TypeScript (Google TS), JavaScript (Google JS), C++ (Google C++), Go (Uber Go), Rust (Rust API Guidelines), C#/.NET (StyleCop plus the .NET design guidelines), Lua (Olivine-Labs), Unreal C++ (Epic's coding standard). Shared: Shell (Google Shell), Tests (cross-language), Docs (Markdown, ADRs and commit messages). |
| Format          | **`.factory/standards/<pack>/rules.md`.** TOML front matter (name, title, rule-id prefix, sources with URLs and licences, file globs), then a table: Rule id, Severity, Rule, Why/example, Source. Ids look like `PY-001`: a prefix unique to the pack and three digits, never reused. A standard-library validator runs in the gate and in `install.py check`.                                        |
| Depth           | **15–30 judgement rules per pack.** No rule that the stack's formatter or linter already enforces. One line points to the gate's format and lint checks for those.                                                                                                                                                                                                                                     |
| Selection       | **By file globs, with Tests and Docs always on.** `.agentic/config.toml` gets a `[standards]` table: `packs` (each pack on or off) and `ignore` (rule ids switched off). A repo-owned `house` pack is never overwritten by the kit, and this repo dogfoods it.                                                                                                                                         |
| Done-when proof | **`state.py finding add --rule <id>`.** The id must name a rule in an installed pack, or the command exits 1. The `standards-review` skill requires `--rule`. The skill's fixture is redone against the real Python pack. This is a small change to `state.py` and E02's findings schema.                                                                                                              |
| Licences        | **Every rule in our own words**, with a link to its source section. The front matter names each source and its licence. No copied text.                                                                                                                                                                                                                                                                |

## In scope

- The 12 packs as kit files, each with its front matter, rule table and pointer to the gate's tools.
- `standards.py`: `check` (validate the packs and `[standards]`), and `select` (the packs and rules in force for a set of files).
- Running the validator in the gate (before any check, like the skills validator) and in `install.py check`.
- The `[standards]` config table: its v1 defaults in the kit's `config.toml`, and its validation.
- The `house` pack: created once by `install.py`, never overwritten or tracked as a kit file.
- `state.py`: `finding add --rule`, the optional `rule` field in the findings schema, and the rule shown by `resume`. `evidence.py` shows the rule in the PR body's findings.
- The `standards-review` skill and the Standards Reviewer card, updated to use `select` and `--rule`.
- The skill's fixture, redone against the real Python pack.
- Dogfooding: this repo installs the packs, writes its own `house` pack, and sets `[standards]`.

## Out of scope

- Gate checks that enforce pack rules. Pass or fail stays with `gate.py` and the profiles' tools ("gates are code"). Packs are for the reviewer's judgement.
- Linter or formatter configs per stack, and the remaining gate profiles (E30). A pack can ship before its stack's profile does.
- Proposing new rules from recurring findings (E28, the retro loop). E11 only makes packs easy to add to.
- Copying packs into each tool's folder (E12 needs no change). The reviewer reads `.factory/standards/` directly.
- Running the reviewer automatically (E13), and the review loop (E14).
- Packs for other languages (Java, Kotlin, Swift, SQL and so on), and publishing packs as plugins.
- Severity levels beyond blocker, major and minor.

## The packs

| Pack         | Prefix  | Applies to                                               | Main sources                                                               |
| ------------ | ------- | -------------------------------------------------------- | -------------------------------------------------------------------------- |
| `python`     | `PY`    | `*.py`, `*.pyi`                                          | PEP 8, PEP 257, the typing docs                                            |
| `typescript` | `TS`    | `*.ts`, `*.tsx`, `*.mts`, `*.cts`                        | Google TypeScript Style Guide                                              |
| `javascript` | `JS`    | `*.js`, `*.jsx`, `*.mjs`, `*.cjs`                        | Google JavaScript Style Guide                                              |
| `cpp`        | `CPP`   | `*.cc`, `*.cpp`, `*.cxx`, `*.h`, `*.hh`, `*.hpp`         | Google C++ Style Guide                                                     |
| `go`         | `GO`    | `*.go`                                                   | Uber Go Style Guide                                                        |
| `rust`       | `RS`    | `*.rs`                                                   | Rust API Guidelines                                                        |
| `csharp`     | `CS`    | `*.cs`                                                   | StyleCop Analyzers rules, .NET framework design guidelines                 |
| `lua`        | `LUA`   | `*.lua`                                                  | Olivine-Labs Lua style guide                                               |
| `unreal`     | `UE`    | the C++ globs, in a repo with a `*.uproject` at its root | Epic's Unreal Engine coding standard                                       |
| `shell`      | `SH`    | `*.sh`, `*.bash`                                         | Google Shell Style Guide                                                   |
| `tests`      | `TST`   | every change                                             | Our own, citing the sources it draws on                                    |
| `docs`       | `DOC`   | every change                                             | Our own, citing the sources it draws on (for example Conventional Commits) |
| `house`      | `HOUSE` | set by the repo                                          | The repo's own rules                                                       |

## Acceptance criteria

**The pack format**

- **AC-01** A pack is `.factory/standards/<name>/rules.md`, starting with TOML front matter between `+++` lines. It has:
  - `name`, which matches the folder
  - `title`
  - `prefix`: 2 to 5 capital letters, unique among the installed packs
  - `applies_to`: a non-empty list of globs, matched against repo-relative paths as the gate matches `mutation_paths`
  - optionally `detect`: markers at the repo root, as in a gate profile, without which the pack doesn't apply
  - optionally `replaces`: names of packs it switches off when it applies
  - `[[sources]]`: at least one, each with `title`, `url` (`https://`) and `licence`
- **AC-02** After the front matter, the body has:
  - a `# <title>` heading
  - a `## Left to the tools` section, which names the gate's format and lint checks as the home of every rule they enforce
  - a `## Rules` section with one Markdown table whose header is exactly `| Rule id | Severity | Rule | Why/example | Source |`
- **AC-03** Each table row:
  - has an id of the form `<prefix>-NNN`, using the pack's own prefix, unique within the pack, with the rows in ascending id order
  - has a severity of `blocker`, `major`, `minor` or `retired`
  - has non-empty Rule and Why/example cells
  - has a Source cell that is a Markdown link whose URL starts with the URL of one of the pack's sources

  A rule that is no longer in force stays in the table as `retired`, so its id is never reused.

- **AC-04** `python .factory/standards/standards.py check` validates every installed pack and the `[standards]` config table (AC-09). Problems are reported as `<file>: <where>: <problem>`, and the command exits 0 when clean and 1 on problems. Front matter or a table it can't read is a problem, not a crash.

**The 12 packs**

- **AC-05** The kit ships exactly the 12 packs in the table above, with the names, prefixes, `applies_to` globs and sources it gives. The `unreal` pack has `detect = ["*.uproject"]` and `replaces = ["cpp"]`. The `tests` and `docs` packs apply to every path (`applies_to = ["*"]`). The kit's `.factory/standards/.gitkeep` goes.
- **AC-06** Each kit pack:
  - passes `standards.py check`
  - has 15 to 30 rules that aren't `retired`
  - has at least one rule of each severity, blocker, major and minor

  Rules are written in our own words, with no text copied from a source. The front matter records each source's licence.

**Choosing the rules for a change**

- **AC-07** `standards.py select [--base-ref REF | FILE ...]` lists the packs that apply to the given files, or to the files changed since the merge base of `REF` (default: `gates.base_ref`) and HEAD, uncommitted changes included. For each pack it shows the files it matched and the rules in force (id, severity, rule). `--json` gives the same as JSON. The output is deterministic.
- **AC-08** A pack applies when:
  - one of the files matches its `applies_to`
  - its `detect` markers, if it has any, are present
  - no pack that applies `replaces` it
  - `[standards].packs` doesn't switch it off

  `tests` and `docs` apply to every change unless switched off. Rules that are `retired` or listed in `[standards].ignore` aren't in force.

- **AC-09** `.agentic/config.toml` gains a `[standards]` table:
  - `packs`: a table of pack name to `true` or `false`, default `{}` (all packs on)
  - `ignore`: a list of rule ids, default `[]`

  A name in `packs` that isn't an installed pack, or an id in `ignore` that isn't a rule, is a problem for `standards.py check` and `install.py check`. A config without the table uses the defaults, so an upgraded repo needs no edit (E01).

**The house pack**

- **AC-10** `install.py` creates `.factory/standards/house/rules.md` when it is missing. The file is a valid pack with prefix `HOUSE` and no rules yet, apart from one example row marked `retired`. Install and upgrade never overwrite or delete it, and it isn't a kit file in the manifest. The house pack is exempt from AC-06's rule count.

**Running the validator**

- **AC-11** The gate runs the standards validator before any check, as it runs the skills validator. Problems stop the gate with exit 2, naming each problem, and no check runs. `install.py check` reports the same problems. A kit without `standards.py` skips both.

**Citing rules in findings**

- **AC-12** `state.py finding add <task> --severity <s> --rule <id> "<summary>"` stores `rule = "<id>"` on the new finding. It refuses (exit 1, naming the id and the reason, and leaving the task file unchanged) when the id:
  - isn't a rule in an installed pack
  - is `retired`
  - is in `[standards].ignore`
  - belongs to a pack switched off in `[standards].packs`

  Without `--rule`, `finding add` works as before.

- **AC-13** E02's findings schema gains an optional `rule`, a string of the form `<prefix>-NNN`. `state.py check` and the gate accept a finding with or without it, and report a malformed one as a problem. `state.py resume` shows the rule beside the severity, and `evidence.py` shows it in the PR body's findings.

**The reviewer**

- **AC-14** The `standards-review` skill:
  - tells the reviewer to run `standards.py select` to find the rules in force
  - requires `--rule <id>` on every finding it records
  - says what to do with something no rule covers: it isn't a finding

  The Standards Reviewer card's run scope includes `standards.py`. Both still pass E09's and E10's checks, and the generated tool files are rebuilt (E12).

- **AC-15** **Done-when:** the `standards-review` fixture is redone against the kit's real `python` pack. Its "before" repo installs the pack, and its "after" task file has findings that each carry a `rule` field. A test checks that:
  - every finding the session added names a rule that is in force in the shipped `python` pack
  - each finding's `file:line` is in the fixture's diff
  - `state.py check` and `standards.py check` pass on the "after" repo

**Installing and dogfooding**

- **AC-16** The packs and `standards.py` are kit files: `install.py` installs them, `install.py check` passes, and a repo's edit to a kit pack is kept on upgrade (E01). This repo installs them, has a `house` pack with its own conventions (at least 5 rules), and its gate validates every pack.
- **AC-17** ruff, `ruff format --check` and `mypy --strict` pass. `standards.py` uses only the standard library. The kit layout tests list the new kit files. Every AC above has at least one test tagged `E11-AC-nn`.

## Assumptions (to confirm with approval)

1. **The tool is `.factory/standards/standards.py`**, beside the packs it reads, with `check` and `select` commands. `state.py` and the gate load it by path, as the gate loads `state.py` and `agents.py`, so each still works when it is missing.
2. **Front matter is TOML between `+++` lines**, as in the role cards (E03) and state files (ADR 0014). It is read with `tomllib`. The rule table is plain Markdown, so agents and people read the same file.
3. **The house pack lives at `.factory/standards/house/rules.md`**, so the reviewer finds every pack in one folder. It is written once from a kit template, like the state files, and never tracked in the manifest. Its prefix is `HOUSE`.
4. **The `unreal` pack replaces `cpp`** in a repo with a `*.uproject` at its root, because the two guides disagree (on naming prefixes and exceptions, for example). An Unreal repo that would rather follow Google C++ switches `unreal` off in `[standards].packs`.
5. **Retired rules stay in the table** with severity `retired`, so an id is never reused. The validator checks uniqueness within a pack and ascending order. It doesn't compare against earlier kit versions.
6. **"No rule the formatter or linter enforces" and "our own words" are checked in review**, not by a test. Tests can't see the source guides, and what a linter enforces depends on its config. The PR for each batch of packs says how this was checked.
7. **The rule's file and line stay in the finding's summary** (`<file>:<line> <what is wrong>`), as E10's skill already says. Only the rule id gets its own field.
8. **The locked E10-T3 test (`tests/test_skills_prove.py`) needs no relock.** It reads whatever pack the fixture's "before" repo holds, and checks the skill for `state.py finding add`, `.factory/standards/` and "rule id", which the updated skill keeps. The redone fixture still passes it.
9. **Slices,** for the design note to confirm: the format, validator, config and house pack, then the packs in batches, then `--rule` and the reviewer, then the done-when fixture and dogfooding.
