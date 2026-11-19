"""E09/T2: the eight Prove and Deliver role cards, the whole set, the hook, install, dogfooding.

Covers E09 AC-01 to AC-07 for `verifier`, the four code reviewers, `adversary`, `integrator` and
`release-manager`, and AC-08 to AC-11. The rows are the spec's table
(docs/specs/E09-core-roles.md); expectations come from the spec, the design note and ADR 0021.
"""

from __future__ import annotations

import io
import json
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

import agents
import state
from factory_installer import cli
from tests._ac import REPO_ROOT
from tests._kits import make_kit
from tests._repo import git_repo

KIT_CORE = REPO_ROOT / "kit" / ".factory" / "agents" / "core"
OWN_CORE = REPO_ROOT / ".factory" / "agents" / "core"
CORE_REL = ".factory/agents/core"

R, S, E, W, X, N = "read", "search", "edit", "write", "run", "web"
TOOLS_BY_ROLE: dict[str, tuple[str, ...]] = {
    "router": (R, S, X),
    "spec-writer": (R, S, E, W, N),
    "architect": (R, S, E, W, N),
    "test-designer": (R, S, E, W, X),
    "implementer": (R, S, E, W, X),
    "debugger": (R, S, E, W, X),
    "docs-writer": (R, S, E, W),
    "verifier": (R, S, X),
    "spec-reviewer": (R, S, X),
    "standards-reviewer": (R, S, X),
    "security-reviewer": (R, S, X),
    "perf-reviewer": (R, S, X),
    "adversary": (R, S, W, X),
    "integrator": (R, S, X),
    "release-manager": (R, S, E, W, X),
    "retro": (R, S, E, W),
}
ALL_ROLES = frozenset(TOOLS_BY_ROLE)

REVIEWER_LIMIT = [
    f"{python} .factory/{tool}"
    for tool in ("gates/gate.py", "state/state.py")
    for python in ("python", "python3", "py", "uv run python")
] + ["git diff", "git log", "git show", "git status"]
LIMITED = ("verifier", "spec-reviewer", "standards-reviewer", "security-reviewer", "perf-reviewer")


@dataclass(frozen=True)
class Row:
    name: str
    title: str
    hint: str
    different_from: str
    summary: str
    must_not: tuple[str, ...] = ()


ROWS = (
    Row(
        "verifier",
        "Verifier",
        "any",
        "",
        "Runs the gate; a claim without a report counts for nothing.",
        ("change code",),
    ),
    Row(
        "spec-reviewer",
        "Spec Reviewer",
        "different-from",
        "implementer",
        "Checks that the diff meets every acceptance criterion in the spec.",
        ("change code",),
    ),
    Row(
        "standards-reviewer",
        "Standards Reviewer",
        "different-from",
        "implementer",
        "Checks that the diff meets the house standards pack.",
        ("change code",),
    ),
    Row(
        "security-reviewer",
        "Security Reviewer",
        "different-from",
        "implementer",
        "Runs a threat check on the change.",
        ("change code",),
    ),
    Row(
        "perf-reviewer",
        "Perf Reviewer",
        "different-from",
        "implementer",
        "Checks the change against the performance budgets on hot paths.",
        ("change code",),
    ),
    Row(
        "adversary",
        "Adversary",
        "different-from",
        "implementer",
        "Writes attacks that try to break the change.",
        ("change existing code",),
    ),
    Row(
        "integrator",
        "Integrator",
        "any",
        "",
        "Commits and opens the PR with evidence and a merge-risk rating.",
        ("without approval",),
    ),
    Row(
        "release-manager",
        "Release Manager",
        "any",
        "",
        "On request, bumps the semver version, dates the changelog and tags for a human.",
    ),
)
IDS = [row.name for row in ROWS]


def card(name: str) -> tuple[dict[str, object], str]:
    parsed = state.parse((KIT_CORE / f"{name}.md").read_text(encoding="utf-8"))
    assert not isinstance(parsed, str), parsed
    return parsed


def section(body: str, heading: str) -> str:
    lines = body.split("\n")
    assert heading in lines, f"no {heading}"
    out: list[str] = []
    for line in lines[lines.index(heading) + 1 :]:
        if line.startswith("## "):
            break
        out.append(line)
    return "\n".join(out)


def items_after(text: str, label: str) -> list[str]:
    lines = text.split("\n")
    assert label in lines, f"no {label!r} line"
    items: list[str] = []
    for line in lines[lines.index(label) + 1 :]:
        if line.startswith("- "):
            items.append(line[2:])
        elif line.strip() and not line.startswith("  "):
            break
    return items


# --- AC-01 to AC-04: the files, tools, scopes and hints -----------------------------------------


@pytest.mark.ac("E09-AC-01")
def test_the_kit_ships_exactly_the_16_core_roles() -> None:
    assert {p.stem for p in KIT_CORE.glob("*.md")} == ALL_ROLES
    assert sorted(p.name for p in KIT_CORE.iterdir()) == sorted(f"{n}.md" for n in ALL_ROLES)


@pytest.mark.ac("E09-AC-01")
@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_the_role_file_exists_with_its_name_and_title(row: Row) -> None:
    data, _ = card(row.name)
    assert (data["name"], data["title"]) == (row.name, row.title)


@pytest.mark.ac("E09-AC-01")
def test_all_16_pass_agents_check(tmp_path: Path) -> None:
    shutil.copytree(KIT_CORE, tmp_path / CORE_REL)
    assert [str(p) for p in agents.validate(tmp_path)] == []


@pytest.mark.ac("E09-AC-02")
@pytest.mark.parametrize("name", sorted(ALL_ROLES))
def test_every_roles_tools_are_exactly_the_tables(name: str) -> None:
    data, _ = card(name)
    assert data["tools"] == list(TOOLS_BY_ROLE[name])


@pytest.mark.ac("E09-AC-03")
@pytest.mark.parametrize("name", LIMITED)
def test_the_verifier_and_reviewers_have_exactly_the_reviewer_limit(name: str) -> None:
    data, _ = card(name)
    assert data["scope"] == {"run": REVIEWER_LIMIT}


@pytest.mark.ac("E09-AC-03")
@pytest.mark.parametrize("name", sorted(ALL_ROLES - set(LIMITED)))
def test_no_other_role_has_a_scope(name: str) -> None:
    data, _ = card(name)
    assert "scope" not in data


@pytest.mark.ac("E09-AC-04")
@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_the_model_hint_is_the_tables(row: Row) -> None:
    data, _ = card(row.name)
    assert (data["model_hint"], data["different_from"]) == (row.hint, row.different_from)


# --- AC-05 to AC-07: the cards ------------------------------------------------------------------


@pytest.mark.ac("E09-AC-05")
@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_the_card_has_the_four_headings_and_both_lists(row: Row) -> None:
    _, body = card(row.name)
    headings = [line for line in body.split("\n") if line.startswith("## ")]
    assert headings == ["## Scope", "## Inputs", "## Outputs", "## Hand-off"]
    scope = section(body, "## Scope")
    assert items_after(scope, "Does:")
    assert items_after(scope, "Must not:")
    for heading in ("## Inputs", "## Outputs"):
        assert section(body, heading).strip()


@pytest.mark.ac("E09-AC-05")
@pytest.mark.parametrize("name", sorted(ALL_ROLES))
def test_every_hand_off_names_only_roles_that_exist(name: str) -> None:
    _, body = card(name)
    named = set(re.findall(r"`([a-z0-9-]+)`", section(body, "## Hand-off")))
    existing = {p.stem for p in KIT_CORE.glob("*.md")}
    assert named, f"{name} hands off to no role"
    assert named <= existing | {"human"}, sorted(named - existing)
    assert name not in named


@pytest.mark.ac("E09-AC-06")
@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_the_summary_is_the_blueprints_one_liner(row: Row) -> None:
    data, _ = card(row.name)
    assert data["summary"] == row.summary
    assert row.summary.endswith(".") and ". " not in row.summary


@pytest.mark.ac("E09-AC-07")
@pytest.mark.parametrize("row", [r for r in ROWS if r.must_not], ids=lambda r: r.name)
def test_the_blueprints_must_not_rules_are_stated(row: Row) -> None:
    _, body = card(row.name)
    rules = " ".join(items_after(section(body, "## Scope"), "Must not:")).lower()
    for phrase in row.must_not:
        assert phrase in rules, f"{row.name}: no {phrase!r} in its Must not: list"


# --- AC-08: held to it by the hook --------------------------------------------------------------

TASK = """+++
id = "E09-T2"
title = "A slice"
status = "in-progress"
review_round = 0
created = 2026-11-19T00:00:00Z
updated = 2026-11-19T00:00:00Z
+++

## Goal

## Acceptance criteria

## Notes
"""
LOCKED = "tests/test_locked.py"


@pytest.fixture(scope="module")
def installed(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A temp repo with the real kit installed by install.py, a source file and a locked test."""
    repo = git_repo(tmp_path_factory.mktemp("repo"))
    assert cli.main([str(repo)]) == 0
    for rel, text in {
        "src/app.py": "x = 1\n",
        LOCKED: "def test_locked() -> None:\n    assert True\n",
        ".agentic/tasks/E09-T2.md": TASK,
    }.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8", newline="\n")
    agents.lock(repo, "E09-T2", [repo / LOCKED])
    return repo


IN_BOUNDS: dict[str, tuple[str, dict[str, str]]] = {
    "read": ("Read", {"file_path": "src/app.py"}),
    "search": ("Grep", {"pattern": "x"}),
    "edit": ("Edit", {"file_path": "src/app.py"}),
    "write": ("Write", {"file_path": "src/new.py"}),
    "run": ("Bash", {"command": "git status"}),
    "web": ("WebFetch", {"url": "https://example.com"}),
}


def hook(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    role: str,
    tool_name: str,
    tool_input: dict[str, str],
) -> tuple[int, str]:
    monkeypatch.setenv("FACTORY_ROLE", role)
    payload = {"cwd": str(repo), "tool_name": tool_name, "tool_input": tool_input}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    code = agents.main(["hook", "claude-code"])
    return code, capsys.readouterr().err


@pytest.mark.ac("E09-AC-08")
@pytest.mark.parametrize("name", sorted(ALL_ROLES))
def test_done_when_every_role_gets_exactly_its_tools(
    installed: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    name: str,
) -> None:
    for tool, (tool_name, tool_input) in IN_BOUNDS.items():
        code, err = hook(installed, monkeypatch, capsys, name, tool_name, tool_input)
        expected = 0 if tool in TOOLS_BY_ROLE[name] else 2
        assert code == expected, (name, tool, err)


@pytest.mark.ac("E09-AC-08")
@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("python .factory/gates/gate.py", 0),
        ("uv run python .factory/gates/gate.py --checks format", 0),
        ("python3 .factory/state/state.py finding add E09-T2 --severity low x", 0),
        ("git diff main", 0),
        ("rm -rf build", 2),
        ("git push", 2),
        ("python .factory/gates/gate.py && rm -rf build", 2),
    ],
)
def test_done_when_a_reviewer_may_only_run_the_gate_state_and_git_reads(
    installed: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    expected: int,
) -> None:
    code, err = hook(installed, monkeypatch, capsys, "spec-reviewer", "Bash", {"command": command})
    assert code == expected, (command, err)


@pytest.mark.ac("E09-AC-08")
def test_done_when_a_reviewer_cannot_edit(
    installed: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _ = hook(installed, monkeypatch, capsys, "spec-reviewer", *IN_BOUNDS["edit"])
    assert code == 2


@pytest.mark.ac("E09-AC-08")
def test_done_when_the_implementer_cannot_edit_a_locked_test(
    installed: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, err = hook(installed, monkeypatch, capsys, "implementer", "Edit", {"file_path": LOCKED})
    assert code == 2
    assert "locked by E09-T2" in err


# --- AC-09: kit files, installed and kept on upgrade --------------------------------------------


@pytest.mark.ac("E09-AC-09")
def test_install_ships_the_16_roles_and_check_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path / "repo")
    assert cli.main([str(repo)]) == 0
    assert {p.stem for p in (repo / CORE_REL).glob("*.md")} == ALL_ROLES
    capsys.readouterr()
    assert cli.main(["check", str(repo)]) == 0, capsys.readouterr()


@pytest.mark.ac("E09-AC-09")
def test_a_repos_edit_to_a_role_is_kept_on_upgrade(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path / "repo")
    rel = f"{CORE_REL}/verifier.md"
    assert cli.main([str(repo), "--kit", str(make_kit(tmp_path, "0.1.0"))]) == 0
    local = (repo / rel).read_text(encoding="utf-8") + "\nThis repo also runs the gate on CI.\n"
    (repo / rel).write_text(local, encoding="utf-8", newline="\n")
    newer = (KIT_CORE / "verifier.md").read_bytes() + b"\nA newer kit line.\n"
    kit2 = make_kit(tmp_path, "0.2.0", {rel: newer})
    capsys.readouterr()
    assert cli.main([str(repo), "--kit", str(kit2), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert rel in report["files"]["kept"]
    assert (repo / rel).read_text(encoding="utf-8") == local
    assert (repo / f"{rel}.factory-new").read_bytes() == newer
    assert [str(p) for p in agents.validate(repo)] == []


# --- AC-10: this repo uses the roles ------------------------------------------------------------


@pytest.mark.ac("E09-AC-10")
def test_this_repos_install_holds_the_kits_16_roles() -> None:
    assert {p.name for p in OWN_CORE.glob("*.md")} == {p.name for p in KIT_CORE.glob("*.md")}
    for path in KIT_CORE.glob("*.md"):
        assert (OWN_CORE / path.name).read_bytes() == path.read_bytes(), path.name
    assert [str(p) for p in agents.validate(REPO_ROOT)] == []
