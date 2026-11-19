"""E10/T2: six Specify, Make and Deliver skills, and a fixture run for each.

Covers E10 AC-04, AC-05 and AC-06 for `spec-interview`, `design-note`, `debugging`,
`dependency-bump`, `retro` and `release`, and AC-07 (their fixture runs). The rows are the spec's
table (docs/specs/E10-skills-library.md). A fixture run is `tests/fixtures/skills/<name>/`:
`before/`, `after/` and `RUN.md` (design note, test seams).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

import agents
import docs
import state
from tests._ac import REPO_ROOT

KIT = REPO_ROOT / "kit" / ".factory"
SKILLS = KIT / "skills"
CORE = KIT / "agents" / "core"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "skills"


@dataclass(frozen=True)
class Row:
    name: str
    used_by: tuple[str, ...]
    phrases: tuple[str, ...]


ROWS = (
    Row(
        "spec-interview",
        ("spec-writer",),
        (".factory/workflow/templates/spec.md", "docs.py check", "AC-"),
    ),
    Row(
        "design-note",
        ("architect",),
        (
            ".factory/workflow/templates/design.md",
            ".factory/workflow/templates/adr.md",
            "docs.py check",
            "state.py task new",
        ),
    ),
    Row("debugging", ("debugger",), ("root cause", "regression test", "hypothesis")),
    Row("dependency-bump", ("router", "implementer"), ("one dependency", "gate.py")),
    Row("retro", ("retro",), ("Draft", "finding")),
    Row("release", ("release-manager",), ("semver", "Unreleased", "tag")),
)
IDS = [row.name for row in ROWS]


def read(name: str) -> tuple[dict[str, object], str, str]:
    text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
    result = agents.read_yaml_front(text)
    assert not isinstance(result, str), result
    return result[0], result[1], text


def section(body: str, heading: str) -> list[str]:
    lines = body.split("\n")
    assert heading in lines, f"no {heading}"
    out: list[str] = []
    for line in lines[lines.index(heading) + 1 :]:
        if line.startswith("## "):
            break
        out.append(line)
    return out


def steps(body: str) -> list[str]:
    return [line for line in section(body, "## Steps") if re.match(r"\d+\. ", line)]


# --- AC-04 to AC-06: the skills -----------------------------------------------------------------


@pytest.mark.ac("E10-AC-02")
def test_these_skills_are_valid(tmp_path: Path) -> None:
    for row in ROWS:
        shutil.copytree(SKILLS / row.name, tmp_path / ".factory" / "skills" / row.name)
    assert [str(p) for p in agents.validate(tmp_path)] == []


@pytest.mark.ac("E10-AC-04")
@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_the_conventions_hold(row: Row) -> None:
    data, body, text = read(row.name)
    assert data["name"] == row.name
    description = str(data["description"])
    assert "Use when" in description and not description.startswith("Use when")
    assert "allowed-tools" not in data
    headings = [line for line in body.split("\n") if line.startswith("## ")]
    assert headings[:3] == ["## When to use", "## Steps", "## Done when"], headings
    numbered = steps(body)
    assert len(numbered) >= 3
    assert [int(s.split(".")[0]) for s in numbered] == list(range(1, len(numbered) + 1))
    assert len([x for x in section(body, "## Done when") if x.startswith("- ")]) >= 2
    used = [line for line in body.split("\n") if line.startswith("Used by:")]
    assert len(used) == 1
    assert sorted(re.findall(r"`([a-z0-9-]+)`", used[0])) == sorted(row.used_by)
    assert len(text.split("\n")) < 500


@pytest.mark.ac("E10-AC-05")
@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_every_user_role_names_the_skill_in_its_card(row: Row) -> None:
    for role in row.used_by:
        text = (CORE / f"{role}.md").read_text(encoding="utf-8")
        assert re.search(rf"skill: {re.escape(row.name)}\b", text), f"{role} doesn't name it"


@pytest.mark.ac("E10-AC-06")
@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_the_skill_uses_the_factorys_commands_and_words(row: Row) -> None:
    _, body, _ = read(row.name)
    for phrase in row.phrases:
        assert phrase in body, f"{row.name} never says {phrase!r}"


# --- AC-07: a fixture run for each --------------------------------------------------------------


@pytest.mark.ac("E10-AC-07")
@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_the_fixture_run_follows_every_step(row: Row) -> None:
    """RUN.md records the run step by step: one numbered entry per step of the skill."""
    folder = FIXTURES / row.name
    assert (folder / "before").is_dir() and (folder / "after").is_dir()
    run = (folder / "RUN.md").read_text(encoding="utf-8")
    assert run.startswith(f"# Fixture run: {row.name}\n")
    _, body, _ = read(row.name)
    recorded = [line for line in run.split("\n") if re.match(r"\d+\. ", line)]
    assert len(recorded) == len(steps(body)), "one RUN.md entry per skill step"


def _copy(row: str, side: str, dest: Path) -> Path:
    shutil.copytree(FIXTURES / row / side, dest)
    return dest


@pytest.mark.ac("E10-AC-07")
def test_spec_interview_produces_a_spec_that_passes_the_linter(tmp_path: Path) -> None:
    before = _copy("spec-interview", "before", tmp_path / "before")
    after = _copy("spec-interview", "after", tmp_path / "after")
    assert not list((before / "docs" / "specs").glob("*.md"))
    specs = list((after / "docs" / "specs").glob("*.md"))
    assert len(specs) == 1
    checked = docs.validate(after)
    assert (checked.count, [str(p) for p in checked]) == (1, [])
    assert len(re.findall(r"^- \*\*AC-\d\d\*\*", specs[0].read_text("utf-8"), re.M)) >= 3


@pytest.mark.ac("E10-AC-07")
def test_design_note_produces_a_design_adr_and_tasks(tmp_path: Path) -> None:
    after = _copy("design-note", "after", tmp_path / "after")
    checked = docs.validate(after)
    assert [str(p) for p in checked] == []
    kinds = {p.parent.name for p in (after / "docs").rglob("*.md")}
    assert {"specs", "design", "adr"} <= kinds
    assert [str(p) for p in state.validate(after)] == []
    assert len(list((after / ".agentic" / "tasks").glob("*.md"))) >= 1


def _pytest(repo: Path) -> int:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:randomly"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "", "PYTHONPATH": str(repo / "src"), "PYTHONDONTWRITEBYTECODE": "1"},
    )
    return result.returncode


@pytest.mark.ac("E10-AC-07")
def test_debugging_turns_red_to_green_with_a_regression_test(tmp_path: Path) -> None:
    before = _copy("debugging", "before", tmp_path / "before")
    after = _copy("debugging", "after", tmp_path / "after")
    for repo in (before, after):
        (repo / "pytest.ini").write_text("[pytest]\naddopts =\n", encoding="utf-8")
    assert _pytest(before) != 0, "the bug must make before/ red"
    assert _pytest(after) == 0, "the fix must make after/ green"
    names = {p.name for p in (before / "tests").glob("test_*.py")}
    new_tests = [p for p in (after / "tests").glob("test_*.py") if p.name not in names]
    added = len(re.findall(r"^def test_", "".join(p.read_text("utf-8") for p in new_tests), re.M))
    old = sum(
        len(re.findall(r"^def test_", (after / "tests" / n).read_text("utf-8"), re.M))
        - len(re.findall(r"^def test_", (before / "tests" / n).read_text("utf-8"), re.M))
        for n in names
    )
    assert added + old >= 1, "no regression test was added"


@pytest.mark.ac("E10-AC-07")
def test_dependency_bump_changes_exactly_one_dependency(tmp_path: Path) -> None:
    before = (FIXTURES / "dependency-bump" / "before" / "pyproject.toml").read_text("utf-8")
    after = (FIXTURES / "dependency-bump" / "after" / "pyproject.toml").read_text("utf-8")
    changed = [(b, a) for b, a in zip(before.split("\n"), after.split("\n"), strict=True) if b != a]
    assert len(changed) == 1, changed
    old, new = changed[0]
    assert old.split(">=")[0] == new.split(">=")[0], "the same dependency, a new version"
    root = _copy("dependency-bump", "after", tmp_path / "after")
    assert [str(p) for p in state.validate(root)] == []
    handoffs = list((root / ".agentic" / "handoffs").glob("*.md"))
    assert len(handoffs) == 1
    assert "**PASS**" in handoffs[0].read_text("utf-8")


@pytest.mark.ac("E10-AC-07")
def test_retro_turns_a_recurring_finding_into_a_draft_spec(tmp_path: Path) -> None:
    before = _copy("retro", "before", tmp_path / "before")
    after = _copy("retro", "after", tmp_path / "after")
    assert [str(p) for p in state.validate(before)] == []
    findings: list[object] = []
    for path in (before / ".agentic" / "tasks").glob("*.md"):
        parsed = state.parse(path.read_text("utf-8"))
        assert not isinstance(parsed, str), parsed
        listed = parsed[0].get("findings")
        findings += listed if isinstance(listed, list) else []
    assert len(findings) >= 2, "a retro needs a recurring finding to work from"
    checked = docs.validate(after)
    assert [str(p) for p in checked] == []
    drafts = [
        p
        for p in (after / "docs" / "specs").glob("*.md")
        if "Status: **Draft" in p.read_text("utf-8")
    ]
    assert len(drafts) == 1


@pytest.mark.ac("E10-AC-07")
def test_release_bumps_semver_and_dates_the_changelog(tmp_path: Path) -> None:
    before = FIXTURES / "release" / "before"
    after = FIXTURES / "release" / "after"
    assert (before / "VERSION").read_text("utf-8").strip() == "0.1.0"
    assert (after / "VERSION").read_text("utf-8").strip() == "0.2.0"  # an Added entry: minor
    log_before = (before / "CHANGELOG.md").read_text("utf-8")
    log_after = (after / "CHANGELOG.md").read_text("utf-8")
    unreleased = log_before.split("## [Unreleased]")[1].split("\n## ")[0]
    assert "### Added" in unreleased
    assert re.search(r"^## \[0\.2\.0\] - \d{4}-\d\d-\d\d$", log_after, re.M)
    after_unreleased = log_after.split("## [Unreleased]")[1].split("\n## ")[0]
    assert not after_unreleased.strip(), "Unreleased must be empty after the release"
    released = log_after.split("## [0.2.0]")[1].split("\n## [")[0]
    for line in unreleased.strip().split("\n"):
        assert line in released, f"{line!r} was lost"
