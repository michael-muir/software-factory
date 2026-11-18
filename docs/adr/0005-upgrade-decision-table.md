# 0005 · Upgrade decision table

Status: Accepted · Date: 2026-11-17 · Epic: E01

## Context

The spec requires full upgrades in E01 (AC-12 to AC-17). For every kit file the installer compares three hashes:

- **M**: the hash recorded in the manifest for the installed version.
- **D**: the hash of the file on disk now.
- **K**: the hash of the file in the new kit.

The spec leaves three cases open. They are marked as choices A, B and C below.

## Decision

| In manifest | On disk | In new kit | Condition | Action |
| --- | --- | --- | --- | --- |
| no | no | yes | — | `create` |
| no | yes | yes | D = K | `unchanged` (adopted into the manifest) |
| no | yes | yes | D ≠ K | `skip`, or `overwrite` with `--force` |
| yes | yes | yes | D = K | `unchanged` |
| yes | yes | yes | D = M, M ≠ K | `update` |
| yes | yes | yes | D ≠ M, D ≠ K | `keep` and write `<name>.factory-new`, or `overwrite` with `--force` |
| yes | yes | no | D = M | `remove` |
| yes | yes | no | D ≠ M | `keep-dropped` |
| yes | no | yes | — | `deleted-locally`: not recreated, dropped from the manifest |
| yes | no | no | — | nothing; drop it from the manifest |

The manifest is then rewritten. It holds the new kit version and the hash on disk of every kit file the installer wrote or confirmed. A `keep` file keeps its old manifest hash, so it is checked again on the next upgrade.

### Choices confirmed by the product owner (2026-11-17)

- **A. A kit file the user deleted.** The deletion is respected. The file is reported as `deleted-locally` and dropped from the manifest, so it stays deleted.
- **B. `--force` on a locally edited file.** `--force` overwrites it with the new kit content and reports it as overwritten. This is the same meaning of `--force` as AC-10.
- **C. `.factory-new` files are git-ignored.** The kit ships `.factory/.gitignore` containing `*.factory-new`, and a newer run overwrites an older `.factory-new`. Ignored files are easy to miss, so:
  - the report lists every `.factory-new` path under its own heading;
  - the run ends with a one-line reminder of how many files are waiting to be merged;
  - `--json` lists them under `pending_merge`.

## Consequences

- The table is implemented in pure `plan.py` and tested row by row, with one test per row tagged with its AC.
- Users never lose an edit without opting in with `--force`.
- `git status` stays clean after an upgrade. The installer's report is the only place pending merges show up.
