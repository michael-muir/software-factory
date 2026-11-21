+++
name = "house"
title = "House rules"
prefix = "HOUSE"
applies_to = ["*"]

[[sources]]
title = "Software Factory: house packs (ADR 0036)"
url = "https://github.com/michael-muir/software-factory/blob/main/docs/adr/"
licence = "Apache-2.0"
+++

# House rules

This repo's own rules, beside the kit's packs. The kit created this file once and never changes
it. Add a row for each rule, with the next free `HOUSE-NNN` id. A rule you drop stays in the
table as `retired`, so its id is never reused. Add a `[[sources]]` table for each page your
rules link to. Check the pack with `python .factory/standards/standards.py check`.

## Left to the tools

The gate's format and lint checks enforce everything the repo's formatter and linter cover.
Don't repeat those rules here.

## Rules

| Rule id   | Severity | Rule                                            | Why/example                                     | Source                                                                                                                |
| --------- | -------- | ----------------------------------------------- | ----------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| HOUSE-001 | retired  | Example: replace this row with your first rule. | A retired row is never cited, and keeps its id. | [ADR 0036](https://github.com/michael-muir/software-factory/blob/main/docs/adr/0036-kit-seed-files-inside-factory.md) |
