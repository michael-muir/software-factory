"""E04/T2: the gate lints documents on every run and reports them; install.py check reports them.

Covers E04 AC-08 to AC-10. Expectations come from the E04 spec, the design note and ADR 0020,
not from the implementation.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

import agents
import gate
from factory_installer import cli
from tests._ac import REPO_ROOT
from tests._gate import PASS, gate_repo, profile, run_gate, touches
from tests._repo import run_install_py

KIT = REPO_ROOT / "kit" / ".factory"
SPEC_REL = "docs/specs/E09-core-roles.md"
SPEC = """# E09 · Core roles — Spec

Issue: [#9](https://example.com/9)
Status: **Approved by the product owner, 19 Nov 2026**

## Goal

## Decisions in force

## In scope

## Out of scope

## Acceptance criteria

- **AC-01** One.

## Assumptions
"""
TASK = """+++
id = "E04-T2"
title = "A slice"
status = "in-progress"
review_round = 0
created = 2026-11-19T08:00:00Z
updated = 2026-11-19T08:00:00Z
+++

## Goal

## Acceptance criteria

## Notes
"""
NO_ACS = re.sub(r"- \*\*AC-01\*\* One\.\n", "", SPEC)
STATE = """+++
phase = "build"
track = "full"
active_task = ""
blockers = []
updated = 2026-11-19T08:00:00Z
+++
"""


def repo(tmp_path: Path, spec: str = SPEC, *, with_docs_py: bool = True) -> Path:
    root = gate_repo(
        tmp_path / "repo",
        {
            "py.toml": profile(
                "py", ["marker.txt"], {"format": touches("ran-format.txt"), "lint": PASS}
            )
        },
        files={"marker.txt": "x\n"},
    )
    files = {".agentic/STATE.md": STATE, SPEC_REL: spec}
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8", newline="\n")
    modules = ["state/state.py", "agents/agents.py"] + (
        ["workflow/docs.py"] if with_docs_py else []
    )
    for rel in modules:
        (root / ".factory" / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(KIT / rel, root / ".factory" / rel)
    return root


def json_report(
    root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *args: str
) -> tuple[int, dict[str, object]]:
    monkeypatch.chdir(root)
    code = gate.main(["--json", *args])
    return code, json.loads(capsys.readouterr().out)


# --- AC-08: the gate step -----------------------------------------------------------------------


@pytest.mark.ac("E04-AC-08")
def test_the_json_report_counts_checked_documents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, report = json_report(repo(tmp_path), monkeypatch, capsys)
    assert code == 0, report
    assert report["docs"] == {"checked": 1, "problems": []}
    assert report["verdict"] == "pass"


@pytest.mark.ac("E04-AC-08")
def test_a_document_problem_fails_the_verdict_but_the_checks_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(tmp_path, NO_ACS)
    code, report = json_report(root, monkeypatch, capsys)
    assert code == 1
    assert report["verdict"] == "fail"
    docs_section = report["docs"]
    assert isinstance(docs_section, dict)
    assert docs_section["checked"] == 1
    assert [p.split(": ")[:2] for p in docs_section["problems"]] == [
        [SPEC_REL, "## Acceptance criteria"]
    ]
    assert (root / "ran-format.txt").exists(), "the checks still run (ADR 0020)"
    checks = report["checks"]
    assert isinstance(checks, list) and checks


@pytest.mark.ac("E04-AC-08")
def test_the_text_report_shows_document_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, output = run_gate(repo(tmp_path), monkeypatch, capsys)
    assert code == 0, output
    assert "Docs: 1 checked, no problems" in output
    root = repo(tmp_path / "bad", NO_ACS)
    code, output = run_gate(root, monkeypatch, capsys)
    assert code == 1, output
    assert "Docs: 1 checked, 1 problem" in output
    assert f"{SPEC_REL}: ## Acceptance criteria: " in output
    assert output.rstrip().endswith("FAIL")


@pytest.mark.ac("E04-AC-08")
def test_documents_are_linted_even_with_checks_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, report = json_report(repo(tmp_path, NO_ACS), monkeypatch, capsys, "--checks", "lint")
    assert code == 1
    docs_section = report["docs"]
    assert isinstance(docs_section, dict) and docs_section["problems"]


@pytest.mark.ac("E04-AC-08")
def test_a_kit_without_the_linter_skips_the_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, report = json_report(repo(tmp_path, NO_ACS, with_docs_py=False), monkeypatch, capsys)
    assert code == 0, report
    assert report["docs"] == {"checked": 0, "problems": []}


@pytest.mark.ac("E04-AC-08")
def test_a_broken_lock_and_a_document_problem_are_both_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(tmp_path, NO_ACS)
    (root / ".agentic" / "tasks").mkdir(parents=True)
    (root / ".agentic" / "tasks" / "E04-T2.md").write_text(TASK, encoding="utf-8", newline="\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("def test_x() -> None:\n    pass\n", encoding="utf-8")
    agents.lock(root, "E04-T2", [root / "tests" / "test_x.py"])
    (root / "tests" / "test_x.py").write_text("changed\n", encoding="utf-8")
    code, report = json_report(root, monkeypatch, capsys)
    assert code == 1
    assert report["checks"] == [], "a broken lock still stops the run (ADR 0018)"
    locks, docs_section = report["locks"], report["docs"]
    assert isinstance(locks, dict) and locks["broken"]
    assert isinstance(docs_section, dict) and docs_section["problems"]


# --- AC-09: install.py check --------------------------------------------------------------------


@pytest.mark.ac("E04-AC-09")
def test_install_check_reports_document_problems(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(tmp_path, NO_ACS)
    shutil.copyfile(
        REPO_ROOT / "kit" / ".agentic" / "config.toml", root / ".agentic" / "config.toml"
    )
    assert cli.main(["check", str(root)]) == 1
    out = capsys.readouterr()
    assert f"{SPEC_REL}: ## Acceptance criteria: " in out.out + out.err


@pytest.mark.ac("E04-AC-09")
def test_install_check_passes_good_documents(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(tmp_path)
    shutil.copyfile(
        REPO_ROOT / "kit" / ".agentic" / "config.toml", root / ".agentic" / "config.toml"
    )
    assert cli.main(["check", str(root)]) == 0, capsys.readouterr()


# --- AC-10: the done-when, end to end -----------------------------------------------------------


@pytest.mark.ac("E04-AC-10")
def test_done_when_a_spec_without_acs_fails_the_gate_until_one_is_added(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = gate_repo(
        tmp_path / "repo",
        {"py.toml": profile("py", ["marker.txt"], {"lint": PASS})},
        files={"marker.txt": "x\n"},
    )
    installed = run_install_py(str(root))
    assert installed.returncode == 0, installed.stdout + installed.stderr
    spec = root / SPEC_REL
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text(NO_ACS, encoding="utf-8", newline="\n")
    code, output = run_gate(root, monkeypatch, capsys)
    assert code == 1, output
    assert SPEC_REL in output
    spec.write_text(SPEC, encoding="utf-8", newline="\n")
    code, output = run_gate(root, monkeypatch, capsys)
    assert code == 0, output
