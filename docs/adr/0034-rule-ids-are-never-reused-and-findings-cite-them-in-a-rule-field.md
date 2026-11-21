# 0034 · Rule ids are never reused, and findings cite them in a `rule` field checked when written

Status: Proposed · Date: 2026-11-21 · Epic: E11

## Context

E11's done-when is "the Standards Reviewer cites pack rules by id". E10's fixture showed the citation only as text inside a finding's summary, which nothing checks. The PO chose `state.py finding add --rule <id>`, which refuses an id that isn't in force. Two things need deciding:

- **What an id means over time.** Packs change between kit versions, and repos switch rules off. A finding recorded last month must still read the same.
- **When a citation is checked.** It could be checked on write only, or again whenever the state files are validated.

## Decision

- **Ids:** `<prefix>-NNN`, where the prefix is 2 to 5 capital letters unique to the pack, and NNN is three digits. A rule taken out of force stays in its table with severity `retired`, so its id is never given to another rule. Rows go in ascending id order, and new rules take the next number.
- **Findings gain an optional `rule` field,** written after `severity`. The summary still carries `<file>:<line>` and the reason (E10).
- **The rule is checked once, when it's written.** `finding add --rule` asks `standards.py` whether the rule is in force: installed, not retired, not ignored, and its pack not switched off. If not, it refuses with exit 1 and leaves the task file unchanged.
- **After that, only the format is checked.** `state.py check` and the gate validate `rule` against the id pattern, not against the packs. An old finding stays valid after its rule is retired.
- **Readers show the rule beside the severity:** `resume` as `F1 [minor] PY-002 <summary>`, and `evidence.py` as `- F1 [minor] (open) PY-002 <summary>`. A finding without a rule prints exactly as before.

## Consequences

- A citation can't be misspelt or invented. The skill requires `--rule`, so every standards finding is linked to a real rule.
- Retiring a rule never invalidates a task file, and an id seen in an old PR always means the same rule.
- The other reviewers' findings (spec, security, performance, adversary) don't change. They may leave `rule` out.
- A pack can't renumber its rules. Fixing a typo in a rule keeps its id; changing what a rule means needs a new id and retires the old one.
