"""E10/T1: validating skills in the Agent Skills format, in agents.py (ADR 0022).

Covers E10 AC-02 and AC-03. Expectations come from the E10 spec, the Agent Skills specification
(agentskills.io/specification), the design note and ADR 0022, not from the implementation.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import agents
from factory_installer import cli
from tests._ac import REPO_ROOT
from tests._gate import PASS, gate_repo, profile, run_gate, touches

KIT = REPO_ROOT / "kit" / ".factory"
SKILLS_REL = ".factory/skills"

VALID_STATE = """+++
phase = "build"
track = "full"
active_task = ""
blockers = []
updated = 2026-11-19T00:00:00Z
+++
"""
BODY = "\n# A skill\n\nDo the thing.\n"


def skill(name: str = "pdf-tools", front: str | None = None, body: str = BODY) -> str:
    if front is None:
        front = f"name: {name}\ndescription: Works with PDFs. Use when a PDF is involved."
    return f"---\n{front}\n---\n{body}"


def write(root: Path, files: dict[str, str]) -> Path:
    state = root / ".agentic" / "STATE.md"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(VALID_STATE, encoding="utf-8", newline="\n")
    for rel, text in files.items():
        path = root / SKILLS_REL / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return root


def problems(root: Path) -> list[str]:
    return [str(p) for p in agents.validate(root)]


def at(root: Path, where: str, folder: str = "pdf-tools") -> list[str]:
    prefix = f"{SKILLS_REL}/{folder}/SKILL.md: {where}: "
    return [p for p in problems(root) if p.startswith(prefix)]


# --- AC-02: valid skills ------------------------------------------------------------------------


@pytest.mark.ac("E10-AC-02")
def test_a_minimal_skill_is_valid(tmp_path: Path) -> None:
    assert problems(write(tmp_path, {"pdf-tools/SKILL.md": skill()})) == []


@pytest.mark.ac("E10-AC-02")
def test_every_standard_field_in_the_subset_is_valid(tmp_path: Path) -> None:
    front = "\n".join(
        [
            "# a comment",
            "name: pdf-tools",
            "description: 'Extracts text: tables too. Use when a PDF is involved.'",
            'license: "Apache-2.0"',
            "",
            "compatibility: Requires Python 3.11+",
            "metadata:",
            "  author: example-org",
            '  version: "1.0"',
            "allowed-tools: Read Bash(git:*)",
        ]
    )
    assert problems(write(tmp_path, {"pdf-tools/SKILL.md": skill(front=front)})) == []


@pytest.mark.ac("E10-AC-02")
def test_the_reader_returns_the_fields_and_the_body() -> None:
    front = 'name: pdf-tools\ndescription: "Say \\"hi\\". Use when greeting."\nmetadata:\n  a: b'
    result = agents.read_yaml_front(skill(front=front))
    assert not isinstance(result, str), result
    data, body = result
    assert data == {
        "name": "pdf-tools",
        "description": 'Say "hi". Use when greeting.',
        "metadata": {"a": "b"},
    }
    assert body == BODY


@pytest.mark.ac("E10-AC-02")
def test_files_other_than_skill_md_and_deeper_folders_are_not_checked(tmp_path: Path) -> None:
    root = write(
        tmp_path,
        {
            "pdf-tools/SKILL.md": skill(),
            "pdf-tools/references/REFERENCE.md": "---\nbroken: [\n---\n",
            "pdf-tools/scripts/run.py": "print('x')\n",
            "deep/inner/SKILL.md": "not a skill\n",
            "README.md": "skills\n",
        },
    )
    (root / SKILLS_REL / ".gitkeep").write_text("", encoding="utf-8")
    assert problems(root) == []


@pytest.mark.ac("E10-AC-02")
def test_a_repo_without_skills_has_no_skill_problems(tmp_path: Path) -> None:
    assert problems(write(tmp_path, {})) == []


# --- AC-02: invalid skills ----------------------------------------------------------------------

LONG = "x" * 1025


@pytest.mark.ac("E10-AC-02")
@pytest.mark.parametrize(
    ("front", "where"),
    [
        ("description: Does it. Use when needed.", "name"),
        ("name: pdf-tools", "description"),
        ("name: pdf-tools\ndescription: ''", "description"),
        (f"name: pdf-tools\ndescription: {LONG}", "description"),
        ("name: PDF-tools\ndescription: d. Use when x.", "name"),
        ("name: -pdf-tools\ndescription: d. Use when x.", "name"),
        ("name: pdf-tools-\ndescription: d. Use when x.", "name"),
        ("name: pdf--tools\ndescription: d. Use when x.", "name"),
        ("name: pdf_tools\ndescription: d. Use when x.", "name"),
        ("name: other-tool\ndescription: d. Use when x.", "name"),
        (f"name: {'a' * 65}\ndescription: d. Use when x.", "name"),
        ("name: pdf-tools\ndescription: d. Use when x.\ncompatibility: ''", "compatibility"),
        (f"name: pdf-tools\ndescription: d.\ncompatibility: {'c' * 501}", "compatibility"),
        ("name: pdf-tools\ndescription: d. Use when x.\nversion: 1.0", "version"),
        ("name: pdf-tools\ndescription: d. Use when x.\nmetadata: flat", "metadata"),
        ("name: pdf-tools\nname: pdf-tools\ndescription: d. Use when x.", "name"),
    ],
)
def test_invalid_fields_are_reported_by_field(tmp_path: Path, front: str, where: str) -> None:
    root = write(tmp_path, {"pdf-tools/SKILL.md": skill(front=front)})
    assert at(root, where), problems(root)


@pytest.mark.ac("E10-AC-02")
def test_a_name_of_exactly_64_characters_is_valid(tmp_path: Path) -> None:
    name = "a" * 64
    root = write(tmp_path, {f"{name}/SKILL.md": skill(name)})
    assert problems(root) == []


@pytest.mark.ac("E10-AC-02")
@pytest.mark.parametrize(
    "text",
    [
        "# No front matter\n",
        "---\nname: pdf-tools\ndescription: never closed\n",
        "\n---\nname: pdf-tools\ndescription: d. Use when x.\n---\n",
    ],
)
def test_missing_or_unclosed_front_matter_is_a_problem(tmp_path: Path, text: str) -> None:
    root = write(tmp_path, {"pdf-tools/SKILL.md": text})
    assert at(root, "front matter"), problems(root)


@pytest.mark.ac("E10-AC-02")
@pytest.mark.parametrize(
    ("front", "line"),
    [
        ("name: pdf-tools\ndescription: |\n  Block scalar.", 2),
        ("name: pdf-tools\ndescription: >\n  Folded.", 2),
        ("name: pdf-tools\ndescription: d. Use when x.\nallowed-tools:\n  - Read", 3),
        ("name: pdf-tools\ndescription: [a, b]", 2),
        ("name: pdf-tools\ndescription: {a: b}", 2),
        ("name: pdf-tools\ndescription: d. Use when x.\nmetadata:\n  deep:\n    key: v", 4),
        ("name: pdf-tools\n\tdescription: tabbed", 2),
        ("name: &anchor pdf-tools\ndescription: d. Use when x.", 1),
        ("just a line\nname: pdf-tools", 1),
        ("name: 'unclosed\ndescription: d. Use when x.", 1),
    ],
)
def test_yaml_outside_the_subset_is_reported_not_parsed(
    tmp_path: Path, front: str, line: int
) -> None:
    root = write(tmp_path, {"pdf-tools/SKILL.md": skill(front=front)})
    found = at(root, "front matter")
    assert found, problems(root)
    assert f"unsupported YAML on line {line}" in found[0], found


@pytest.mark.ac("E10-AC-02")
def test_the_reader_never_raises_on_bad_input() -> None:
    for text in ("", "---", "---\n---", "---\n: x\n---\n", "---\n'\n---\n", "﻿---\n"):
        result = agents.read_yaml_front(text)
        assert isinstance(result, (str, tuple))


# --- AC-03: the CLI, the gate and install.py check ----------------------------------------------


@pytest.mark.ac("E10-AC-03")
def test_agents_check_reports_skill_problems(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write(tmp_path, {"pdf-tools/SKILL.md": skill(front="name: pdf-tools")})
    monkeypatch.chdir(root)
    assert agents.main(["check"]) == 1
    assert f"{SKILLS_REL}/pdf-tools/SKILL.md: description: " in capsys.readouterr().out


@pytest.mark.ac("E10-AC-03")
def test_agents_check_passes_valid_skills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write(tmp_path, {"pdf-tools/SKILL.md": skill()})
    monkeypatch.chdir(root)
    assert agents.main(["check"]) == 0, capsys.readouterr()


def _gated(tmp_path: Path, text: str) -> Path:
    repo = gate_repo(
        tmp_path / "repo",
        {
            "py.toml": profile(
                "py", ["marker.txt"], {"format": touches("ran-format.txt"), "lint": PASS}
            )
        },
        files={"marker.txt": "x\n"},
    )
    write(repo, {"pdf-tools/SKILL.md": text})
    for rel in ("state/state.py", "agents/agents.py"):
        (repo / ".factory" / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(KIT / rel, repo / ".factory" / rel)
    return repo


@pytest.mark.ac("E10-AC-03")
def test_the_gate_exits_2_on_an_invalid_skill_and_runs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _gated(tmp_path, skill(front="name: Bad_Name\ndescription: d. Use when x."))
    code, output = run_gate(repo, monkeypatch, capsys)
    assert code == 2, output
    assert f"{SKILLS_REL}/pdf-tools/SKILL.md: name: " in output
    assert not (repo / "ran-format.txt").exists()


@pytest.mark.ac("E10-AC-03")
def test_the_gate_passes_with_valid_skills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _gated(tmp_path, skill())
    code, output = run_gate(repo, monkeypatch, capsys)
    assert code == 0, output
    assert (repo / "ran-format.txt").exists()


@pytest.mark.ac("E10-AC-03")
def test_install_check_reports_skill_problems(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write(tmp_path, {"pdf-tools/SKILL.md": skill(front="name: pdf-tools")})
    shutil.copyfile(
        REPO_ROOT / "kit" / ".agentic" / "config.toml", root / ".agentic" / "config.toml"
    )
    assert cli.main(["check", str(root)]) == 1
    out = capsys.readouterr()
    assert f"{SKILLS_REL}/pdf-tools/SKILL.md: description: " in out.out + out.err
