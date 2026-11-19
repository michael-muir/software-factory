"""E04/T1: the document linter: spec, design note and ADR rules, `check`, and three templates.

Covers E04 AC-01 (spec, design and ADR templates), AC-03 to AC-05, AC-07 and AC-11. Expectations
come from the E04 spec, the design note and ADR 0019, not from the implementation.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import docs
from tests._ac import REPO_ROOT

KIT_WORKFLOW = REPO_ROOT / "kit" / ".factory" / "workflow"
KIT_STATE = REPO_ROOT / "kit" / ".factory" / "state" / "state.py"

SPEC = """# E09 · Core roles — Spec

Issue: [#9](https://example.com/9) · Milestone: M1 · Depends on: E03 (done)
Status: **Approved by the product owner, 19 Nov 2026** · Next: design

## Goal

Roles.

## Decisions in force (product owner, 19 Nov 2026)

## In scope

## Out of scope

## Acceptance criteria

- **AC-01** One.
- **AC-02** Two.
- **AC-02b** Two, refined.

## Assumptions (confirmed with approval, 19 Nov 2026)
"""

DESIGN = """# E09 · Core roles design note

Spec: [E09 spec](../specs/E09-core-roles.md) · Issue: [#9](https://example.com/9)
Status: **Accepted by the product owner, 19 Nov 2026** · ADRs: none

## Summary

## Source layout (this repo)

## Test seams and speed

## Vertical slices

## Risks
"""

ADR = """# 0021 · Roles are files

Status: Accepted · Date: 2026-11-19 · Epic: E09

## Context

## Decision

## Consequences
"""


def write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8", newline="\n")
    return root


def good_repo(tmp_path: Path) -> Path:
    return write(
        tmp_path,
        {
            "docs/specs/E09-core-roles.md": SPEC,
            "docs/design/E09-roles-design.md": DESIGN,
            "docs/adr/0021-roles-are-files.md": ADR,
            "docs/adr/README.md": "# Architecture Decision Records\n",
        },
    )


def problems(root: Path) -> list[str]:
    return [str(p) for p in docs.validate(root)]


def lint(kind: str, rel: str, text: str, root: Path | None = None) -> list[str]:
    return [str(p) for p in docs.lint(kind, rel, text, root)]


# --- AC-03: specs -------------------------------------------------------------------------------

SPEC_REL = "docs/specs/E09-core-roles.md"


@pytest.mark.ac("E04-AC-03")
def test_a_valid_spec_has_no_problems(tmp_path: Path) -> None:
    assert lint("spec", SPEC_REL, SPEC, tmp_path) == []


@pytest.mark.ac("E04-AC-03")
@pytest.mark.parametrize(
    ("text", "where"),
    [
        (SPEC.replace("# E09 · Core roles — Spec", "# E08 · Core roles — Spec"), "title"),
        (SPEC.replace(" — Spec\n", "\n", 1), "title"),
        (SPEC.replace("Issue: [#9](https://example.com/9) · ", ""), "Issue"),
        (SPEC.replace("**Approved by the product owner, 19 Nov 2026**", "**Done**"), "status"),
        (
            SPEC.replace(
                "Status: **Approved by the product owner, 19 Nov 2026**", "Status: Approved"
            ),
            "status",
        ),
        (SPEC.replace("## Goal\n", ""), "## Goal"),
        (
            SPEC.replace("## Decisions in force (product owner, 19 Nov 2026)\n", ""),
            "## Decisions in force",
        ),
        (SPEC.replace("## In scope\n", ""), "## In scope"),
        (SPEC.replace("## Out of scope\n", ""), "## Out of scope"),
        (
            SPEC.replace("## Assumptions (confirmed with approval, 19 Nov 2026)\n", ""),
            "## Assumptions",
        ),
        (SPEC.replace("- **AC-02b** Two, refined.\n", "- **AC-02** Again.\n"), "AC-02"),
    ],
)
def test_spec_problems_name_where(text: str, where: str) -> None:
    found = lint("spec", SPEC_REL, text)
    assert any(p.startswith(f"{SPEC_REL}: {where}: ") for p in found), found


@pytest.mark.ac("E04-AC-03")
def test_a_spec_without_acceptance_criteria_is_a_problem() -> None:
    text = re.sub(r"- \*\*AC-[^\n]*\n", "", SPEC)
    found = lint("spec", SPEC_REL, text)
    assert any(p.startswith(f"{SPEC_REL}: ## Acceptance criteria: ") for p in found), found


@pytest.mark.ac("E04-AC-03")
def test_ac_ids_need_two_digits() -> None:
    text = re.sub(r"- \*\*AC-[^\n]*\n", "- **AC-1** One.\n", SPEC)
    found = lint("spec", SPEC_REL, text)
    assert any(p.startswith(f"{SPEC_REL}: ## Acceptance criteria: ") for p in found), found


@pytest.mark.ac("E04-AC-03")
def test_a_draft_spec_passes() -> None:
    text = SPEC.replace(
        "**Approved by the product owner, 19 Nov 2026**", "**Draft, awaiting approval**"
    )
    assert lint("spec", SPEC_REL, text) == []


@pytest.mark.ac("E04-AC-03")
def test_headings_in_fenced_code_do_not_count() -> None:
    text = SPEC.replace("## Goal\n\nRoles.\n", "```markdown\n## Goal\n```\n")
    found = lint("spec", SPEC_REL, text)
    assert any(p.startswith(f"{SPEC_REL}: ## Goal: ") for p in found), found


@pytest.mark.ac("E04-AC-03")
def test_a_longer_word_is_not_the_heading() -> None:
    text = SPEC.replace("## Goal\n", "## Goals\n")
    found = lint("spec", SPEC_REL, text)
    assert any(p.startswith(f"{SPEC_REL}: ## Goal: ") for p in found), found


# --- AC-04: design notes ------------------------------------------------------------------------

DESIGN_REL = "docs/design/E09-roles-design.md"


@pytest.mark.ac("E04-AC-04")
def test_a_valid_design_note_has_no_problems(tmp_path: Path) -> None:
    root = good_repo(tmp_path)
    assert lint("design", DESIGN_REL, DESIGN, root) == []


@pytest.mark.ac("E04-AC-04")
@pytest.mark.parametrize(
    ("text", "where"),
    [
        (
            DESIGN.replace("# E09 · Core roles design note", "# E10 · Core roles design note"),
            "title",
        ),
        (DESIGN.replace(" design note\n", "\n", 1), "title"),
        (DESIGN.replace("Spec: [E09 spec](../specs/E09-core-roles.md) · ", ""), "Spec"),
        (DESIGN.replace("../specs/E09-core-roles.md", "../specs/E09-missing.md"), "Spec"),
        (
            DESIGN.replace("**Accepted by the product owner, 19 Nov 2026**", "**Approved**"),
            "status",
        ),
        (DESIGN.replace("## Summary\n", ""), "## Summary"),
        (DESIGN.replace("## Source layout (this repo)\n", ""), "## Source layout"),
        (DESIGN.replace("## Test seams and speed\n", ""), "## Test seams"),
        (DESIGN.replace("## Vertical slices\n", ""), "## Vertical slices"),
        (DESIGN.replace("## Risks\n", ""), "## Risks"),
    ],
)
def test_design_problems_name_where(tmp_path: Path, text: str, where: str) -> None:
    root = good_repo(tmp_path)
    found = lint("design", DESIGN_REL, text, root)
    assert any(p.startswith(f"{DESIGN_REL}: {where}: ") for p in found), found


@pytest.mark.ac("E04-AC-04")
def test_a_proposed_design_note_passes(tmp_path: Path) -> None:
    root = good_repo(tmp_path)
    text = DESIGN.replace(
        "**Accepted by the product owner, 19 Nov 2026**", "**Proposed, awaiting acceptance**"
    )
    assert lint("design", DESIGN_REL, text, root) == []


@pytest.mark.ac("E04-AC-04")
def test_without_a_root_the_spec_link_is_not_followed() -> None:
    text = DESIGN.replace("../specs/E09-core-roles.md", "../specs/E09-missing.md")
    assert lint("design", DESIGN_REL, text, None) == []


# --- AC-05: ADRs --------------------------------------------------------------------------------

ADR_REL = "docs/adr/0021-roles-are-files.md"


@pytest.mark.ac("E04-AC-05")
def test_a_valid_adr_has_no_problems(tmp_path: Path) -> None:
    assert lint("adr", ADR_REL, ADR, good_repo(tmp_path)) == []


@pytest.mark.ac("E04-AC-05")
@pytest.mark.parametrize(
    "status",
    [
        "Status: Proposed · Date: 2026-11-19",
        "Status: Accepted · Date: 2026-11-19 · Epic: E09 · Refines: [0005](0005-x.md)",
        "Status: Superseded by 0021 · Date: 2026-11-19",
    ],
)
def test_valid_adr_status_lines(tmp_path: Path, status: str) -> None:
    root = good_repo(tmp_path)
    text = ADR.replace("Status: Accepted · Date: 2026-11-19 · Epic: E09", status)
    assert lint("adr", ADR_REL, text, root) == []


@pytest.mark.ac("E04-AC-05")
@pytest.mark.parametrize(
    ("text", "where"),
    [
        (ADR.replace("# 0021 · ", "# 0022 · "), "title"),
        (ADR.replace("# 0021 · Roles are files", "# Roles are files"), "title"),
        (
            ADR.replace(
                "Status: Accepted · Date: 2026-11-19", "Status: Rejected · Date: 2026-11-19"
            ),
            "status",
        ),
        (ADR.replace("Status: Accepted · Date: 2026-11-19", "Status: Accepted"), "status"),
        (ADR.replace("Date: 2026-11-19", "Date: 19 Nov 2026"), "status"),
        (ADR.replace("Status: Accepted", "Status: Superseded by 0099"), "status"),
        (ADR.replace("## Context\n", ""), "## Context"),
        (ADR.replace("## Decision\n", ""), "## Decision"),
        (ADR.replace("## Consequences\n", ""), "## Consequences"),
    ],
)
def test_adr_problems_name_where(tmp_path: Path, text: str, where: str) -> None:
    root = good_repo(tmp_path)
    found = lint("adr", ADR_REL, text, root)
    assert any(p.startswith(f"{ADR_REL}: {where}: ") for p in found), found


# --- AC-07: check -------------------------------------------------------------------------------


def run(
    root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *args: str
) -> tuple[int, str]:
    monkeypatch.chdir(root)
    code = docs.main(list(args))
    out = capsys.readouterr()
    return code, out.out + out.err


@pytest.mark.ac("E04-AC-07")
def test_validate_lints_every_document_and_counts_them(tmp_path: Path) -> None:
    checked = docs.validate(good_repo(tmp_path))
    assert list(checked) == []
    assert checked.count == 3  # README.md isn't an ADR


@pytest.mark.ac("E04-AC-07")
def test_check_exits_0_when_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".agentic").mkdir()
    code, output = run(good_repo(tmp_path), monkeypatch, capsys, "check")
    assert code == 0, output


@pytest.mark.ac("E04-AC-07")
def test_check_prints_one_line_per_problem_and_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = good_repo(tmp_path)
    (root / ".agentic").mkdir()
    write(root, {SPEC_REL: SPEC.replace("## Goal\n", "").replace("## In scope\n", "")})
    code, output = run(root, monkeypatch, capsys, "check")
    assert code == 1, output
    lines = [line for line in output.splitlines() if line.startswith("docs/")]
    assert lines == [
        f"{SPEC_REL}: ## Goal: missing heading",
        f"{SPEC_REL}: ## In scope: missing heading",
    ]


@pytest.mark.ac("E04-AC-07")
def test_check_takes_a_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = good_repo(tmp_path / "repo")
    write(root, {ADR_REL: ADR.replace("## Context\n", "")})
    monkeypatch.chdir(tmp_path)
    assert docs.main(["--root", str(root), "check"]) == 1
    assert ADR_REL in capsys.readouterr().out


@pytest.mark.ac("E04-AC-07")
def test_a_repo_without_docs_has_nothing_to_check(tmp_path: Path) -> None:
    checked = docs.validate(tmp_path)
    assert (list(checked), checked.count) == ([], 0)


@pytest.mark.ac("E04-AC-07")
def test_files_outside_the_kinds_are_ignored(tmp_path: Path) -> None:
    root = good_repo(tmp_path)
    write(
        root,
        {
            "docs/GLOSSARY.md": "# Glossary\n",
            "docs/specs/notes.txt": "x\n",
            "docs/blueprint/a.md": "x\n",
        },
    )
    assert problems(root) == []


@pytest.mark.ac("E04-AC-07")
def test_docs_py_needs_its_sibling_state_py(tmp_path: Path) -> None:
    lonely = tmp_path / ".factory" / "workflow"
    lonely.mkdir(parents=True)
    shutil.copyfile(KIT_WORKFLOW / "docs.py", lonely / "docs.py")
    result = subprocess.run(
        [sys.executable, str(lonely / "docs.py"), "check"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, result
    assert "state.py" in result.stderr


# --- AC-01: the spec, design and ADR templates --------------------------------------------------


@pytest.mark.ac("E04-AC-01")
@pytest.mark.parametrize(
    ("kind", "template", "as_if"),
    [
        ("spec", "spec.md", "docs/specs/E00-example.md"),
        ("design", "design.md", "docs/design/E00-example.md"),
        ("adr", "adr.md", "docs/adr/0000-example.md"),
    ],
)
def test_each_template_passes_its_own_rules(kind: str, template: str, as_if: str) -> None:
    text = (KIT_WORKFLOW / "templates" / template).read_text(encoding="utf-8")
    assert lint(kind, as_if, text, None) == []


# --- AC-11: this repo's documents pass ----------------------------------------------------------


@pytest.mark.ac("E04-AC-11")
def test_this_repos_documents_pass() -> None:
    checked = docs.validate(REPO_ROOT)
    assert [str(p) for p in checked] == []
    assert checked.count >= 34  # 7 specs, 7 design notes and 20 ADRs when E04 began
