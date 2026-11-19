# 0023 · Adapters write committed files, tracked by a manifest and kept current by a drift check

Status: Accepted · Date: 2026-11-19 · Epic: E12

## Context

Claude Code, Copilot and Cursor each read agents, skills and hooks from their own folders and formats. The factory keeps one neutral source: `.factory/agents/` and `.factory/skills/`. The product owner chose to build the native files, commit them, and have the gate fail when they're stale. That way every tool, including Copilot's cloud agent, sees them straight from git.

Three questions follow:
1. **What counts as "no longer produced"?** A build must remove the files it wrote for a role that was deleted, or a tool that was dropped. It must never remove a repo's own files in the same folders, such as a hand-written skill in `.claude/skills/`.
2. **Are the generated files kit files?** Kit files are versioned and kept on upgrade when edited (ADR 0005). Generated files are derived from the repo's own sources.
3. **What does the gate do on drift?**

## Decision

- **`.factory/adapters/build.py`,** standard library only, builds every file in memory as `{path: bytes}`, and then either writes them or checks them.
- **A manifest,** `.factory/adapters/generated.json`, lists every path the last build produced, with its LF-normalised SHA-256. The build removes exactly the paths that are in the old manifest and not in the new output, and nothing else. A repo's own files beside the generated ones are never touched.
- **Generated files belong to the repo, not the kit.** They're rebuilt from the repo's sources, never versioned, and not kept on upgrade. Agent files carry a "generated, edit the source" notice. Skill copies can't carry one, because they're byte-for-byte copies.
- **Drift fails the verdict, but the checks still run** (ADR 0020's pattern). The gate runs `build.py --check` on every run and lists each missing, stale or extra file. A kit without `build.py` skips the check.
- **`install.py`** runs the build after installing, and `install.py check` reports drift.
- **`[adapters] tools`** in `.agentic/config.toml` picks the tools; the default is all three.

## Consequences

- Every tool reads ready-made files, including Copilot's cloud agent, which reads only the default branch.
- A role edited without a rebuild fails the gate on the next run, locally and in CI, and the report names the files.
- The manifest is one more committed file. Deleting it by hand makes the next build unable to remove stale files, and the drift check then reports them as unknown rather than removing them.
- Reviews show both the source change and the generated files. The drift check is the guarantee that they match.
