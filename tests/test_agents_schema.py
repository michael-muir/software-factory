"""E03/T2: the agent file format, its validation, `_schema.md` and `_template.md`.

Covers E03 AC-01 to AC-04 for agent files. Expectations come from the E03 spec and the design
note, not from the implementation.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Mapping
from pathlib import Path

import pytest

import agents
from factory_installer import cli
from tests._ac import REPO_ROOT
from tests._gate import PASS, gate_repo, profile, run_gate, touches

KIT = REPO_ROOT / "kit" / ".factory"
KIT_AGENTS_DIR = KIT / "agents"
AGENTS_REL = ".factory/agents"

VALID_STATE = """+++
phase = "test"
track = "full"
active_task = ""
blockers = []
updated = 2026-11-18T21:30:00Z
+++
"""

BODY = "\n## Scope\n\nWhat this role does.\n\n## Inputs\n\n## Outputs\n"

DEFAULTS: dict[str, str] = {
    "name": '"implementer"',
    "title": '"Implementer"',
    "summary": '"Smallest change to green."',
    "model_hint": '"strong"',
    "different_from": '""',
    "tools": '["read", "search", "edit", "write", "run"]',
}


def role_text(
    *,
    drop: tuple[str, ...] = (),
    scope: Mapping[str, str] | None = None,
    body: str = BODY,
    **values: str,
) -> str:
    """An agent file: DEFAULTS overridden by `values` (TOML literals), minus `drop`."""
    inline = values.pop("scope_inline", None)
    fields = {**DEFAULTS, **values}
    if inline is not None:
        fields["scope"] = inline
    lines = [f"{key} = {value}" for key, value in fields.items() if key not in drop]
    if scope is not None:
        lines += ["", "[scope]"] + [f"{key} = {value}" for key, value in scope.items()]
    return "+++\n" + "\n".join(lines) + "\n+++\n" + body


def write_roles(root: Path, roles: Mapping[str, str]) -> Path:
    state = root / ".agentic" / "STATE.md"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(VALID_STATE, encoding="utf-8", newline="\n")
    for rel, text in roles.items():
        path = root / AGENTS_REL / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return root


def problems(root: Path) -> list[str]:
    return [str(p) for p in agents.validate(root)]


def problems_at(root: Path, rel: str, where: str) -> list[str]:
    prefix = f"{AGENTS_REL}/{rel}: {where}: "
    return [p for p in problems(root) if p.startswith(prefix)]


# --- AC-01: a valid agent file ------------------------------------------------------------------


@pytest.mark.ac("E03-AC-01")
def test_a_valid_role_has_no_problems(tmp_path: Path) -> None:
    root = write_roles(tmp_path, {"implementer.md": role_text()})
    assert problems(root) == []


@pytest.mark.ac("E03-AC-01")
def test_a_role_with_scopes_is_valid(tmp_path: Path) -> None:
    text = role_text(scope={"write": '["src/**", "tests/*.py"]', "run": '["uv run pytest"]'})
    root = write_roles(tmp_path, {"implementer.md": text})
    assert problems(root) == []


@pytest.mark.ac("E03-AC-01")
def test_a_different_from_hint_names_another_role(tmp_path: Path) -> None:
    reviewer = role_text(
        name='"code-reviewer"',
        title='"Code Reviewer"',
        model_hint='"different-from"',
        different_from='"implementer"',
        tools='["read", "search"]',
    )
    root = write_roles(tmp_path, {"implementer.md": role_text(), "code-reviewer.md": reviewer})
    assert problems(root) == []


@pytest.mark.ac("E03-AC-01")
def test_roles_in_subfolders_are_validated(tmp_path: Path) -> None:
    root = write_roles(tmp_path, {"core/implementer.md": role_text(model_hint='"fast"')})
    assert problems_at(root, "core/implementer.md", "model_hint")


@pytest.mark.ac("E03-AC-01")
def test_underscore_files_and_other_files_are_not_roles(tmp_path: Path) -> None:
    root = write_roles(
        tmp_path,
        {"_notes.md": "not a role\n", "core/_draft.md": "nor this\n", "README.txt": "x\n"},
    )
    (root / AGENTS_REL / "agents.py").write_text("x = 1\n", encoding="utf-8")
    assert problems(root) == []


@pytest.mark.ac("E03-AC-01")
def test_a_repo_without_an_agents_folder_has_no_problems(tmp_path: Path) -> None:
    assert problems(write_roles(tmp_path, {})) == []


# --- AC-01: invalid agent files, reported by key or heading -------------------------------------


@pytest.mark.ac("E03-AC-01")
@pytest.mark.parametrize(
    ("text", "where"),
    [
        (role_text(owner='"me"'), "owner"),
        (role_text(drop=("title",)), "title"),
        (role_text(drop=("summary",)), "summary"),
        (role_text(drop=("different_from",)), "different_from"),
        (role_text(title='""'), "title"),
        (role_text(summary="3"), "summary"),
        (role_text(name='"coder"'), "name"),
        (role_text(tools="[]"), "tools"),
        (role_text(tools='"read"'), "tools"),
        (role_text(tools='["read", "deploy"]'), "tools"),
        (role_text(tools='["read", "read"]'), "tools"),
        (role_text(model_hint='"fast"'), "model_hint"),
        (role_text(model_hint='"different-from"'), "different_from"),
        (role_text(model_hint='"different-from"', different_from='"nobody"'), "different_from"),
        (
            role_text(model_hint='"different-from"', different_from='"implementer"'),
            "different_from",
        ),
        (role_text(different_from='"code-reviewer"'), "different_from"),
        (role_text(scope={"read": '["src/**"]'}), "scope.read"),
        (role_text(scope={"write": '"src/**"'}), "scope.write"),
        (role_text(scope={"write": "[]"}), "scope.write"),
        (role_text(scope={"write": '["/src/**"]'}), "scope.write"),
        (role_text(scope={"write": '["../src/**"]'}), "scope.write"),
        (role_text(scope={"write": '["src\\\\**"]'}), "scope.write"),
        (role_text(scope={"write": '["C:/src/**"]'}), "scope.write"),
        (role_text(tools='["read", "run"]', scope={"write": '["src/**"]'}), "scope.write"),
        (role_text(tools='["read", "edit"]', scope={"run": '["uv run"]'}), "scope.run"),
        (role_text(scope={"run": '[""]'}), "scope.run"),
        (role_text(body="\n## Scope\n\n## Outputs\n"), "## Inputs"),
        (role_text(body="\n## Inputs\n\n## Outputs\n"), "## Scope"),
        (role_text(body="\n## Scope\n\n## Inputs\n"), "## Outputs"),
        ("no front matter here\n", "front matter"),
        ("+++\nname = [\n+++\n" + BODY, "front matter"),
    ],
)
def test_invalid_roles_are_reported_by_key(tmp_path: Path, text: str, where: str) -> None:
    root = write_roles(tmp_path, {"implementer.md": text})
    assert problems_at(root, "implementer.md", where), problems(root)


@pytest.mark.ac("E03-AC-01")
def test_scope_must_be_a_table(tmp_path: Path) -> None:
    root = write_roles(tmp_path, {"implementer.md": role_text(scope_inline='"src/**"')})
    assert problems_at(root, "implementer.md", "scope"), problems(root)


@pytest.mark.ac("E03-AC-01")
@pytest.mark.parametrize("bad", ["Implementer", "code_reviewer", "code reviewer", "rôle"])
def test_names_are_lowercase_letters_digits_and_hyphens(tmp_path: Path, bad: str) -> None:
    root = write_roles(tmp_path, {f"{bad}.md": role_text(name=f'"{bad}"')})
    assert problems_at(root, f"{bad}.md", "name"), problems(root)


@pytest.mark.ac("E03-AC-01")
def test_no_two_roles_share_a_name(tmp_path: Path) -> None:
    root = write_roles(
        tmp_path, {"core/implementer.md": role_text(), "domains/implementer.md": role_text()}
    )
    found = problems_at(root, "domains/implementer.md", "name")
    assert found, problems(root)
    assert "core/implementer.md" in found[0]


@pytest.mark.ac("E03-AC-01")
def test_every_problem_in_a_file_is_reported(tmp_path: Path) -> None:
    text = role_text(model_hint='"fast"', tools='["deploy"]', owner='"me"')
    root = write_roles(tmp_path, {"implementer.md": text})
    wheres = {p.split(": ")[1] for p in problems(root)}
    assert {"model_hint", "tools", "owner"} <= wheres, problems(root)


@pytest.mark.ac("E03-AC-01")
def test_the_vocabulary_is_the_six_neutral_tools() -> None:
    assert set(agents.TOOLS) == {"read", "search", "edit", "write", "run", "web"}
    assert set(agents.HINTS) == {"strong", "any", "different-from"}


# --- AC-02: _schema.md and _template.md ---------------------------------------------------------


def _table_names(markdown: str, heading: str) -> set[str]:
    """The backticked names in the first column of the table under `heading`."""
    lines = markdown.split("\n")
    assert heading in lines, f"_schema.md has no {heading!r} section"
    names: set[str] = set()
    for line in lines[lines.index(heading) + 1 :]:
        if line.startswith("## "):
            break
        match = re.match(r"\|\s*`([^`]+)`\s*\|", line)
        if match:
            names.add(match.group(1))
    assert names, f"no table rows under {heading!r}"
    return names


SCHEMA_DOC = KIT_AGENTS_DIR / "_schema.md"


@pytest.mark.ac("E03-AC-02")
def test_schema_doc_lists_exactly_the_keys_the_validator_accepts() -> None:
    doc = SCHEMA_DOC.read_text(encoding="utf-8")
    assert _table_names(doc, "## Keys") == set(agents.AGENT_SCHEMA)


@pytest.mark.ac("E03-AC-02")
def test_schema_doc_lists_exactly_the_scope_keys() -> None:
    doc = SCHEMA_DOC.read_text(encoding="utf-8")
    assert _table_names(doc, "## Scope keys") == set(agents.SCOPE_KEYS) == {"write", "run"}


@pytest.mark.ac("E03-AC-02")
def test_schema_doc_lists_exactly_the_tools() -> None:
    doc = SCHEMA_DOC.read_text(encoding="utf-8")
    assert _table_names(doc, "## Tools") == set(agents.TOOLS)


@pytest.mark.ac("E03-AC-02")
def test_schema_doc_explains_every_model_hint() -> None:
    doc = SCHEMA_DOC.read_text(encoding="utf-8")
    assert _table_names(doc, "## Model hints") == set(agents.HINTS)


@pytest.mark.ac("E03-AC-02")
def test_schema_doc_names_the_required_headings() -> None:
    doc = SCHEMA_DOC.read_text(encoding="utf-8")
    for heading in agents.AGENT_HEADINGS:
        assert f"`{heading}`" in doc
    assert set(agents.AGENT_HEADINGS) == {"## Scope", "## Inputs", "## Outputs"}


@pytest.mark.ac("E03-AC-02")
def test_the_template_copied_to_its_role_name_is_a_valid_role(tmp_path: Path) -> None:
    template = (KIT_AGENTS_DIR / "_template.md").read_text(encoding="utf-8")
    match = re.search(r'^name = "([a-z0-9-]+)"$', template, re.MULTILINE)
    assert match, "the template must have a name line"
    root = write_roles(tmp_path, {f"{match.group(1)}.md": template})
    assert problems(root) == []


@pytest.mark.ac("E03-AC-02")
def test_the_kit_ships_only_valid_roles(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    shutil.copytree(KIT_AGENTS_DIR, root / AGENTS_REL)
    write_roles(root, {})
    assert problems(root) == []


# --- AC-03: agents.py check covers roles --------------------------------------------------------


def run(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *args: str,
) -> tuple[int, str]:
    monkeypatch.chdir(root)
    code = agents.main(list(args))
    out = capsys.readouterr()
    return code, out.out + out.err


@pytest.mark.ac("E03-AC-03")
def test_check_reports_role_problems_one_per_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write_roles(
        tmp_path, {"implementer.md": role_text(model_hint='"fast"', tools='["deploy"]')}
    )
    code, output = run(root, monkeypatch, capsys, "check")
    assert code == 1, output
    lines = [line for line in output.splitlines() if line.startswith(f"{AGENTS_REL}/")]
    assert len(lines) == 2, output
    assert all(re.fullmatch(r"[^:]+: [^:]+: .+", line) for line in lines), lines


@pytest.mark.ac("E03-AC-03")
def test_check_passes_valid_roles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write_roles(tmp_path, {"implementer.md": role_text()})
    code, output = run(root, monkeypatch, capsys, "check")
    assert code == 0, output


@pytest.mark.ac("E03-AC-03")
def test_check_reports_roles_and_lock_records_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write_roles(tmp_path, {"implementer.md": role_text(model_hint='"fast"')})
    locks = root / ".agentic" / "locks"
    locks.mkdir(parents=True)
    (locks / "E03-T1.toml").write_text("task = [\n", encoding="utf-8")
    code, output = run(root, monkeypatch, capsys, "check")
    assert code == 1, output
    assert f"{AGENTS_REL}/implementer.md: model_hint: " in output
    assert ".agentic/locks/E03-T1.toml: " in output


# --- AC-04: the gate and install.py check validate roles ----------------------------------------


@pytest.mark.ac("E03-AC-04")
def test_the_gate_exits_2_on_an_invalid_role_and_runs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = gate_repo(
        tmp_path / "repo",
        {"py.toml": profile("py", ["marker.txt"], {"format": touches("ran.txt"), "lint": PASS})},
        files={"marker.txt": "x\n"},
    )
    write_roles(repo, {"implementer.md": role_text(tools='["deploy"]')})
    for rel in ("state/state.py", "agents/agents.py"):
        (repo / ".factory" / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(KIT / rel, repo / ".factory" / rel)
    code, output = run_gate(repo, monkeypatch, capsys)
    assert code == 2, output
    assert f"{AGENTS_REL}/implementer.md: tools: " in output
    assert not (repo / "ran.txt").exists()


@pytest.mark.ac("E03-AC-04")
def test_the_gate_passes_with_valid_roles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = gate_repo(
        tmp_path / "repo",
        {"py.toml": profile("py", ["marker.txt"], {"format": touches("ran.txt"), "lint": PASS})},
        files={"marker.txt": "x\n"},
    )
    write_roles(repo, {"implementer.md": role_text()})
    for rel in ("state/state.py", "agents/agents.py"):
        (repo / ".factory" / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(KIT / rel, repo / ".factory" / rel)
    code, output = run_gate(repo, monkeypatch, capsys)
    assert code == 0, output
    assert (repo / "ran.txt").exists()


@pytest.mark.ac("E03-AC-04")
def test_install_check_reports_role_problems(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write_roles(tmp_path, {"implementer.md": role_text(model_hint='"fast"')})
    shutil.copyfile(
        REPO_ROOT / "kit" / ".agentic" / "config.toml", root / ".agentic" / "config.toml"
    )
    assert cli.main(["check", str(root)]) == 1
    out = capsys.readouterr()
    assert f"{AGENTS_REL}/implementer.md: model_hint: " in out.out + out.err
