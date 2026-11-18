# E07 · Hooks and CI design note

Spec: [E07 spec](../specs/E07-hooks-and-ci.md) · Issue: [#7](https://github.com/michael-muir/software-factory/issues/7)
Status: **Accepted by the product owner, 18 Nov 2026** · ADRs: [0012](../adr/0012-git-hooks-launcher.md) · [0013](../adr/0013-rendered-pipeline-files.md)

## Summary

Three pieces, all built on the existing gate and installer.

1. **Gate options.** `gate.py` gains `--checks` and `--base-ref`, and `Settings` reads two new keys: `commit_checks` and `python_command`.
2. **Hooks.**
   - Two tiny `sh` hooks find a working Python 3.11+ and hand over to a standard-library launcher, `run_hook.py`.
   - The launcher reads the gate's own settings, then runs `python_command` with the right gate arguments.
   - `install.py hooks` switches the hooks on with `core.hooksPath`.
3. **Pipelines.**
   - `install.py ci <provider>` records the provider in the manifest and re-runs the normal install.
   - The install then renders each recorded provider's pipeline file and treats it as one more kit file. It goes through the same ADR 0005/0006 decision table, so upgrades, conflicts and `--force` work exactly as they do for `.factory/` files.

## Probe findings (18 Nov 2026, Git for Windows 2.55)

- Git runs an `sh` hook from `core.hooksPath`, and a non-zero exit blocks the commit. With `core.fileMode = false` the exec bit doesn't matter on Windows.
- **`python3` on Windows can be the Microsoft Store stub** (`WindowsApps\python3`), which doesn't run Python. A hook can't trust the first name on PATH. It has to try each candidate and keep the first that really is Python 3.11 or later.

## Source layout

```text
kit/.factory/gates/
├── gate.py                  # + --checks, --base-ref; Settings + commit_checks, python_command
└── hooks/
    ├── pre-commit           # sh: find Python 3.11+, exec run_hook.py pre-commit
    ├── pre-push             # sh: same, pre-push
    └── run_hook.py          # stdlib: import gate, load Settings, run python_command + gate args
factory_installer/
├── cli.py                   # + `hooks` and `ci` subcommands
├── hooks.py                 # core.hooksPath on/off, chmod of the hook scripts
├── pipelines.py             # provider table, profile detection (via the kit's gate), renderers
├── manifest.py              # + `pipelines` section; allow-listed pipeline paths
└── config_schema.py         # + gates.commit_checks, gates.python_command
kit/.agentic/config.toml     # + the two keys, with comments
.github/workflows/factory-gate.yml   # this repo's own rendered workflow (T4)
```

## Gate changes

| Part | Change |
| --- | --- |
| `Settings` | + `commit_checks: list[str]`, where every item must be one of `CHECK_ORDER` (exit 2 otherwise); + `python_command: list[str]`, non-empty. The defaults mirror `config_schema`. |
| `main` | `--checks a,b`: unknown names exit 2, listing the valid ones. `--base-ref REF` replaces `settings.base_ref` before `FileSource` is built, so the report shows the base actually used. |
| `run_profiles` | Takes the selected set. An unselected check gives `Result(..., "skipped", "not selected")` and never runs or computes changed files. |

The verdict logic is unchanged, because `skipped` already counts as not failing.

## Hooks (ADR 0012)

```sh
#!/bin/sh
# Software Factory pre-commit hook (E07). Bypass once with: git commit --no-verify
for py in python3 python py; do
  if command -v "$py" >/dev/null 2>&1 &&
     "$py" -c 'import sys; sys.exit(sys.version_info < (3, 11))' >/dev/null 2>&1; then
    exec "$py" "$(git rev-parse --show-toplevel)/.factory/gates/hooks/run_hook.py" pre-commit
  fi
done
echo "factory hook: no Python 3.11+ found on PATH (tried python3, python, py)" >&2
exit 1
```

`run_hook.py <hook>`:
1. It finds the repo root and imports `gate` from `.factory/gates/`, its parent folder.
2. It calls `gate.Settings.load(root)`. A config error prints the gate's own message, which names the same key and problem as `install.py check`, then exits 1.
3. It builds the argv:
   - **pre-commit:** `python_command + [".factory/gates/gate.py", "--checks", ",".join(commit_checks)]`. It first prints "factory hook: checking the working tree, unstaged changes included".
   - **pre-push:** `python_command + [".factory/gates/gate.py"]`
4. It resolves `argv[0]` with `shutil.which`, runs the command in the repo root with output passed through, and exits 0 if the gate exits 0, else 1. If the command isn't found, it says so and exits 1.

**Spec clarification (AC-07, accepted 18 Nov 2026).** The spec said an invalid config blocks "with the same message `install.py check` gives". `install.py` isn't installed into target repos, only `.factory/` is. So the hook uses the gate's validation, which names the same key and problem in slightly different words, for example `gate: .agentic/config.toml: gates.commit_checks: ...`. AC-07 now reads "with the gate's config error naming the key".

**`install.py hooks [path] [--force] [--remove]`** (`factory_installer/hooks.py`):
- It requires `.factory/gates/hooks/run_hook.py`. Without it, it exits 1 and says "run install.py first".
- It reads `git config --local core.hooksPath`:
  - **Unset:** set it to `.factory/gates/hooks`.
  - **Already ours:** report "already on".
  - **Anything else:** exit 1 naming the value, unless `--force`.
- `--remove` unsets it only when the value is ours.
- It also chmods `pre-commit` and `pre-push` to `0o755`, which does nothing on Windows. `core.hooksPath` is per-clone config, so every clone runs `install.py hooks` anyway. That makes it the right moment to fix modes lost by repos committed from Windows.
- The installer's `apply` also writes those two files as `0o755` on POSIX. This repo commits them with mode `100755` (`git update-index --chmod=+x`) for both `kit/` and `.factory/`.

## Pipelines (ADR 0013)

**Manifest.** A new top-level `"pipelines"` object, for example `{"github": {"os": ["ubuntu", "windows", "macos"]}}`. Rendered files keep their hashes in `files`, like any kit file.
- `manifest.load` still ignores untrusted paths. It now accepts `.factory/*` plus exactly the four fixed pipeline paths in `pipelines.PROVIDERS`, and ignores unknown provider names.

**Install flow.**
1. `install.py ci github --os ...` loads the manifest, adds or updates the provider entry, then runs `run_install` with it.
2. Every plain `install.py` run does the same with the recorded providers.
3. `run_install` builds the `Kit`, then adds one rendered file per recorded provider to `kit.files`.
4. `Kit.is_kit_managed` treats those paths as managed, so `plan()` applies the ADR 0005 table unchanged:
   - A user-edited pipeline is a conflict: kept, with a `.factory-new` beside it, unless `--force`.
   - A deleted one stays deleted.
5. `install.py ci` prints the provider's turn-on step after the report.
6. Rendering needs the detected profiles. `pipelines.py` loads the **kit's** `gate.py` with `importlib`, then calls `load_profiles` and `select_profiles` on the target. Selection is then identical to what the gate does, including a `gates.profiles` override.
7. If no profile applies, it exits 1 with the gate's message and writes nothing (AC-11).

**Renderers.** These are plain Python functions, one per provider, that build the text from a small `PipelineSpec`:
- profiles
- `has_uv_lock`
- `python_command`
- base branch, from `gates.base_ref` minus any `origin/` prefix
- OS list

I chose them over template files because the four formats differ structurally (YAML vs Groovy, conditionals, matrices), and functions are easy to unit-test. Output is deterministic: the same inputs always render the same bytes.

| Provider | Triggers | Checkout | Setup (Python / TS-JS) | Gate on PR or MR |
| --- | --- | --- | --- | --- |
| GitHub | `pull_request`, `push` to base | `actions/checkout@v4`, `fetch-depth: 0` | `actions/setup-python@v5` 3.12 + `astral-sh/setup-uv@v6`; `actions/setup-node@v4` `lts/*` | `--base-ref origin/${{ github.base_ref }}` |
| GitLab | `merge_request_event`, push to base | `GIT_DEPTH: 0`, then `git fetch origin $CI_MERGE_REQUEST_TARGET_BRANCH_NAME` | image `node:lts` when TS/JS is detected, else `python:3.12`; `pip install uv`, or `apt` python3 where needed | `--base-ref origin/$CI_MERGE_REQUEST_TARGET_BRANCH_NAME` |
| Azure | `pr` and `trigger` on base | `fetchDepth: 0` | `UsePythonVersion@0` 3.12 + `pip install uv`; `NodeTool@0` LTS | `--base-ref origin/$(System.PullRequest.TargetBranchName)` |
| Jenkins | Multibranch: PR or base branch | full clone, then `git fetch origin $CHANGE_TARGET` | Expects Python 3.12, uv and Node on the agent; runs `uv sync --locked` and `npm ci` | `--base-ref origin/$CHANGE_TARGET` when `CHANGE_TARGET` is set |

All four install the same way: `uv sync --locked` if `uv.lock` exists, else `pip install -e .`, and `npm ci` for TS/JS. The gate runs as `python_command + [".factory/gates/gate.py", ...]`.

**Jenkins has no standard way to install tools,** so the rendered file declares `agent any` and states in a header comment that Python 3.12, uv and Node must be on the agent. It uses `sh` steps, so it needs a Linux or macOS agent. This is the one place the spec's "sets up the tools" means "checks the tools are there and installs dependencies". Each tool step fails with a clear message when its tool is missing.

## Test seams

- **Hooks run for real in temp repos.** Each test sets `GIT_CONFIG_GLOBAL` to an empty file and `GIT_CONFIG_NOSYSTEM=1`, so the developer's own config is never read or changed. Pre-push is tested by pushing to a local bare repo.
- **A fixture profile drives the hooks.** It uses `[sys.executable, "-c", ...]` checks, as the E05 tests do, with `python_command = [sys.executable]`. Hook tests then need no ruff or mypy and stay fast. Only the same-verdict test (AC-16) uses the real Python profile on the `python-ref` fixture, tagged `slow`.
- **Renderers are tested as functions,** for every provider × {Python, TS/JS, both}. YAML is parsed with PyYAML, a new dev dependency used in tests only. The Jenkinsfile gets a brace-balance and structure check.
- **The manifest and upgrade behaviour of pipeline files** reuses the E01 test helpers: install, edit, upgrade, then check for a conflict and `.factory-new`.

## Vertical slices

| Task | Slice | ACs |
| --- | --- | --- |
| T1 | Gate `--checks` and `--base-ref`; config keys in the gate and `install.py check`; seed config | AC-01, AC-02, AC-03 |
| T2 | Hook scripts and `run_hook.py`; `install.py hooks`; exec bits; local same-verdict test | AC-04 to AC-08, AC-16 (local part) |
| T3 | Pipeline renderers for four providers; manifest `pipelines`; `install.py ci`; upgrade rules | AC-09 to AC-14 |
| T4 | Dogfood: this repo's `python_command`, rendered workflow on three OSes, hooks on, seeded-failure CI evidence, E07 AC coverage enforced | AC-15, AC-16 (CI part), AC-17 |

## Risks

- **CI runtime.** GitHub runners have 2 to 4 cores, while this machine has 32. The full suite took 215 s in parallel here, and could approach the 600 s tests timeout on a runner. T4 measures it first and reports before changing anything (spec assumption 6).
- **macOS and Linux timeout-kill paths** (E05) run for the first time in T4. Bugs found there are fixed in T4 with tests.
- **Action and image versions drift.** The renderers pin major versions (`@v4`, `@v5`). Moving them is a deliberate kit change, and upgrades re-render the files.
- **Jenkins and GitLab files are proven only statically** (spec decision). The first real user may find environment gaps.
