# 0013 · Pipeline files are rendered kit files, tracked by the manifest

Status: Accepted · Date: 2026-11-18 · Epic: E07

## Context

`install.py ci <provider>` writes a pipeline file outside `.factory/`. Its content depends on the repo: the detected profiles, whether `uv.lock` exists, `python_command`, the base branch and the OS list. Upgrades must refresh it, and a user's edits must survive, exactly like kit files (ADRs 0005 and 0006).

Today, `manifest.load` ignores every entry outside `.factory/`, because the manifest lives in the user's repo and its paths are untrusted.

## Decision

- **Manifest section:** the manifest gets a `pipelines` section that maps a provider name to its options, for example `{"github": {"os": ["ubuntu"]}}`.
  - Only the four known providers are read; unknown names are ignored.
  - Each provider's file path is a constant in the installer, never read from the manifest.
- **Allowed paths:** `manifest.load` accepts `files` entries under `.factory/`, plus those four constant paths.
- **Every install renders:** each install, and `install.py ci`, renders one file per recorded provider and adds it to the `Kit` as a managed file. The unchanged `plan()` then applies the ADR 0005/0006 decision table: create, update, conflict with a `.factory-new` file, `--force`, stays deleted.
- **Renderers:** these are Python functions per provider, deterministic and covered by unit tests. Templates are not files. Profile detection loads the kit's own `gate.py`, so the pipeline sets up exactly the stacks the gate will check.
- **No profile:** when no profile applies, `install.py ci` writes nothing and exits 1.

## Consequences

- No new upgrade logic is needed: pipeline files get every guarantee kit files already have, and its tests.
- The manifest still can't steer writes to arbitrary paths. The only new paths are four constants.
- `install.py ci` also runs a normal install, so it can refresh kit files when the clone is newer. The report shows every action, as an install always does.
- Changing a renderer changes the pipeline in every repo on its next upgrade. That's intended, and the change is visible in the upgrade report and the repo's diff.
