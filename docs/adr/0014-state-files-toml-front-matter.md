# 0014 · State files are Markdown with a strict TOML front matter

Status: Accepted · Date: 2026-11-18 · Epic: E02

## Context

Sessions resume from `STATE.md`, task files and handoffs alone (E02). The files must:
- be readable and writable by people and agents
- be parsed reliably by tools: `state.py`, the gate, and later E18's job index
- use only the standard library, as every kit script does

Python 3.11+ reads TOML (`tomllib`) but can't write it.

## Decision

- **Shape:** every state file is a `+++` line, a TOML document, a closing `+++` line, then a Markdown body. The body is never parsed beyond checking for its required `##` headings.
- **Strict schemas:** each file kind has a fixed schema of required keys, each with a type and, where listed, an allowed set of values. Missing keys, unknown keys, wrong types and values outside the set are all errors. A file is either fully valid or reported.
- **Writing:** `state.py` writes the front matter with a small emitter that covers only the types the schemas use:
  - strings, written as JSON strings (valid TOML basic strings)
  - non-negative integers
  - UTC datetimes ending in `Z`
  - lists of strings
  - the `[[findings]]` array of tables

  Keys are written in schema order, so rewrites are deterministic. The body is carried over byte for byte.
- **Times** are TOML offset datetimes in UTC.

## Consequences

- One parse gives the structured fields, with no Markdown parsing.
- Strictness catches typos (for example `statsu`) at the gate instead of letting a later session misread state.
- Hand edits are allowed, but they must stay valid. `state.py check` and the gate say what's wrong.
- Adding a field later is a schema change. Old files then fail validation until migrated, so later epics must add fields with a migration or a default.
