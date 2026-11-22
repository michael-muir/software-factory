# 0036 · A kit can ship seed files inside `.factory/`, created once and never managed

Status: Accepted · Date: 2026-11-21 · Epic: E11

## Context

ADR 0003 splits the kit into kit files (everything under `.factory/`, tracked in the manifest, updated on upgrade and kept when edited) and state seeds (`.agentic/` and `docs/`, created when missing and never touched again). The PO chose a repo-owned `house` pack that the kit never overwrites. The reviewer should find it beside the other packs, in `.factory/standards/` (E11 assumption 3). Under today's rule, any file under `.factory/` is a kit file. A house pack shipped there would be updated, or shown as a local edit, on every upgrade.

## Decision

- **The kit declares seed files inside `.factory/`:** `SEED_FILES` in `factory_installer/kit.py`, starting with `.factory/standards/house/rules.md`. A seed file follows the state-seed rules:
  - it's created when missing
  - it's left alone when present, whatever its content
  - it's never written to the manifest, and never removed
- **The kit's copy is the template:** a valid pack with prefix `HOUSE` and one retired example row.
- **In this repo**, `kit/.factory/standards/house/rules.md` is that template, and the root `.factory/standards/house/rules.md` holds this repo's own rules. `install.py .` leaves the root copy alone.

## Consequences

- A repo's house rules survive every upgrade with no merge files and no warnings.
- A repo that deletes its house pack gets the template back on the next install, as with any state seed. To opt out, a repo switches the pack off with `[standards].packs` rather than deleting it.
- The manifest's rule "everything under `.factory/` is the kit's" now has a named exception list. Tests pin that list.
