---
name: dependency-bump
description: Bumps one dependency to a new version on the lite track, proves it with the full gate, and hands off. Use when a dependency alert, a security advisory or a routine update asks for a newer version.
---

# Dependency bump

Used by: `router`, `implementer`.

## When to use

- A dependency alert, a security advisory or a scheduled update names one dependency.
- Not for upgrades that need code changes across the codebase: those need a spec.

## Steps

1. Pick one dependency and the target version. Read its changelog between the two versions for breaking changes.
2. Change only that one dependency in the manifest, and in the lock file if there is one. Nothing else goes in the same change.
3. Run the full gate: `python .factory/gates/gate.py`.
4. If the gate is red, don't patch around the new version. Hand off to the Debugger, or revert the bump and report why.
5. Write a handoff with the gate's verdict (skill: handoff), and open the PR on the lite track.

## Done when

- The diff changes exactly one dependency.
- The full gate passed on that diff, and the handoff records **PASS**.
- Any breaking change in the changelog is named in the handoff, with how it was checked.
