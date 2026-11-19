"""E10/T3: five review skills and their fixture runs, the exercise record, and the whole library.

Covers E10 AC-04 to AC-06 for `spec-review`, `standards-review`, `threat-check`, `perf-budget` and
`adversarial-testing`; AC-07's record; AC-01, AC-05 for the whole set, AC-08 and AC-09. The rows
are the spec's table (docs/specs/E10-skills-library.md).
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

import agents
import state
from factory_installer import cli
from tests._ac import REPO_ROOT
from tests._kits import make_kit
from tests._repo import git_repo

KIT = REPO_ROOT / "kit" / ".factory"
SKILLS = KIT / "skills"
OWN_SKILLS = REPO_ROOT / ".factory" / "skills"
CORE = KIT / "agents" / "core"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "skills"
SKILLS_REL = ".factory/skills"

ALL_SKILLS = frozenset(
    {
        "spec-interview",
        "design-note",
        "tdd-slices",
        "lock-tests",
        "handoff",
        "resume-from-state",
        "verify-with-evidence",
        "spec-review",
        "standards-review",
        "threat-check",
        "perf-budget",
        "adversarial-testing",
        "debugging",
        "retro",
        "release",
        "dependency-bump",
    }
)
NOT_YET = frozenset({"pull-request-evidence"})  # E08 ships it (spec AC-05)

# AC-07: how each skill was exercised. Live entries name the PR and commits that followed it.
EXERCISED: dict[str, tuple[str, str]] = {
    "resume-from-state": ("live", "#64: 228e005; T3: 54cdb25"),
    "tdd-slices": ("live", "#64: a512e7f"),
    "lock-tests": ("live", "#64: a512e7f"),
    "verify-with-evidence": ("live", "#64: full gate on 4b669d4"),
    "handoff": ("live", "#63: dde7f2b; #64: 2acf979"),
    "spec-interview": ("fixture", ""),
    "design-note": ("fixture", ""),
    "debugging": ("fixture", ""),
    "dependency-bump": ("fixture", ""),
    "retro": ("fixture", ""),
    "release": ("fixture", ""),
    "spec-review": ("fixture", ""),
    "standards-review": ("fixture", ""),
    "threat-check": ("fixture", ""),
    "perf-budget": ("fixture", ""),
    "adversarial-testing": ("fixture", ""),
}


@dataclass(frozen=True)
class Row:
    name: str
    used_by: tuple[str, ...]
    phrases: tuple[str, ...]


REVIEW = ("state.py finding add", "blocker", "major", "minor")
ROWS = (
    Row("spec-review", ("spec-reviewer",), (*REVIEW, "AC-")),
    Row("standards-review", ("standards-reviewer",), (*REVIEW, ".factory/standards/", "rule id")),
    Row("threat-check", ("security-reviewer",), (*REVIEW, "secret", "input")),
    Row("perf-budget", ("perf-reviewer",), (*REVIEW, "budget", "hot path")),
    Row("adversarial-testing", ("adversary",), (*REVIEW, "new file")),
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


# --- AC-04 to AC-06: the five review skills -----------------------------------------------------


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


@pytest.mark.ac("E10-AC-06")
@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_the_review_skill_records_findings_with_state_py(row: Row) -> None:
    _, body, _ = read(row.name)
    for phrase in row.phrases:
        assert phrase in body, f"{row.name} never says {phrase!r}"


# --- AC-07: fixture runs for the five, and the record -------------------------------------------


@pytest.mark.ac("E10-AC-07")
@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_the_fixture_run_follows_every_step(row: Row) -> None:
    folder = FIXTURES / row.name
    assert (folder / "before").is_dir() and (folder / "after").is_dir()
    run = (folder / "RUN.md").read_text(encoding="utf-8")
    assert run.startswith(f"# Fixture run: {row.name}\n")
    _, body, _ = read(row.name)
    recorded = [line for line in run.split("\n") if re.match(r"\d+\. ", line)]
    assert len(recorded) == len(steps(body))


def _findings(root: Path) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    for path in sorted((root / ".agentic" / "tasks").glob("*.md")):
        parsed = state.parse(path.read_text("utf-8"))
        assert not isinstance(parsed, str), parsed
        listed = parsed[0].get("findings")
        found += [f for f in listed if isinstance(f, dict)] if isinstance(listed, list) else []
    return found


@pytest.mark.ac("E10-AC-07")
@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_the_review_adds_valid_open_findings_with_a_location(tmp_path: Path, row: Row) -> None:
    before = shutil.copytree(FIXTURES / row.name / "before", tmp_path / "before")
    after = shutil.copytree(FIXTURES / row.name / "after", tmp_path / "after")
    assert [str(p) for p in state.validate(before)] == []
    assert [str(p) for p in state.validate(after)] == []
    new = [f for f in _findings(after) if f not in _findings(before)]
    assert new, "the review recorded no finding"
    for finding in new:
        assert finding["status"] == "open"
        assert re.search(r"[\w./-]+\.\w+:\d+", str(finding["summary"])), "no file:line"


def _new_summaries(row: str) -> str:
    after = FIXTURES / row / "after"
    before = FIXTURES / row / "before"
    return " ".join(str(f["summary"]) for f in _findings(after) if f not in _findings(before))


@pytest.mark.ac("E10-AC-07")
def test_spec_review_names_the_unmet_ac() -> None:
    summaries = _new_summaries("spec-review")
    assert re.search(r"AC-\d\d", summaries)


@pytest.mark.ac("E10-AC-07")
def test_standards_review_cites_rule_ids_from_the_pack() -> None:
    pack = "\n".join(
        p.read_text("utf-8")
        for p in (FIXTURES / "standards-review" / "before" / ".factory" / "standards").rglob("*.md")
    )
    cited = re.findall(r"\b[A-Z]{2,}-\d{3}\b", _new_summaries("standards-review"))
    assert cited, "no rule id cited"
    assert all(rule in pack for rule in cited), cited


@pytest.mark.ac("E10-AC-07")
def test_threat_check_rates_the_injection_a_blocker() -> None:
    after = FIXTURES / "threat-check" / "after"
    before = FIXTURES / "threat-check" / "before"
    new = [f for f in _findings(after) if f not in _findings(before)]
    assert any(f["severity"] == "blocker" for f in new), new


@pytest.mark.ac("E10-AC-07")
def test_perf_budget_cites_the_budget_it_breaks() -> None:
    budgets = (FIXTURES / "perf-budget" / "before" / "docs" / "perf-budgets.md").read_text("utf-8")
    names = re.findall(r"^\| `([a-z_.]+)` \|", budgets, re.M)
    assert names
    assert any(name in _new_summaries("perf-budget") for name in names)


@pytest.mark.ac("E10-AC-07")
def test_adversarial_testing_only_adds_new_files() -> None:
    before = FIXTURES / "adversarial-testing" / "before"
    after = FIXTURES / "adversarial-testing" / "after"
    old = {
        p.relative_to(before).as_posix(): p.read_bytes() for p in before.rglob("*") if p.is_file()
    }
    new = {p.relative_to(after).as_posix(): p.read_bytes() for p in after.rglob("*") if p.is_file()}
    changed = sorted(rel for rel in old if rel in new and old[rel] != new[rel])
    assert changed == [".agentic/tasks/E01-T1.md"], "only the task file may change"
    assert set(old) <= set(new)
    added = sorted(set(new) - set(old))
    assert added and all(re.fullmatch(r"tests/test_attack_\w+\.py", rel) for rel in added), added


@pytest.mark.ac("E10-AC-07")
def test_done_when_every_skill_is_exercised_and_recorded() -> None:
    assert set(EXERCISED) == ALL_SKILLS
    for name, (how, where) in EXERCISED.items():
        assert how in {"live", "fixture"}, name
        if how == "live":
            assert re.search(r"#\d+: [0-9a-f]{7}", where), (name, where)
        else:
            assert (FIXTURES / name / "RUN.md").is_file(), name


# --- AC-01 and AC-05: the whole library ---------------------------------------------------------


@pytest.mark.ac("E10-AC-01")
def test_the_kit_ships_exactly_the_16_skills() -> None:
    assert sorted(p.name for p in SKILLS.iterdir()) == sorted(ALL_SKILLS)
    assert all((SKILLS / name / "SKILL.md").is_file() for name in ALL_SKILLS)


@pytest.mark.ac("E10-AC-01")
def test_all_16_pass_agents_check(tmp_path: Path) -> None:
    shutil.copytree(SKILLS, tmp_path / SKILLS_REL)
    assert [str(p) for p in agents.validate(tmp_path)] == []


@pytest.mark.ac("E10-AC-05")
def test_every_skill_a_card_names_exists() -> None:
    named = set()
    for card in CORE.glob("*.md"):
        named |= set(re.findall(r"skill: ([a-z0-9-]+)", card.read_text("utf-8")))
    assert named - ALL_SKILLS <= NOT_YET, sorted(named - ALL_SKILLS)
    assert named >= ALL_SKILLS, sorted(ALL_SKILLS - named)


@pytest.mark.ac("E10-AC-05")
@pytest.mark.parametrize("name", sorted(ALL_SKILLS))
def test_every_used_by_role_names_the_skill(name: str) -> None:
    _, body, _ = read(name)
    used = next(line for line in body.split("\n") if line.startswith("Used by:"))
    roles = re.findall(r"`([a-z0-9-]+)`", used)
    assert roles
    for role in roles:
        text = (CORE / f"{role}.md").read_text("utf-8")
        assert re.search(rf"skill: {re.escape(name)}\b", text), (name, role)


@pytest.mark.ac("E10-AC-05")
@pytest.mark.parametrize("name", ["handoff", "resume-from-state"])
def test_every_role_names_the_session_skills(name: str) -> None:
    for card in CORE.glob("*.md"):
        assert re.search(rf"skill: {name}\b", card.read_text("utf-8")), card.name


# --- AC-08 and AC-09: installed, kept on upgrade, dogfooded -------------------------------------


@pytest.mark.ac("E10-AC-08")
def test_install_ships_the_16_skills_and_check_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path / "repo")
    assert cli.main([str(repo)]) == 0
    assert {p.name for p in (repo / SKILLS_REL).iterdir()} == ALL_SKILLS
    capsys.readouterr()
    assert cli.main(["check", str(repo)]) == 0, capsys.readouterr()


@pytest.mark.ac("E10-AC-08")
def test_a_repos_edit_to_a_skill_is_kept_on_upgrade(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path / "repo")
    rel = f"{SKILLS_REL}/debugging/SKILL.md"
    assert cli.main([str(repo), "--kit", str(make_kit(tmp_path, "0.1.0"))]) == 0
    local = (repo / rel).read_text("utf-8") + "\nOur team also bisects with git bisect.\n"
    (repo / rel).write_text(local, encoding="utf-8", newline="\n")
    newer = (SKILLS / "debugging" / "SKILL.md").read_bytes() + b"\nA newer kit line.\n"
    capsys.readouterr()
    assert (
        cli.main([str(repo), "--kit", str(make_kit(tmp_path, "0.2.0", {rel: newer})), "--json"])
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert rel in report["files"]["kept"]
    assert (repo / rel).read_text("utf-8") == local
    assert (repo / f"{rel}.factory-new").read_bytes() == newer
    assert [str(p) for p in agents.validate(repo)] == []


@pytest.mark.ac("E10-AC-09")
def test_this_repos_install_holds_the_kits_16_skills() -> None:
    assert {p.name for p in OWN_SKILLS.iterdir()} == ALL_SKILLS
    for name in ALL_SKILLS:
        own, kit = OWN_SKILLS / name / "SKILL.md", SKILLS / name / "SKILL.md"
        assert own.read_bytes() == kit.read_bytes(), name
    assert [str(p) for p in agents.validate(REPO_ROOT)] == []
