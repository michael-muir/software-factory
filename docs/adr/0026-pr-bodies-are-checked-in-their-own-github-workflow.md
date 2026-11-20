# 0026 · PR bodies are checked in their own GitHub workflow, which reads the event file

Status: Proposed · Date: 2026-11-19 · Epic: E08

## Context

The `pr-evidence` check must run whenever a PR body is edited, but an edit must not rerun the 12-minute gate on three OSes (spec AC-13).

The obvious fix is one workflow, triggered on `edited` too, with the gate jobs skipped on that type. That opens a hole. GitHub reports a job skipped by `if:` as a successful check run, and the newest run for a commit is the one that counts. Editing the body of a PR with a red gate would turn its gate check green.

The body is also untrusted text. Put into a script with `${{ github.event.pull_request.body }}`, it can run commands on the runner.

## Decision

- **Two files from `install.py ci github`:**
  - **`factory-gate.yml`** keeps its triggers: `pull_request` (opened, synchronize, reopened) and pushes to the base branch. Its jobs gain the JSON artefact and the job summary.
  - **`factory-pr-evidence.yml`** holds the `pr-evidence` job. It runs on `ubuntu-latest`, for `pull_request` opened, edited, synchronize and reopened.

  The provider record gains extra files, which only GitHub uses.

- **The body never touches a script.** One `python -c` step reads it from `$GITHUB_EVENT_PATH` into `pr-body.md`. The base and head SHAs come in through `env:`. `git rev-list "$BASE..$HEAD"` lists the PR's commits, then `python .factory/workflow/docs.py --root . check-pr --strict pr-body.md --commits ...` checks the body. Nothing is installed, and no token is used.
- **The gate job's evidence:** each gate step writes `--json-out "$RUNNER_TEMP/gate-report.json"`. Then two steps run with `if: always()`:
  - **The summary step,** in `shell: bash` on every OS: `evidence.py --summary <report>` appends to `$GITHUB_STEP_SUMMARY`. It writes "No gate report" when the file is missing.
  - **`actions/upload-artifact@v4`,** with the name `gate-report-${{ matrix.os }}` and `if-no-files-found: warn`.

## Consequences

- Editing a body runs one short Ubuntu job, and can never mask a gate result.
- A repo can make `pr-evidence` a required check independently of the gate. That's the repo owner's choice (spec: out of scope).
- `install.py ci github` now writes two files. The E07 tests that pin one file per provider change with E08's tests.
- GitLab, Azure and Jenkins are untouched. Adding a body check there later means each provider gaining its own extra file.
