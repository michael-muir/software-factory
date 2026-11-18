# 0006 · Upgrade refinements: unchanged state files and no-op merges

Status: Accepted · Date: 2026-11-17 · Epic: E01 · Refines: [0005](0005-upgrade-decision-table.md)

## Context

Writing the T5 tests exposed two cases that ADR 0005 and the spec left open:

1. **A locally edited kit file the new kit did not change** (D ≠ M, M = K). ADR 0005's table would write a `.factory-new` identical to the old version. That gives the user nothing new to merge.
2. **A re-run when state files already exist.** AC-09 reports pre-existing files as skipped. If a re-run reported every `.agentic/` file as skipped, it could never read "up to date" (AC-12).

The product owner decided both on 17 Nov 2026.

## Decision

- **Edited kit file, kit unchanged:** `keep`, reported as kept, and no `.factory-new` is written. A `.factory-new` is written only when the new kit's content differs from the manifest's (M ≠ K) and from the file on disk (D ≠ K).
- **State files once installed:** when a manifest exists, an `.agentic/` file that is already present is reported as `unchanged`. On a first install, where no manifest exists, a pre-existing state file is still `skipped` (AC-09).
- **"Up to date":** a run is up to date when nothing is created, skipped, overwritten, updated, kept or removed, and nothing is waiting to merge. The text report then says "Up to date".

## Consequences

- `.factory-new` files appear only when there is something to merge, so the reminder count stays meaningful.
- Re-running the installer is a cheap, quiet health check.
- A file edited locally keeps showing as kept on every run. That is accurate, and it means such a repo is never reported as "up to date" until the edit is reconciled.
