# 0033 · Standards packs are Markdown rule tables with TOML front matter, read by one standalone module

Status: Proposed · Date: 2026-11-21 · Epic: E11

## Context

The Standards Reviewer reads a pack to judge a diff. The gate, `install.py check` and `state.py finding add --rule` all need to read the same packs as data. The PO chose Markdown with TOML front matter and a fixed table (E11 spec), so agents and people read the same file. Three questions were left open:

1. **Where the reader lives.** `agents.py` and `docs.py` build on `state.py`, but `state.py` now needs to read packs too (`--rule`). If the reader imports `state.py` while `state.py` loads the reader, the two modules import each other.
2. **How strict the table reader is.** Markdown tables have many dialects, and a forgiving reader can quietly misread a rule.
3. **Who checks the packs, and when.** A broken pack could fail the gate's verdict, like doc problems (ADR 0020), or stop the gate before it runs, like agent files.

## Decision

- **One kit module, `.factory/standards/standards.py`,** standard library only, sitting next to the packs. It holds the pack reader, the validator, the selector (ADR 0035) and a CLI with `check` and `select`. It imports nothing from the kit. Its few lines of `+++` TOML front matter reading and its own `Problem(path, where, message)` copy `state.py`'s shapes, so the messages read the same (`<file>: <where>: <problem>`).
- **The table is read strictly.** These rules apply:
  - The `## Rules` section holds exactly one table, and its header is exactly `| Rule id | Severity | Rule | Why/example | Source |`.
  - Every row has five cells. `\|` is a literal pipe inside a cell.
  - The Source cell is one Markdown link.
  - Anything else is a problem that names the line. It never crashes, and a row is never guessed at.
- **Callers load it by path:** the gate, `install.py check` (the kit's copy, as for `state.py`) and `state.py` (the repo's copy, for `--rule`). When it's missing, they skip it, so an older kit still works.
- **Problems stop the gate with exit 2** before any check runs, as agent and skill problems do. A pack is configuration of the review, like a role card, not a document of the change.

## Consequences

- One reader means the reviewer, the gate and `--rule` can't disagree about what a pack says.
- With no import cycle, `state.py` can load `standards.py` only when it needs it, and `state.py` works without packs.
- A small duplicate of the front matter reader exists, about 15 lines. A test checks that it reads the same `+++` blocks `state.py` does.
- A pack with a malformed row stops every gate run until it's fixed. The message names the file and line, and `standards.py check` shows the same problems on its own.
