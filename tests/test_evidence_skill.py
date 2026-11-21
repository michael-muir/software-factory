"""E08/T5: the `pull-request-evidence` skill, the Integrator card naming it, and E08's coverage.

Covers E08 AC-16 and AC-20. Expectations come from the E08 spec, the design note and E10's skill
conventions (E10 AC-02, AC-04, AC-05), not from the implementation. AC-17's exercise record lives
in E10's `tests/test_skills_prove.py`.
"""

from __future__ import annotations

import ast
import re
import shutil
import sys
from pathlib import Path

import pytest

import agents
from tests._ac import COLLECTED_AC_IDS, REPO_ROOT, spec_ac_ids
from tests._repo import KIT_FILES

KIT = REPO_ROOT / "kit" / ".factory"
NAME = "pull-request-evidence"
SKILL = KIT / "skills" / NAME / "SKILL.md"
INTEGRATOR = KIT / "agents" / "core" / "integrator.md"


def _read() -> tuple[dict[str, object], str, str]:
    text = SKILL.read_text(encoding="utf-8")
    result = agents.read_yaml_front(text)
    assert not isinstance(result, str), result
    return result[0], result[1], text


def _section(body: str, heading: str) -> list[str]:
    lines = body.split("\n")
    assert heading in lines, f"no {heading}"
    out: list[str] = []
    for line in lines[lines.index(heading) + 1 :]:
        if line.startswith("## "):
            break
        out.append(line)
    return out


def _steps(body: str) -> list[str]:
    """Each numbered step, with the lines under it."""
    found: list[str] = []
    for line in _section(body, "## Steps"):
        if re.match(r"\d+\. ", line):
            found.append(line)
        elif found and line.strip():
            found[-1] += "\n" + line
    return found


# --- AC-16: the skill ---------------------------------------------------------------------------


@pytest.mark.ac("E08-AC-16")
def test_the_kit_ships_the_skill_and_it_is_valid(tmp_path: Path) -> None:
    assert SKILL.is_file()
    target = tmp_path / ".factory" / "skills" / NAME
    shutil.copytree(SKILL.parent, target)
    assert [str(p) for p in agents.validate(tmp_path)] == []


@pytest.mark.ac("E08-AC-16")
def test_the_skill_follows_the_e10_conventions() -> None:
    data, body, text = _read()
    assert data["name"] == NAME
    description = str(data["description"])
    assert "Use when" in description and not description.startswith("Use when")
    assert "allowed-tools" not in data
    headings = [line for line in body.split("\n") if line.startswith("## ")]
    assert headings[:3] == ["## When to use", "## Steps", "## Done when"], headings
    numbered = _steps(body)
    assert len(numbered) >= 3
    assert [int(s.split(".")[0]) for s in numbered] == list(range(1, len(numbered) + 1))
    assert len([x for x in _section(body, "## Done when") if x.startswith("- ")]) >= 2
    used = [line for line in body.split("\n") if line.startswith("Used by:")]
    assert len(used) == 1
    assert re.findall(r"`([a-z0-9-]+)`", used[0]) == ["integrator"]
    assert len(text.split("\n")) < 500


@pytest.mark.ac("E08-AC-16")
def test_the_steps_gate_draft_fill_check_and_open_in_that_order() -> None:
    steps = _steps(_read()[1])
    marks = [
        ".factory/gates/gate.py --json-out",
        ".factory/workflow/evidence.py",
        "TODO(author)",
        "check-pr --strict",
        "open the PR",
    ]
    where = []
    for mark in marks:
        holding = [i for i, step in enumerate(steps) if mark.lower() in step.lower()]
        assert holding, f"no step says {mark!r}"
        where.append(holding[0])
    assert where == sorted(where), dict(zip(marks, where, strict=True))


@pytest.mark.ac("E08-AC-16")
def test_the_skill_says_why_a_dirty_tree_and_a_rebase_matter() -> None:
    body = _read()[1]
    assert "uncommitted" in body
    assert "--commits" in body
    assert "patch-id" in body


@pytest.mark.ac("E08-AC-16")
def test_the_integrator_card_names_the_skill_and_the_commands() -> None:
    card = INTEGRATOR.read_text(encoding="utf-8")
    assert re.search(r"skill: pull-request-evidence\b", card)
    does = card.split("Does:", 1)[1].split("Must not:", 1)[0]
    assert "evidence.py" in does
    assert "check-pr --strict" in does


@pytest.mark.ac("E08-AC-16")
def test_every_skill_a_card_names_now_exists_with_no_exception() -> None:
    shipped = {p.name for p in (KIT / "skills").iterdir() if (p / "SKILL.md").is_file()}
    named: set[str] = set()
    for card in (KIT / "agents" / "core").glob("*.md"):
        named |= set(re.findall(r"skill: ([a-z0-9-]+)", card.read_text("utf-8")))
    assert named - shipped == set()
    assert NAME in shipped


@pytest.mark.ac("E08-AC-16")
def test_this_repos_install_holds_the_kits_skill() -> None:
    own = REPO_ROOT / ".factory" / "skills" / NAME / "SKILL.md"
    assert own.read_bytes() == SKILL.read_bytes()


# --- AC-20: quality and coverage ----------------------------------------------------------------


@pytest.mark.ac("E08-AC-20")
def test_the_e08_spec_defines_ac_01_to_ac_20() -> None:
    assert spec_ac_ids("E08") == {f"E08-AC-{n:02d}" for n in range(1, 21)}


@pytest.mark.ac("E08-AC-20")
def test_every_e08_ac_has_a_test_but_the_live_ones(request: pytest.FixtureRequest) -> None:
    missing = spec_ac_ids("E08") - request.config.stash[COLLECTED_AC_IDS]
    assert missing <= {"E08-AC-17", "E08-AC-19"}, f"E08 ACs with no test: {sorted(missing)}"


@pytest.mark.ac("E08-AC-20")
def test_evidence_py_is_standard_library_only() -> None:
    tree = ast.parse((KIT / "workflow" / "evidence.py").read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
    foreign = sorted({n.split(".")[0] for n in names} - set(sys.stdlib_module_names))
    assert not foreign, foreign


@pytest.mark.ac("E08-AC-20")
def test_the_kit_layout_lists_e08s_kit_files() -> None:
    assert ".factory/workflow/evidence.py" in KIT_FILES
    assert f".factory/skills/{NAME}/SKILL.md" in KIT_FILES
