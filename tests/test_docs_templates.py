"""E04/T3: the task and PR evidence templates, lint_pr and check-pr, and full E04 AC coverage.

Covers E04 AC-01 (task and PR evidence templates), AC-02, AC-06 and AC-12. Expectations come from
the E04 spec and the design note, not from the implementation.
"""

from __future__ import annotations

import ast
import io
import sys
from pathlib import Path

import pytest

import docs
import state
from tests._ac import COLLECTED_AC_IDS, REPO_ROOT, spec_ac_ids

TEMPLATES = REPO_ROOT / "kit" / ".factory" / "workflow" / "templates"
KIT_DOCS_PY = REPO_ROOT / "kit" / ".factory" / "workflow" / "docs.py"

PR = """Refs #9.

## What changes

Roles as files.

## Acceptance criteria

- AC-01: tests/test_roles.py::test_one

## Tests

Twelve tests.

## Gate evidence

**PASS**: format, lint and types < 1 s.

## Findings

None.
"""

STATE = """+++
phase = "build"
track = "full"
active_task = ""
blockers = []
updated = 2026-11-19T08:00:00Z
+++
"""


def lint_pr(text: str, name: str = "pr.md") -> list[str]:
    return [str(p) for p in docs.lint_pr(text, name)]


# --- AC-02: the task template -------------------------------------------------------------------


@pytest.mark.ac("E04-AC-02")
def test_the_task_template_has_exactly_the_state_task_headings() -> None:
    text = (TEMPLATES / "task.md").read_text(encoding="utf-8")
    headings = [line for line in text.split("\n") if line.startswith("## ")]
    assert headings == list(state.TASK_HEADINGS)


@pytest.mark.ac("E04-AC-02")
def test_a_task_written_from_the_template_is_valid_state(tmp_path: Path) -> None:
    text = (TEMPLATES / "task.md").read_text(encoding="utf-8")
    parsed = state.parse(text)
    assert not isinstance(parsed, str), parsed
    task_id = parsed[0]["id"]
    assert isinstance(task_id, str)
    (tmp_path / ".agentic" / "tasks").mkdir(parents=True)
    (tmp_path / ".agentic" / "STATE.md").write_text(STATE, encoding="utf-8", newline="\n")
    (tmp_path / ".agentic" / "tasks" / f"{task_id}.md").write_text(
        text, encoding="utf-8", newline="\n"
    )
    assert [str(p) for p in state.validate(tmp_path)] == []


# --- AC-06: PR evidence -------------------------------------------------------------------------


@pytest.mark.ac("E04-AC-06")
def test_valid_pr_evidence_has_no_problems() -> None:
    assert lint_pr(PR) == []


@pytest.mark.ac("E04-AC-06")
def test_a_fail_verdict_is_also_a_verdict() -> None:
    assert lint_pr(PR.replace("**PASS**", "**FAIL**")) == []


@pytest.mark.ac("E04-AC-06")
@pytest.mark.parametrize(
    "heading", ["## What changes", "## Acceptance criteria", "## Gate evidence", "## Findings"]
)
def test_each_required_heading(heading: str) -> None:
    found = lint_pr(PR.replace(heading + "\n", ""))
    assert any(p.startswith(f"pr.md: {heading}: ") for p in found), found


@pytest.mark.ac("E04-AC-06")
def test_the_gate_evidence_must_state_a_verdict() -> None:
    found = lint_pr(PR.replace("**PASS**", "Passed"))
    assert any(p.startswith("pr.md: ## Gate evidence: ") for p in found), found


@pytest.mark.ac("E04-AC-06")
def test_a_verdict_elsewhere_does_not_count() -> None:
    text = PR.replace("**PASS**", "Passed").replace("Roles as files.", "Roles as files. **PASS**")
    found = lint_pr(text)
    assert any(p.startswith("pr.md: ## Gate evidence: ") for p in found), found


@pytest.mark.ac("E04-AC-06")
def test_check_pr_reads_a_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good, bad = tmp_path / "good.md", tmp_path / "bad.md"
    good.write_text(PR, encoding="utf-8")
    bad.write_text(PR.replace("## Findings\n", ""), encoding="utf-8")
    assert docs.main(["check-pr", str(good)]) == 0
    capsys.readouterr()
    assert docs.main(["check-pr", str(bad)]) == 1
    assert f"{bad}: ## Findings: missing heading" in capsys.readouterr().out


@pytest.mark.ac("E04-AC-06")
def test_check_pr_reads_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(PR.replace("## What changes\n", "")))
    assert docs.main(["check-pr"]) == 1
    assert "stdin: ## What changes: missing heading" in capsys.readouterr().out


# --- AC-01: the task and PR evidence templates --------------------------------------------------


@pytest.mark.ac("E04-AC-01")
def test_the_pr_evidence_template_passes_its_own_rules() -> None:
    assert lint_pr((TEMPLATES / "pr-evidence.md").read_text(encoding="utf-8")) == []


@pytest.mark.ac("E04-AC-01")
def test_the_kit_ships_all_five_templates() -> None:
    assert sorted(p.name for p in TEMPLATES.glob("*.md")) == [
        "adr.md",
        "design.md",
        "pr-evidence.md",
        "spec.md",
        "task.md",
    ]


# --- AC-12: quality and coverage ----------------------------------------------------------------


@pytest.mark.ac("E04-AC-12")
def test_docs_py_imports_only_the_standard_library() -> None:
    tree = ast.parse(KIT_DOCS_PY.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
    foreign = sorted({n.split(".")[0] for n in names} - set(sys.stdlib_module_names) - {"state"})
    assert not foreign, foreign


@pytest.mark.ac("E04-AC-12")
def test_e04_spec_defines_ac_01_to_ac_12() -> None:
    assert spec_ac_ids("E04") == {f"E04-AC-{n:02d}" for n in range(1, 13)}


@pytest.mark.ac("E04-AC-12")
def test_every_e04_ac_has_a_test(request: pytest.FixtureRequest) -> None:
    missing = spec_ac_ids("E04") - request.config.stash[COLLECTED_AC_IDS]
    assert not missing, f"E04 ACs with no test: {sorted(missing)}"
