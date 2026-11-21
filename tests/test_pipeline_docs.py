"""E13/T1: `pipeline.md`, the stage table it describes, the roles and skills it names, and this
repo's changelog.

Covers E13 AC-19. Expectations come from the E13 spec ("The stages", AC-19) and the design note
("The stage table"): one table, `STAGES`, which `pipeline.md` and the prompts follow (ADR 0040).
"""

from __future__ import annotations

import re

import pytest

import pipeline
import state
from tests._ac import REPO_ROOT

AC = "E13-AC-19"
KIT = REPO_ROOT / "kit" / ".factory"
DOC = KIT / "workflow" / "pipeline.md"
SCOPES = {"plan job": "plan", "slice job": "slice", "main checkout": "main"}
EXPECTED = [
    ("spec", ("spec-writer",), (("spec-interview",),), "plan", "spec"),
    ("design", ("architect",), (("design-note",),), "plan", "design"),
    ("test", ("test-designer",), (("tdd-slices", "lock-tests"),), "slice", ""),
    ("build", ("implementer",), (("tdd-slices",),), "slice", ""),
    ("gate", ("debugger",), (("debugging",),), "slice", ""),
    (
        "review",
        (
            "verifier",
            "spec-reviewer",
            "standards-reviewer",
            "security-reviewer",
            "perf-reviewer",
            "adversary",
        ),
        (
            ("verify-with-evidence",),
            ("spec-review",),
            ("standards-review",),
            ("threat-check",),
            ("perf-budget",),
            ("adversarial-testing",),
        ),
        "slice",
        "",
    ),
    ("docs", ("docs-writer",), ((),), "slice", ""),
    ("ship", ("integrator",), (("pull-request-evidence",),), "slice", "merge"),
    ("learn", (), (), "main", ""),
]


def ticked(cell: str) -> list[str]:
    return re.findall(r"`([^`]+)`", cell)


def doc_rows() -> list[list[str]]:
    lines = DOC.read_text(encoding="utf-8").splitlines()
    start = lines.index("## The stages")
    rows = []
    for line in lines[start:]:
        if line.startswith("| `"):
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
        elif rows and not line.startswith("|"):
            break
    return rows


@pytest.mark.ac(AC)
def test_the_stage_table_is_the_nine_phases_in_order_with_their_roles_and_skills() -> None:
    got = [(s.name, s.roles, s.skills, s.scope, s.checkpoint) for s in pipeline.STAGES]
    assert got == EXPECTED
    assert tuple(s.name for s in pipeline.STAGES) == state.PHASES


@pytest.mark.ac(AC)
def test_pipeline_md_has_one_row_per_stage_matching_the_table() -> None:
    rows = doc_rows()
    assert len(rows) == len(pipeline.STAGES)
    for row, stage in zip(rows, pipeline.STAGES, strict=True):
        assert ticked(row[0]) == [stage.name]
        assert ticked(row[1]) == list(stage.roles)
        assert ticked(row[2]) == [skill for skills in stage.skills for skill in skills]
        assert SCOPES[row[3]] == stage.scope
        assert ticked(row[4]) == ([stage.checkpoint] if stage.checkpoint else [])
        assert row[5] == stage.passes


@pytest.mark.ac(AC)
def test_every_role_and_skill_in_the_table_exists_in_the_kit() -> None:
    for stage in pipeline.STAGES:
        for role in stage.roles:
            assert (KIT / "agents" / "core" / f"{role}.md").is_file(), role
        for skills in stage.skills:
            for skill in skills:
                assert (KIT / "skills" / skill / "SKILL.md").is_file(), skill


@pytest.mark.ac(AC)
def test_the_router_hands_a_full_track_job_to_the_first_stages_role() -> None:
    router = (KIT / "agents" / "core" / "router.md").read_text(encoding="utf-8")
    handoff = router.split("## Hand-off", 1)[1]
    first = pipeline.STAGES[0].roles[0]
    assert f"A new full-track job goes to `{first}`." in handoff


@pytest.mark.ac(AC)
@pytest.mark.parametrize(
    "needle",
    [
        *(f"pipeline.py {command}" for command in pipeline.COMMANDS),
        *(f"`{key}`" for key in pipeline.PIPELINE_DEFAULTS),
        "work/<id>.pipeline.toml",
        "--permission-mode acceptEdits",
    ],
)
def test_pipeline_md_documents_the_commands_keys_and_record(needle: str) -> None:
    assert needle in DOC.read_text(encoding="utf-8")


@pytest.mark.ac(AC)
def test_the_commands_are_the_specs() -> None:
    expected = ("new", "run", "check", "approve", "reject", "resume", "cancel", "status")
    assert set(pipeline.COMMANDS) == set(expected)


@pytest.mark.ac(AC)
def test_this_repo_has_a_changelog_with_an_unreleased_section() -> None:
    text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "\n## [Unreleased]\n" in text


@pytest.mark.ac(AC)
def test_this_repo_installs_the_kits_pipeline_files() -> None:
    for name in ("pipeline.py", "pipeline.md"):
        kit = (KIT / "workflow" / name).read_bytes()
        assert (REPO_ROOT / ".factory" / "workflow" / name).read_bytes() == kit, name
