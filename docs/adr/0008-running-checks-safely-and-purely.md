# 0008 · Running checks: no shell, resolved programs, killed process trees, purity snapshots

Status: Accepted · Date: 2026-11-17 · Epic: E05

## Context

The gate's verdict must be deterministic (spec AC-17), and the gate must never change the repo (AC-16). Commands come from profile files, which are plain text in the repo. Several platform details work against those goals:

- On Windows, a subprocess given an argument list does not apply `PATHEXT`, so `npm`, which is really `npm.cmd`, looks missing.
- `subprocess.run(timeout=…)` kills only the direct child, so grandchildren can outlive a timeout.
- A formatter run without its check-only flag rewrites files and then passes.

## Decision

- **No shell, ever.** Commands are argument lists, run from the repo root with `shell=False`. Placeholders are expanded per argument, so a file name can never be interpreted as shell syntax.
- **Programs are resolved first.** `shutil.which(argv[0], path=os.environ["PATH"])` resolves each program. If that returns nothing, the check fails with "command not found: \<program\>" (AC-10). The resolved path is what runs, and what the report shows.
- **Output** is captured with stdout and stderr merged in order, decoded as UTF-8 with replacement characters. The report keeps the last 40 lines.
- **Timeouts kill the whole tree.**
  - On POSIX, each check starts in a new session and its process group is sent `SIGKILL`.
  - On Windows, `taskkill /T /F /PID` is used.

  The check then fails with "timed out after \<n\>s" (AC-11).
- **The purity snapshot** is taken before and after each check. It is the SHA-256 of three things:
  - `git status --porcelain=v1 -z --untracked-files=all`
  - `git diff HEAD --binary --no-ext-diff`
  - the contents of untracked, non-ignored files

  If the hash changes, the check fails with "modified the repository", and the report lists the paths whose status line changed (AC-16). Git-ignored output such as `.coverage` or `node_modules/` does not count.
- **Environment:** checks inherit the gate's environment unchanged. The gate adds nothing that varies between runs.

## Consequences

- Profiles must use check-only modes: `ruff format --check`, `prettier --check`, and so on. Misconfigured profiles fail loudly instead of silently fixing code.
- The snapshot costs a few git calls per check, which is negligible next to a test suite.
- Tool caches must be git-ignored, or the check that writes them fails the purity check. That is a deliberate nudge toward clean repos, and E06's profiles document the caches their tools use.
