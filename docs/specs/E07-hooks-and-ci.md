# E07 · Hooks and CI — Spec

Issue: [#7](https://github.com/michael-muir/software-factory/issues/7) · Milestone: M1 · Manual factory (alpha) · Depends on: E05 (done), E06 (done)
Status: **Approved by the product owner, 18 Nov 2026** · Next: Architect design note and ADRs, then failing tests per AC

## Goal

The gate gives the same verdict on a developer's machine, in a git hook and in CI. Git hooks give fast feedback on commit and run the full gate on push. An installer command writes a ready-to-run pipeline for GitHub Actions, GitLab CI, Azure Pipelines or Jenkins, with tool-setup steps matched to the repo's stack. This repo runs its own gate in GitHub Actions on Ubuntu, Windows and macOS.

## Decisions in force

| Topic | Decision |
| --- | --- |
| What hooks run | **pre-commit**: fast checks only, from `gates.commit_checks` (default format, lint, types). **pre-push**: the full gate, the same command CI runs. |
| Selecting checks | New gate option `--checks NAME[,NAME...]` |
| Installing hooks | Opt-in. `python install.py hooks` points `core.hooksPath` at `.factory/gates/hooks/`, where the hooks ship as kit files. Nothing is copied into `.git/`. |
| What a hook checks | The working tree as it is, unstaged edits included. The hook says so. Push and CI judge the exact commits. |
| Project environment | New config key `gates.python_command`, a command list (default `["python"]`). Hooks and pipelines run the gate with it, for example `["uv", "run", "python"]`. |
| Pipelines | `python install.py ci <provider>` renders a pipeline file from a kit template, with setup steps for the profiles detected in the repo. It's manifest-tracked, so upgrades refresh it. |
| Base for changed files | New gate option `--base-ref REF`, which overrides `gates.base_ref` for one run. Pipelines pass the PR's target branch and fetch full history. |
| Providers | GitHub Actions is proven live on this repo. GitLab CI, Azure Pipelines and Jenkins are proven by tests on the rendered files. |
| This repo's CI | GitHub Actions on Ubuntu, Windows and macOS, the full gate on every PR and on pushes to `main` |

**Naming note:** the hook-environment key was discussed as `gates.hook_python`. The spec calls it `gates.python_command`, because the pipelines use it too, so the gate runs the same way in both places.

## In scope

- The gate options `--checks` and `--base-ref`.
- The config keys `gates.commit_checks` and `gates.python_command`, and their validation.
- The `pre-commit` and `pre-push` hooks in the kit, and `install.py hooks`.
- Pipeline templates for four providers, and `install.py ci`.
- This repo's GitHub Actions workflow and hooks.

## Out of scope

- Publishing gate evidence on PRs: artefacts, comments, status summaries (E08).
- Branch protection rules and required-check settings, which belong to the repo owner.
- Live runs on GitLab, Azure DevOps or Jenkins.
- Other hook types (commit-msg, pre-rebase), and hook managers such as husky or pre-commit.
- Caching tool installs in CI, beyond what each provider's setup step does by default.

## Acceptance criteria

**Gate options**

- **AC-01** `gate.py --checks a,b`:
  - It runs only the named checks, in the gate's fixed order.
  - Every other check is reported as `skipped` with the reason "not selected".
  - The verdict and exit code come from the selected checks only.
  - An unknown check name exits 2 and lists the valid names.
- **AC-02** `gate.py --base-ref REF` uses REF instead of `gates.base_ref` for that run. The text and JSON reports show the base that was used.

**Config**

- **AC-03** `config.toml` gets two new `gates` keys, both validated by `install.py check`:
  - **`commit_checks`**: a list of check names, default `["format", "lint", "types"]`. Each item must be one of the seven check names.
  - **`python_command`**: a non-empty list of strings, default `["python"]`.

  The seed config shows both keys with comments. A config file without them gets the defaults, and the gate reads them the same way.

**Hooks**

- **AC-04** The kit ships `.factory/gates/hooks/pre-commit` and `.factory/gates/hooks/pre-push`:
  - They're POSIX `sh` scripts with LF line endings.
  - The installer writes them executable on POSIX.
  - They run on Linux, macOS, and Git for Windows' bundled `sh`.
- **AC-05** The pre-commit hook:
  - runs `<python_command> .factory/gates/gate.py --checks <commit_checks>` from the repo root
  - prints a note that unstaged changes are included
  - blocks the commit when the gate exits non-zero
- **AC-06** The pre-push hook runs `<python_command> .factory/gates/gate.py` from the repo root, the same gate command a pipeline runs, and blocks the push when the gate exits non-zero.
- **AC-07** Each hook reads `config.toml` with a standard-library Python 3.11+ found on PATH. If none is found, the hook exits non-zero with a message saying so. If `config.toml` is invalid, it blocks with the gate's config error naming the key. *(Clarified 18 Nov 2026 with the design: `install.py` isn't installed into target repos, so the hook uses the gate's own validation.)*
- **AC-08** `python install.py hooks [path]`:
  - It sets `core.hooksPath` to `.factory/gates/hooks`.
  - Running it again changes nothing and reports that hooks are already on.
  - If `core.hooksPath` is already set to something else, it exits 1 naming the current value, unless `--force` is given.
  - `--remove` unsets it, but only if it points at the factory hooks.
  - In a repo without the installed kit, it exits 1 and says to install first.

**Pipelines**

- **AC-09** `python install.py ci <provider> [path]` writes one file. The providers are `github`, `gitlab`, `azure` and `jenkins`, and none of the files collides with a provider's default file:

  | Provider | File | How the project turns it on |
  | --- | --- | --- |
  | github | `.github/workflows/factory-gate.yml` | Nothing else to do |
  | gitlab | `.gitlab/factory-gate.yml` | `include:` it from `.gitlab-ci.yml`, or set it as the CI config path |
  | azure | `.azure-pipelines/factory-gate.yml` | Create a pipeline from this file |
  | jenkins | `jenkins/factory-gate.Jenkinsfile` | Point a Pipeline job's script path at it |

  The command prints that turn-on step.
- **AC-10** Every rendered pipeline:
  - runs on pull or merge requests, and on pushes to the base branch
  - checks out full history
  - sets up the tools for each profile detected in the repo:
    - Python: Python 3.12 and uv, then `uv sync --locked` if `uv.lock` exists, else `pip install -e .`
    - TS/JS: Node LTS and `npm ci`
  - runs `<python_command> .factory/gates/gate.py`, adding `--base-ref <the target branch>` on pull and merge requests

  The job's result is the gate's exit code.
- **AC-11** If no profile applies to the repo, `install.py ci` exits 1 with the gate's "no profile applies" message, and writes nothing.
- **AC-12** `install.py ci github --os ubuntu,windows,macos` runs the gate job on each listed OS. The default is `ubuntu`. Other providers reject `--os` with exit 2.
- **AC-13** Pipeline files are tracked in the manifest like kit files, under the same upgrade and conflict rules (ADRs 0005 and 0006):
  - Running `install.py ci` again re-renders the file.
  - A file the user has edited is a conflict, kept unless `--force` is given.
  - A plain `install.py` upgrade re-renders every pipeline file in the manifest.
- **AC-14** Tests check every provider with three repos (Python only, TS/JS only, and both). Each rendered file:
  - parses: YAML for the three YAML providers, and balanced blocks plus the declarative `pipeline {}` structure for Jenkins
  - contains exactly the expected setup steps and gate command

**This repo**

- **AC-15** This repo:
  - sets `python_command = ["uv", "run", "python"]`
  - commits `.github/workflows/factory-gate.yml`, rendered with `install.py ci github --os ubuntu,windows,macos`
  - turns its hooks on with `install.py hooks`

  On the E07 PR, the gate job passes on all three OSes.
- **AC-16** **Same verdict, shown with one seeded failure.** A lint error committed to a test branch:
  - fails the lint check when the gate runs directly
  - is blocked by the pre-commit hook
  - is blocked by the pre-push hook, pushing to a local bare remote
  - fails the lint check in GitHub Actions

  The first three are automated tests. The CI run is evidence in the PR: a throwaway branch, deleted afterwards.

**Quality**

- **AC-17** ruff, `ruff format --check` and `mypy --strict` pass. The gate and the hooks' helper stay standard-library only. Every AC above has at least one test tagged `E07-AC-nn`, except the live CI evidence in AC-15 and AC-16.

## Assumptions (confirmed with approval, 18 Nov 2026)

1. **Hooks need a Python 3.11+ on PATH, for reading config,** even in TS/JS-only repos. The gate needs Python anyway.
2. **`git commit --no-verify` and `git push --no-verify` still bypass the hooks.** That's git's standard escape hatch. CI is the check nobody can bypass.
3. **Pipeline file names avoid each provider's default file** (`.gitlab-ci.yml`, `azure-pipelines.yml`, `Jenkinsfile`), so the installer never overwrites a project's existing pipeline. Turning a pipeline on is one documented step.
4. **The Python version in pipelines is 3.12, and Node is the current LTS.** Neither is configurable in E07.
5. **The pre-push hook uses `gates.base_ref` from config,** usually the local `main`. It doesn't work out the remote's target branch.
6. **This repo's CI runs the full suite on 2–4-core runners,** so it will be slower than locally (3.5 min on 32 cores). If a run nears the 600 s tests timeout or the 1800 s mutation timeout, T-final reports the timings before any change is made.

## Notes for the Architect (design, not requirements)

- How a hook gets from `sh` to Python: a small standard-library launcher next to the hooks, which reads config and runs the gate.
- How the manifest tracks rendered pipeline files, which live outside `.factory/`, and how an upgrade re-renders them (ADR 0005 and 0006 rules).
- Template format: standard-library `string.Template` versus small Python builders per provider.
- How to test hooks without touching the developer's own git config: temp repos, and `GIT_CONFIG_GLOBAL` pointed at an empty file.
- YAML parsing in tests needs a dev dependency (PyYAML), but only in tests, never in the kit.
- Setting an exec bit through the installer on Windows (a no-op) and on POSIX (`chmod 0o755`), and how Git for Windows runs `sh` hooks.
