# 0019 · One standard-library docs module, with each document kind's rules as data

Status: Accepted · Date: 2026-11-19 · Epic: E04

## Context

E04 lints three kinds of repo document (specs, design notes and ADRs) and PR evidence. The CLI, the gate and `install.py check` all need the same answers, as with state (ADR 0015) and agents (ADR 0016). The three kinds differ only in their folder, file name, title, status rule, required lines and headings, plus one extra check each.

The options:
1. **One function per kind.** It's simple, but each function repeats the heading and status logic.
2. **One rule table and one engine.** A new kind is one more table row.
3. **Put the rules in the templates themselves,** with markers the linter reads. The templates would then be harder to copy cleanly.

## Decision

- **Option 2.** `.factory/workflow/docs.py` (standard library only) defines a `Kind` per document type: folder, file-name pattern, title pattern, status rule, required line, required headings, and an optional extra check. One engine applies them.
- **Built on `state.py`** (ADR 0016): it loads its sibling `state.py` for `Problem` and `find_root`. It exits 2 if `state.py` is missing.
- **Headings** match by prefix and ignore fenced code blocks. **Repo context is optional**, so templates lint without the files they link to.
- **Templates are kit files** in `.factory/workflow/templates/`, upgraded with the kit like any other kit file (ADR 0005).

## Consequences

- Adding a kind later, such as a runbook or a postmortem, means adding a row and a template.
- The rules live in code, not in the templates, so a test lints each template against its kind to keep them in step.
- `docs.py` is the third module on top of `state.py`, so `state.py`'s public helpers (the code review's step 1) carry more weight. A rename there breaks three modules, loudly.
