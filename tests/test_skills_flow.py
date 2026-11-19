"""E10/T1: the five workflow skills, and the role cards that name them.

Covers E10 AC-04 and AC-06 for `tdd-slices`, `lock-tests`, `handoff`, `resume-from-state` and
`verify-with-evidence`. The rows are the spec's table (docs/specs/E10-skills-library.md).
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

import agents
from tests._ac import REPO_ROOT

KIT = REPO_ROOT / "kit" / ".factory"
SKILLS = KIT / "skills"
CORE = KIT / "agents" / "core"
ALL_ROLES = tuple(sorted(p.stem for p in CORE.glob("*.md")))


@dataclass(frozen=True)
class Row:
    name: str
    used_by: tuple[str, ...]
    phrases: tuple[str, ...]  # AC-06: what the skill must say


ROWS = (
    Row("tdd-slices", ("test-designer", "implementer"), ("agents.py lock",)),
    Row("lock-tests", ("test-designer",), ("agents.py lock", "--replace", "approval")),
    Row(
        "handoff",
        ALL_ROLES,
        ("state.py handoff", "## Done", "## Next", "## Open questions"),
    ),
    Row("resume-from-state", ALL_ROLES, ("state.py resume",)),
    Row("verify-with-evidence", ("verifier",), (".factory/gates/gate.py",)),
)
IDS = [row.name for row in ROWS]


def read(name: str) -> tuple[dict[str, object], str, str]:
    text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
    result = agents.read_yaml_front(text)
    assert not isinstance(result, str), result
    data, body = result
    return data, body, text


def section(body: str, heading: str) -> list[str]:
    lines = body.split("\n")
    assert heading in lines, f"no {heading}"
    out: list[str] = []
    for line in lines[lines.index(heading) + 1 :]:
        if line.startswith("## "):
            break
        out.append(line)
    return out


@pytest.mark.ac("E10-AC-02")
def test_the_workflow_skills_are_valid(tmp_path: Path) -> None:
    for row in ROWS:
        dest = tmp_path / ".factory" / "skills" / row.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(SKILLS / row.name, dest)
    assert [str(p) for p in agents.validate(tmp_path)] == []


# --- AC-04: the factory's conventions -----------------------------------------------------------


@pytest.mark.ac("E10-AC-04")
@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_the_description_says_what_and_when(row: Row) -> None:
    data, _, _ = read(row.name)
    description = str(data["description"])
    assert "Use when" in description
    assert not description.startswith("Use when")
    assert data["name"] == row.name
    assert "allowed-tools" not in data


@pytest.mark.ac("E10-AC-04")
@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_the_body_has_the_three_sections_in_order(row: Row) -> None:
    _, body, _ = read(row.name)
    headings = [line for line in body.split("\n") if line.startswith("## ")]
    assert headings[:3] == ["## When to use", "## Steps", "## Done when"], headings


@pytest.mark.ac("E10-AC-04")
@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_steps_are_numbered_and_done_when_is_a_list(row: Row) -> None:
    _, body, _ = read(row.name)
    steps = [line for line in section(body, "## Steps") if re.match(r"\d+\. ", line)]
    assert len(steps) >= 3, "fewer than three numbered steps"
    numbers = [int(line.split(".")[0]) for line in steps]
    assert numbers == list(range(1, len(steps) + 1))
    done = [line for line in section(body, "## Done when") if line.startswith("- ")]
    assert len(done) >= 2, "fewer than two checkable items"


@pytest.mark.ac("E10-AC-04")
@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_used_by_names_exactly_the_tables_roles(row: Row) -> None:
    _, body, _ = read(row.name)
    lines = [line for line in body.split("\n") if line.startswith("Used by:")]
    assert len(lines) == 1, "needs exactly one Used by: line"
    named = re.findall(r"`([a-z0-9-]+)`", lines[0])
    assert sorted(named) == sorted(row.used_by)


@pytest.mark.ac("E10-AC-04")
@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_the_skill_stays_under_500_lines(row: Row) -> None:
    _, _, text = read(row.name)
    assert len(text.split("\n")) < 500


# --- AC-06: the factory's real commands ---------------------------------------------------------


@pytest.mark.ac("E10-AC-06")
@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_the_skill_uses_the_factorys_commands(row: Row) -> None:
    _, body, _ = read(row.name)
    for phrase in row.phrases:
        assert phrase in body, f"{row.name} never says {phrase!r}"


@pytest.mark.ac("E10-AC-06")
def test_lock_tests_says_relocking_needs_a_human() -> None:
    _, body, _ = read("lock-tests")
    relock = [line for line in body.split("\n") if "--replace" in line]
    assert any("human" in line.lower() for line in relock), relock


# --- the cards name these skills (E10 AC-05, for T1's five) -------------------------------------


@pytest.mark.ac("E10-AC-05")
@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_every_user_role_names_the_skill_in_its_card(row: Row) -> None:
    for role in row.used_by:
        text = (CORE / f"{role}.md").read_text(encoding="utf-8")
        assert re.search(rf"skill: {re.escape(row.name)}\b", text), f"{role} doesn't name it"
