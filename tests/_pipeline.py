"""Helpers for the E13 pipeline tests: temp repos, plan and slice files that pass each stage's
check, and pipeline records.

The file shapes come from the E13 spec ("The stages") and design note ("The checks", "The
records"), and from the templates the checks reuse (E02 task files, E04 docs, E03 lock records,
E08 PR evidence). The made-up epic is E31.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import agents
from tests._ac import REPO_ROOT

PIPELINE_PY = REPO_ROOT / "kit" / ".factory" / "workflow" / "pipeline.py"
EPIC = "E31"
TASK = "E31-T1"
JOB = "e31-widgets"
SPEC_REL = "docs/specs/E31-widgets.md"
DESIGN_REL = "docs/design/E31-widgets-design.md"
TASK_REL = ".agentic/tasks/E31-T1.md"
LOCK_REL = ".agentic/locks/E31-T1.toml"
TEST_REL = "tests/test_widgets.py"
REVIEWERS = (
    "verifier",
    "spec-reviewer",
    "standards-reviewer",
    "security-reviewer",
    "perf-reviewer",
    "adversary",
)


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout


def head(root: Path) -> str:
    return git(root, "rev-parse", "HEAD").strip()


def repo(tmp_path: Path, name: str = "proj") -> Path:
    """A git repo on branch main with one commit (a README and a CHANGELOG)."""
    root = tmp_path / name
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    write(root, {"README.md": "fixture\n", "CHANGELOG.md": CHANGELOG})
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "fixture")
    return root


def write(root: Path, files: Mapping[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))


def commit(root: Path, files: Mapping[str, str], message: str = "change") -> str:
    """Write the files, commit them all, and return the new commit."""
    write(root, files)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)
    return head(root)


# --- plan files ---------------------------------------------------------------------------------


def spec_text(acs: Sequence[str] = ("AC-01", "AC-02"), epic: str = EPIC) -> str:
    lines = "\n".join(f"- **{ac}** Widgets do thing {ac}." for ac in acs)
    return f"""# {epic} · Widgets — Spec

Issue: [#82](https://example.com/issues/82) · Milestone: M2 · Depends on: none
Status: **Draft, awaiting product owner approval** · Next: design

## Goal

Widgets.

## Decisions in force

| Topic | Decision |
| ----- | -------- |
| Size  | Small    |

## In scope

- Widgets.

## Out of scope

- Gadgets.

## Acceptance criteria

{lines}

## Assumptions (to confirm with approval)

1. None.
"""


def design_text(spec_link: str = "../specs/E31-widgets.md") -> str:
    return f"""# {EPIC} · Widgets design note

Spec: [{EPIC} spec]({spec_link}) · Issue: [#82](https://example.com/issues/82)
Status: **Proposed, awaiting product owner acceptance** · ADRs: none yet

## Summary

One module.

## Source layout

```text
widgets.py   # the widgets
```

## Test seams

In-process calls.

## Vertical slices

| Task | Slice   | ACs          |
| ---- | ------- | ------------ |
| T1   | Widgets | AC-01, AC-02 |

## Risks

- None.
"""


def task_text(
    task: str = TASK,
    acs: str = "E31 AC-01, AC-02.",
    *,
    review_round: int = 0,
    findings: Sequence[Mapping[str, str]] = (),
) -> str:
    tables = "".join(
        "\n[[findings]]\n" + "".join(f'{key} = "{value}"\n' for key, value in finding.items())
        for finding in findings
    )
    return f"""+++
id = "{task}"
title = "Widgets"
status = "in-progress"
review_round = {review_round}
created = 2026-11-21T00:00:00Z
updated = 2026-11-21T00:00:00Z
{tables}+++

## Goal

Widgets.

## Acceptance criteria

{acs}

## Notes

None.
"""


def plan_files(acs: Sequence[str] = ("AC-01", "AC-02")) -> dict[str, str]:
    return {SPEC_REL: spec_text(acs), DESIGN_REL: design_text(), TASK_REL: task_text()}


# --- slice files --------------------------------------------------------------------------------

TESTS = """import pytest


@pytest.mark.ac("E31-AC-01")
def test_widgets_do_one() -> None:
    assert False


@pytest.mark.ac("E31-AC-02")
def test_widgets_do_two() -> None:
    assert False
"""

CHANGELOG = """# Changelog

## [Unreleased]

## [0.1.0] - 2026-11-01

- First release.
"""


def lock_tests(root: Path, files: Mapping[str, str] | None = None) -> str:
    """Write the slice's tests, lock them with agents.py, and commit both in one commit."""
    files = {TEST_REL: TESTS} if files is None else files
    write(root, files)
    agents.lock(root, TASK, [root / rel for rel in files])
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "test(E31/T1): lock failing tests")
    return head(root)


def plan_and_slice_base(tmp_path: Path) -> tuple[Path, str]:
    """A repo whose plan (spec, design, task) is committed on main: returns (repo, slice base)."""
    root = repo(tmp_path)
    return root, commit(root, plan_files(), "docs(E31): plan")


def gate_report(commit: str, *, verdict: str = "pass", dirty: bool = False) -> dict[str, Any]:
    """A gate JSON report in the shape `gate.py --json-out` writes (E08 AC-01)."""
    checks = [
        {"name": "format", "status": "pass", "detail": "", "seconds": 0.1, "stdout": ""},
        {
            "name": "tests",
            "status": "pass" if verdict == "pass" else "fail",
            "detail": "",
            "seconds": 1.0,
            "stdout": "",
        },
    ]
    return {
        "verdict": verdict,
        "root": ".",
        "base_ref": "main",
        "commit": commit,
        "dirty": dirty,
        "profiles": ["python"],
        "changed_files": [],
        "locks": {"locked": 1, "broken": []},
        "docs": {"checked": 2, "problems": []},
        "adapters": {"files": None, "problems": []},
        "checks": checks,
    }


def pr_body(commit: str, epic: str = EPIC) -> str:
    """A filled-in PR body that passes `check-pr --strict` for a branch holding `commit`."""
    return f"""{epic}/T1: widgets. Covers {epic} **AC-01** and **AC-02**. Refs #82.

## What changes

- Widgets.

## Acceptance criteria

- **AC-01** `tests/test_widgets.py`: `test_widgets_do_one`
- **AC-02** `tests/test_widgets.py`: `test_widgets_do_two`

## Tests

1 locked test file.

## Gate evidence

**PASS** on `{commit[:12]}`.

## Findings

None.
"""


def record(**fields: Any) -> dict[str, Any]:
    """A pipeline record (design note, "The records") with sensible defaults."""
    data: dict[str, Any] = {
        "version": 1,
        "id": JOB,
        "epic": EPIC,
        "issue": 82,
        "status": "running",
        "reason": "",
        "stage": "spec",
        "task": JOB,
        "base": "main",
        "request": "Make widgets.",
        "warnings": [],
        "tasks": [],
        "runs": [],
        "sessions": [],
        "gates": [],
        "decisions": [],
    }
    data.update(fields)
    return data


def gate_entry(task: str, report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "task": task,
        "commit": report["commit"],
        "verdict": report["verdict"],
        "report": json.dumps(report),
    }


def factory_dir(root: Path) -> Path:
    common = git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    return Path(common) / "factory"


def sidecar(root: Path, job: str, name: str) -> Path:
    """E18's sidecar path, `work/<id>.<name>.toml` (E18 design, "Sidecars")."""
    return factory_dir(root) / "work" / f"{job}.{name}.toml"
