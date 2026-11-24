+++
name = "house"
title = "House rules"
prefix = "HOUSE"
applies_to = ["*"]

[[sources]]
title = "Software Factory: house packs (ADR 0036)"
url = "https://github.com/michael-muir/software-factory/blob/main/docs/adr/"
licence = "Apache-2.0"

[[sources]]
title = "Software Factory: skills and specs"
url = "https://github.com/michael-muir/software-factory/blob/main/"
licence = "Apache-2.0"
+++

# House rules

The Software Factory repo's own rules, beside the kit's packs. The kit created this file once and
never changes it. Add a row for each rule, with the next free `HOUSE-NNN` id. A rule you drop stays in the
table as `retired`, so its id is never reused. Add a `[[sources]]` table for each page your
rules link to. Check the pack with `python .factory/standards/standards.py check`.

## Left to the tools

The gate's format and lint checks enforce everything the repo's formatter and linter cover.
Don't repeat those rules here.

## Rules

| Rule id   | Severity | Rule                                                                                                                                                             | Why/example                                                                                       | Source                                                                                                                                  |
| --------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| HOUSE-001 | retired  | Example: replace this row with your first rule.                                                                                                                  | A retired row is never cited, and keeps its id.                                                   | [ADR 0036](https://github.com/michael-muir/software-factory/blob/main/docs/adr/0036-kit-seed-files-inside-factory.md)                   |
| HOUSE-002 | blocker  | Never change a locked test without the product owner's approval. A relock lists every file in the task's lock record, and only the approved file's hash changes. | `lock --replace` rewrites the record with only the files given, so a short list unlocks the rest. | [ADR 0018](https://github.com/michael-muir/software-factory/blob/main/docs/adr/0018-test-locks-are-hash-records-checked-by-the-gate.md) |
| HOUSE-003 | major    | Kit code under `kit/.factory/` imports only the standard library.                                                                                                | The kit runs in repos that install nothing else.                                                  | [ADR 0007](https://github.com/michael-muir/software-factory/blob/main/docs/adr/0007-gate-is-one-stdlib-file-in-the-kit.md)              |
| HOUSE-004 | major    | A change to `kit/` reruns `install.py .` and commits its output, generated tool files included, in the same PR.                                                  | This repo dogfoods the kit, and the gate fails on stale tool files.                               | [ADR 0002](https://github.com/michael-muir/software-factory/blob/main/docs/adr/0002-installer-runs-from-clone-stdlib-only.md)           |
| HOUSE-005 | major    | Every test is tagged `@pytest.mark.ac("<EPIC>-AC-nn")` with an AC its epic's spec defines, and tests are locked before the implementation commit.                | The PR body traces each AC to its tests.                                                          | [tdd-slices](https://github.com/michael-muir/software-factory/blob/main/.factory/skills/tdd-slices/SKILL.md)                            |
| HOUSE-006 | minor    | Tests that read a subprocess's output decode it with `encoding="utf-8"`, never the locale's encoding.                                                            | CI runs on Windows, whose default code page breaks on non-ASCII output.                           | [lock-tests](https://github.com/michael-muir/software-factory/blob/main/.factory/skills/lock-tests/SKILL.md)                            |
| HOUSE-007 | minor    | Code that runs on Windows uses no POSIX-only names (`signal.SIGKILL`, `os.getuid`); check with `mypy --platform win32`.                                          | The gate's types check runs on Linux and doesn't see them.                                        | [ADR 0007](https://github.com/michael-muir/software-factory/blob/main/docs/adr/0007-gate-is-one-stdlib-file-in-the-kit.md)              |
