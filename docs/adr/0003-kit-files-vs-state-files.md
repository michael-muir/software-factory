# 0003 · Kit files and state files are handled differently

Status: Accepted · Date: 2026-11-17 · Epic: E01

## Context

The factory writes two kinds of files into a target repo:

- **Kit files** under `.factory/`: roles, skills, standards, gates, workflow and adapters. They come from us and change when the kit is upgraded.
- **State files** under `.agentic/`: `config.toml`, `STATE.md`, task files and handoffs. They belong to the project from the moment they are created.

The spec says upgrades must never rewrite existing state (AC-16), and that only kit files go in the manifest (AC-08).

## Decision

- **Kit files** (everything under `kit/.factory/`) are tracked in `.factory/manifest.json` with their hashes, and the upgrade rules in ADR 0005 apply to them.
- **State seeds** (everything under `kit/.agentic/`) are created only when missing and skipped otherwise. They are never tracked in the manifest, never updated and never removed.
- `.factory/manifest.json` is written by the installer and not by hand. It is excluded from its own hash list.

## Consequences

- A user can edit anything in `.agentic/` without the installer ever touching it again.
- A new state file added in a later kit version still appears in existing repos, because a missing file is created.
- A change to a seed's default content never reaches existing repos. For `config.toml`, the code supplies defaults for keys that were added later (spec assumption 3).
