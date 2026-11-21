"""E08/T5: the done-when, in a test. A temp repo holds a spec, a task with locked tests tagged with
its ACs, a finding and a gate JSON report. `evidence.py` drafts the body, the test fills it in, and
`check-pr --strict --commits` passes it. A reviewer can then audit it from the body alone, and each
tampering fails the check.

Covers E08 AC-18. Expectations come from the E08 spec, not from the implementation. The fixture
uses a made-up epic, E42.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import docs
import evidence
from tests._gate import git

SPEC = """# E42 · Widgets — Spec

Issue: [#42](https://example.com/issues/42) · Milestone: M1 · Depends on: none
Status: **Approved by the product owner** · Next: tests

## Acceptance criteria

- **AC-01** Widgets can be added.
- **AC-02** Widgets can be counted.
- **AC-03** Widgets can be removed.
"""
TASK = """+++
id = "E42-T1"
title = "Widgets"
status = "in-review"
review_round = 1
created = 2026-11-20T00:00:00Z
updated = 2026-11-20T00:00:00Z

[[findings]]
id = "F1"
severity = "major"
status = "fixed"
summary = "widgets.py:2 counted one too many."
+++

## Goal

## Acceptance criteria

## Notes
"""
PY_TESTS = """import pytest


@pytest.mark.ac("E42-AC-01")
def test_add() -> None:
    pass


@pytest.mark.ac("E42-AC-02")
def test_count() -> None:
    pass
"""
TS_TESTS = """import { test } from "vitest";

// E42-AC-02
test("counts in the browser", () => {});
"""
LOCK = (
    'task = "E42-T1"\nlocked = 2026-11-20T00:00:00Z\n'
    '\n[[files]]\npath = "tests/test_widgets.py"\nsha256 = "' + "0" * 64 + '"\n'
    '\n[[files]]\npath = "web/widgets.test.ts"\nsha256 = "' + "0" * 64 + '"\n'
)
CHECKS = {"format": 0.25, "lint": 0.5, "types": 1.75, "tests": 12.0}
INPUT_TRACE = {
    "AC-01": {"tests/test_widgets.py": ["test_add"]},
    "AC-02": {
        "tests/test_widgets.py": ["test_count"],
        "web/widgets.test.ts": ["counts in the browser"],
    },
}


def _repo(tmp_path: Path) -> tuple[Path, str, Path]:
    """(repo, its HEAD, the gate's JSON report for HEAD)."""
    repo = tmp_path / "widgets"
    files = {
        "docs/specs/E42-widgets.md": SPEC,
        ".agentic/tasks/E42-T1.md": TASK,
        ".agentic/locks/E42-T1.toml": LOCK,
        "tests/test_widgets.py": PY_TESTS,
        "web/widgets.test.ts": TS_TESTS,
        "widgets.py": "def count() -> int:\n    return 2\n",
    }
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8", newline="\n")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "widgets")
    head = git(repo, "rev-parse", "HEAD").strip()
    report = {
        "verdict": "pass",
        "root": str(repo),
        "base_ref": "main",
        "commit": head,
        "dirty": False,
        "profiles": ["python"],
        "changed_files": ["widgets.py"],
        "locks": {"locked": 2, "broken": []},
        "docs": {"checked": 1, "problems": []},
        "checks": [
            {
                "profile": "python",
                "check": check,
                "status": "pass",
                "reason": "",
                "exit_code": 0,
                "duration_s": took,
                "command": [check],
                "output_tail": "",
            }
            for check, took in CHECKS.items()
        ],
    }
    path = tmp_path / "gate-report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return repo, head, path


def _drafted(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> tuple[Path, str, str]:
    repo, head, report = _repo(tmp_path)
    code = evidence.main(["--root", str(repo), "E42-T1", "--gate-report", str(report)])
    out = capsys.readouterr()
    assert (code, out.err) == (0, ""), out.err
    filled = out.out.replace("TODO(author): what this PR delivers", "Widgets can be counted")
    filled = filled.replace("TODO(author): what each change does, and why.", "A counter.")
    return repo, head, filled


def _check(
    repo: Path, body: str, commits: list[str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> tuple[int, str]:
    path = tmp_path / "pr.md"
    path.write_text(body, encoding="utf-8")
    argv = ["--root", str(repo), "check-pr", "--strict", str(path), "--commits", *commits]
    code = docs.main(argv)
    return code, capsys.readouterr().out


def _section(body: str, heading: str) -> str:
    return body.split(f"{heading}\n", 1)[1].split("\n## ", 1)[0]


@pytest.mark.ac("E08-AC-18")
def test_the_drafted_and_filled_body_passes_and_is_auditable_from_the_body_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, head, body = _drafted(tmp_path, capsys)
    assert _check(repo, body, [head], tmp_path, capsys) == (0, "")

    evidence_text = _section(body, "## Gate evidence")
    summary = evidence_text.strip().split("\n", 1)[0]
    verdict = re.match(r"\*\*(PASS|FAIL)\*\*", summary)
    assert verdict is not None and verdict.group(1) == "PASS"
    named = re.search(r"on `([0-9a-f]{7,40})`", summary)
    assert named is not None and head.startswith(named.group(1))
    full = evidence_text.split("```text\n", 1)[1].split("\n```", 1)[0]
    assert f"Commit: {head}" in full
    for check, took in CHECKS.items():
        assert f"python {check} pass {took:.2f} s" in summary
        assert re.search(rf"python\s+{check}\s+pass\s+{took:.2f}s", full), check

    trace: dict[str, dict[str, list[str]]] = {}
    current = ""
    for line in _section(body, "## Acceptance criteria").strip().split("\n"):
        ac = re.match(r"- \*\*(AC-\d\d)\*\*(.*)", line)
        if ac:
            current, rest = ac.group(1), ac.group(2)
        else:
            rest = line.strip().removeprefix("- ")
        spans = re.findall(r"`([^`]+)`", rest)
        if spans:
            trace.setdefault(current, {})[spans[0]] = spans[1:]
    assert trace == INPUT_TRACE

    findings = _section(body, "## Findings").strip().split("\n")
    assert findings == ["- F1 [major] (fixed) widgets.py:2 counted one too many."]


@pytest.mark.ac("E08-AC-18")
@pytest.mark.parametrize(
    "tamper",
    ["an AC not in the spec", "an AC with no test", "no commit", "a commit not the PR's"],
)
def test_each_tampering_fails_the_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], tamper: str
) -> None:
    repo, head, body = _drafted(tmp_path, capsys)
    commits = [head]
    if tamper == "an AC not in the spec":
        body = body.replace("- **AC-01** `", "- **AC-07** `", 1)
        expected = "AC-07: not in the E42 spec"
    elif tamper == "an AC with no test":
        line = next(x for x in body.split("\n") if x.startswith("- **AC-01** "))
        body = body.replace(line, "- **AC-01** checked by hand")
        expected = "AC-01: lists no test"
    elif tamper == "no commit":
        body = re.sub(r"[0-9a-f]{7,40}", "<sha>", body.replace(f"Commit: {head}", "Commit: none"))
        expected = "## Gate evidence: no commit SHA"
    else:
        git(repo, "commit", "-q", "--allow-empty", "-m", "another")
        git(repo, "commit", "-q", "--allow-empty", "-m", "and another")
        commits = [git(repo, "rev-parse", "HEAD").strip()]
        expected = "which is not a commit of this PR"
    code, out = _check(repo, body, commits, tmp_path, capsys)
    assert code == 1
    assert expected in out, out
