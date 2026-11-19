# 0021 · Core roles are kit data, pinned by tests rather than by new validator rules

Status: Accepted · Date: 2026-11-19 · Epic: E09

## Context

E09 adds 16 role files and conventions on top of the E03 format:
- a `## Hand-off` heading
- `Does:` and `Must not:` lists
- one reviewer run limit, shared by five roles
- fixed summaries
- particular must-not rules

There are two places those conventions could be enforced:
1. **In `agents.py`,** as new schema rules. These would apply to every role in every repo, including a repo's own roles and E29's domain experts.
2. **In tests on the kit's own files.** These pin what the factory ships, and leave the E03 format as it is.

E03's format is deliberately small: keys, tools, scopes, a hint and three headings. Domain experts (E29) must be addable "from the template alone", and repos may tighten or rewrite roles. The E03 format also has no includes, so the shared reviewer limit has to be written out five times.

## Decision

- **The conventions are tests, not validator rules.** Tests on `kit/.factory/agents/core/*.md` pin:
  - the spec's role table: tools, run limits, hints and summaries
  - the card layout
  - the hand-off names
  - the AC-07 must-not rules

  `agents.py`, `_schema.md` and `_template.md` don't change.
- **The reviewer limit is repeated** in the five cards, and a test keeps the five lists identical, and equal to the spec's prefixes. There's no include mechanism.
- **Core roles are ordinary kit files.** They're installed, recorded in the manifest, and kept on upgrade when a repo has edited them (ADR 0005).
- **The E03 validator still applies to every role,** core or not. A repo's edited core role must still pass `agents.py check`.

## Consequences

- The E03 format stays the single contract for roles. E29's domain experts and a repo's own roles need nothing beyond it.
- A repo can adapt a core card, for example adding `poetry run python` to the reviewer limit, without failing any check. Only the kit's copies are pinned.
- Changing a reviewer limit means changing five files together, and the test catches a partial change.
- If the card conventions later need to bind every repo, a new ADR can move them into `agents.py`.
