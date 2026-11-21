# 0035 · Which rules apply to a change is computed from globs, markers and config, never judged

Status: Accepted · Date: 2026-11-21 · Epic: E11

## Context

A repo may have all 12 packs installed. A reviewer who reads all of them wastes context and cites rules from other languages. The PO chose: packs apply by their file globs, Tests and Docs are always on, and `[standards]` can switch packs and rules off. Unreal C++ and Google C++ both match `*.cpp` but disagree on rules. Deciding "which packs apply" in the reviewer's head would make reviews depend on the model.

## Decision

- **`standards.py select` decides, deterministically.** A pack applies when all of these hold:
  - a changed file matches one of its `applies_to` globs (`fnmatchcase` on repo-relative POSIX paths, as the gate's `mutation_paths` are matched)
  - every `detect` marker it has matches a file at the repo root
  - no pack that applies `replaces` it
  - `[standards].packs` doesn't set it to `false`

  Rules that are retired, or listed in `[standards].ignore`, are left out. Packs and rules are listed in name and id order.

- **"Changed" means exactly what the gate means.** With `--base-ref`, or by default, `select` loads `gate.py` by path and calls its `changed_files`. The default ref is `gates.base_ref`. Given file arguments, it uses them as given.
- **`replaces` is resolved in one pass:** a pack that is itself replaced can't replace others. Cycles are a validation problem.
- **Packs never affect pass or fail.** `select` reports; it never fails the gate. Only problems in the packs or config stop the gate (ADR 0033).

## Consequences

- Two reviewers of the same diff see the same rules, and the skill's first step is one command.
- The Unreal and C++ conflict is settled by data (`detect = ["*.uproject"]`, `replaces = ["cpp"]`), not by the reviewer.
- `standards.py` depends on `gate.py` only for `--base-ref`. Without a gate, it needs explicit files.
- A new pack, including a repo's own, needs only its front matter to take part in selection.
