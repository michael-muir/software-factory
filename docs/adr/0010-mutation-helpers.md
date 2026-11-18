# 0010 · Mutation runs through standard-library helpers with a pinned interpreter, sampling and outside-repo state

Status: Accepted · Date: 2026-11-17 · Epic: E06

## Context

The gate's model is exit codes only (E05). Neither cosmic-ray nor Stryker exits non-zero on a mutation-score threshold in the form the gate needs. They also need a list of files that changes on every run. Three findings shaped the design:

- **Pinning.** A probe found that cosmic-ray, given a bare `python` in its test command, picked an interpreter without pytest. Every mutant "died" from an import error, and the score read 100%.
- **Cost.** `gate.py` has 565 mutants. Testing each one serially takes hours (E06 design note).
- **Purity.** Both tools write session, report and temp files. The gate's purity check (ADR 0008) fails any check that leaves new files behind.

## Decision

- **One helper per stack** in `.factory/gates/tools/`, standard library only, invoked as `python <helper> --min {mutation_percent} {changed_files}`.
- **Pinned interpreter.** `mutate_python.py` builds cosmic-ray's test command from `sys.executable`: `<sys.executable> -m pytest -q -x <test-args>`. It runs cosmic-ray as `sys.executable -m cosmic_ray.cli`.
- **Outside-repo state.** Config, session database and reports go in a `tempfile.mkdtemp()` directory, which is removed in a `finally` block. Stryker's report path is set to that directory through a generated config file there. Stryker's `.stryker-tmp/` sandbox stays in the repo and must be git-ignored.
- **Test files are never mutated.** They are excluded by naming convention before anything runs (spec AC-05, AC-06).
- **Deterministic sampling (Python).**
  - After `cosmic-ray init`, the helper reads the session's work items.
  - If there are more than `max-mutants`, it keeps a sample chosen by `random.Random(seed)`. The seed is the SHA-256 of the sorted file paths and their contents.
  - It deletes the other items from the session database, then runs `exec`.
  - The same inputs always select the same mutants (E05 AC-17), and the output says "sampled X of Y".
- **Project settings (Python).** `[tool.software-factory.mutation]` in `pyproject.toml` sets `max-mutants` (default 100) and `test-args` (default `[]`). An invalid value exits 2, naming the key.
- **The score:**
  - **Python:** the kill rate is computed from the session database: killed ÷ (killed + survived). Mutants that time out count as killed, as cosmic-ray treats them. This is compared to `--min` directly, rather than through `cr-rate`.
  - **TS/JS:** Stryker's JSON report gives the mutation score.
- **Exit codes:**
  - 0 when the score is at or above the threshold, or when there's nothing to mutate
  - 1 when it's below
  - 2 when the tool or test runner is missing, or a setting is invalid

## Consequences

- A mutation score can never be inflated by a broken environment. A missing pytest becomes exit 2, not a perfect score.
- Mutation stays inside its timeout on large changes. The cost is that a sample can miss a weak spot that a full run would find; repeated runs on changed code over time narrow that gap.
- The Python helper depends on cosmic-ray's session schema. The helper tests run the real tool, so an incompatible upgrade fails visibly.
