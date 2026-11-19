"""E02/T3: resume, the seeds, a second session resuming from files alone, and dogfooding.

Covers E02 AC-12, AC-14, AC-15, AC-16 (the parts a test can check) and AC-17. Expectations come
from the E02 spec and design note, not from the implementation.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path

import pytest

import state
from tests._ac import REPO_ROOT
from tests._repo import git_repo, run_install_py

KIT = REPO_ROOT / "kit"
KIT_STATE_PY = KIT / ".factory" / "state" / "state.py"
T0 = dt.datetime(2026, 11, 18, 21, 30, 0, tzinfo=dt.UTC)
T1 = dt.datetime(2026, 11, 18, 22, 0, 0, tzinfo=dt.UTC)
HANDOFF = "## Done\n\nParser.\n\n## Next\n\n{next}\n\n## Open questions\n\nNone.\n"


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[dt.datetime]:
    times = [T0]
    monkeypatch.setattr(state, "_now", lambda: times[-1])
    return times


def run(root: Path, *args: str) -> int:
    return state.main(["--root", str(root), *args])


def handoff(root: Path, monkeypatch: pytest.MonkeyPatch, task: str, next_step: str) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(HANDOFF.format(next=next_step)))
    assert run(root, "handoff", task, "--from", "builder") == 0


@pytest.fixture
def active(
    tmp_path: Path,
    clock: list[dt.datetime],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> Path:
    """E02-T1 active with two findings (one fixed), a blocker, and handoffs for two tasks."""
    root = tmp_path
    assert run(root, "init") == 0
    assert run(root, "task", "new", "E02-T1", "Formats and validator") == 0
    assert run(root, "task", "new", "E02-T2", "Write commands") == 0
    assert run(root, "start", "E02-T1", "--phase", "build") == 0
    assert run(root, "task", "set", "E02-T1", "--round", "2") == 0
    assert run(root, "finding", "add", "E02-T1", "--severity", "major", "Open one") == 0
    assert run(root, "finding", "add", "E02-T1", "--severity", "minor", "Fixed one") == 0
    assert run(root, "finding", "set", "E02-T1", "F2", "--status", "fixed") == 0
    assert run(root, "block", "waiting on review") == 0
    handoff(root, monkeypatch, "E02-T1", "first note")
    handoff(root, monkeypatch, "E02-T1", "second note, same second")
    handoff(root, monkeypatch, "E02-T1", "third note, same second")
    handoff(root, monkeypatch, "E02-T2", "note for another task")
    capsys.readouterr()
    return root


# --- AC-12: resume ------------------------------------------------------------------------------


@pytest.mark.ac("E02-AC-12")
def test_resume_prints_what_a_new_session_needs(
    active: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(active, "resume") == 0
    out = capsys.readouterr().out
    for expected in (
        "build",
        "full",
        "waiting on review",
        "E02-T1",
        "Formats and validator",
        "in-progress",
        "2",
        "Open one",
        "## Goal",
        "third note, same second",
    ):
        assert expected in out, (expected, out)
    assert "Fixed one" not in out
    assert "first note" not in out
    assert "note for another task" not in out


@pytest.mark.ac("E02-AC-12")
def test_resume_picks_the_newest_handoff_by_time_then_suffix(
    active: Path,
    clock: list[dt.datetime],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clock.append(T1)
    handoff(active, monkeypatch, "E02-T1", "later note")
    capsys.readouterr()
    assert run(active, "resume", "--json") == 0
    data = json.loads(capsys.readouterr().out)
    assert "later note" in data["handoff"]["body"]
    assert data["handoff"]["path"] == ".agentic/handoffs/20261118T220000Z-E02-T1.md"


@pytest.mark.ac("E02-AC-12")
def test_resume_json_has_the_same_information(
    active: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(active, "resume", "--json") == 0
    data = json.loads(capsys.readouterr().out)
    assert data["state"]["front"]["phase"] == "build"
    assert data["state"]["front"]["blockers"] == ["waiting on review"]
    assert data["state"]["front"]["updated"].startswith("2026-11-18T21:30:00")
    assert data["task"]["front"]["id"] == "E02-T1"
    assert data["task"]["front"]["review_round"] == 2
    assert [f["id"] for f in data["task"]["open_findings"]] == ["F1"]
    assert "## Acceptance criteria" in data["task"]["body"]
    assert data["handoff"]["path"] == ".agentic/handoffs/20261118T213000Z-E02-T1-3.md"
    assert data["handoff"]["front"]["from"] == "builder"
    assert "third note" in data["handoff"]["body"]
    assert data["pending"] == []


@pytest.mark.ac("E02-AC-12")
def test_resume_with_no_active_task_lists_unfinished_tasks(
    tmp_path: Path, clock: list[dt.datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(tmp_path, "init") == 0
    for task_id in ("A", "B", "C"):
        assert run(tmp_path, "task", "new", task_id, f"Task {task_id}") == 0
    assert run(tmp_path, "task", "set", "B", "--status", "done") == 0
    capsys.readouterr()
    assert run(tmp_path, "resume") == 0
    out = capsys.readouterr().out
    assert "no active task" in out.lower()
    assert "A" in out and "C" in out and "Task B" not in out
    assert run(tmp_path, "resume", "--json") == 0
    data = json.loads(capsys.readouterr().out)
    assert data["task"] is None and data["handoff"] is None
    assert [t["id"] for t in data["pending"]] == ["A", "C"]


@pytest.mark.ac("E02-AC-12")
def test_resume_with_no_handoff_yet(
    tmp_path: Path, clock: list[dt.datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(tmp_path, "init") == 0
    assert run(tmp_path, "task", "new", "A", "Task A") == 0
    assert run(tmp_path, "start", "A") == 0
    capsys.readouterr()
    assert run(tmp_path, "resume", "--json") == 0
    assert json.loads(capsys.readouterr().out)["handoff"] is None


@pytest.mark.ac("E02-AC-12")
def test_resume_refuses_invalid_or_missing_state(
    tmp_path: Path, clock: list[dt.datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(tmp_path, "resume") == 1
    assert "state.py init" in capsys.readouterr().err
    assert run(tmp_path, "init") == 0
    path = tmp_path / ".agentic" / "STATE.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace('"spec"', '"coding"'), encoding="utf-8"
    )
    capsys.readouterr()
    assert run(tmp_path, "resume") == 1
    assert "phase" in capsys.readouterr().out


# --- AC-14: seeds -------------------------------------------------------------------------------


@pytest.mark.ac("E02-AC-14")
def test_the_state_seed_is_init_output_with_a_fixed_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed = dt.datetime(2026, 11, 18, 0, 0, 0, tzinfo=dt.UTC)
    monkeypatch.setattr(state, "_now", lambda: fixed)
    assert run(tmp_path, "init") == 0
    seed = (KIT / ".agentic" / "STATE.md").read_bytes()
    assert seed == (tmp_path / ".agentic" / "STATE.md").read_bytes()


@pytest.mark.ac("E02-AC-14")
def test_the_glossary_seed_defines_the_factory_terms() -> None:
    text = (KIT / "docs" / "GLOSSARY.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0].startswith("# ")
    assert any(line and not line.startswith(("#", "|")) for line in lines[1:5])
    rows = [line for line in lines if line.startswith("| ") and not line.startswith("| ---")]
    terms = {row.split("|")[1].strip().strip("*`").lower() for row in rows[1:]}
    assert {"gate", "profile", "kit", "slice", "handoff", "track", "phase"} <= terms, terms


@pytest.mark.ac("E02-AC-14")
def test_the_adr_readme_seed_gives_the_format_and_numbering() -> None:
    text = (KIT / "docs" / "adr" / "README.md").read_text(encoding="utf-8")
    for part in ("Status", "Context", "Decision", "Consequences"):
        assert part in text, part
    assert "0001" in text
    assert "number" in text.lower()


@pytest.mark.ac("E02-AC-14")
def test_install_creates_the_seeds_and_never_overwrites_them(tmp_path: Path) -> None:
    repo = git_repo(tmp_path / "repo")
    (repo / "docs").mkdir()
    (repo / "docs" / "GLOSSARY.md").write_text("# Mine\n", encoding="utf-8")
    result = run_install_py(str(repo))
    assert result.returncode == 0, result.stdout + result.stderr
    assert (repo / "docs" / "GLOSSARY.md").read_text(encoding="utf-8") == "# Mine\n"
    assert (repo / "docs" / "adr" / "README.md").is_file()
    manifest = json.loads((repo / ".factory" / "manifest.json").read_text(encoding="utf-8"))
    assert not [rel for rel in manifest["files"] if rel.startswith("docs/")]
    assert state.validate(repo) == []


# --- AC-15: a second session resumes from files alone -------------------------------------------

FIRST_SESSION = textwrap.dedent(
    """
    import io, sys
    sys.path.insert(0, sys.argv[1])
    import state
    root = sys.argv[2]
    def run(*args):
        code = state.main(["--root", root, *args])
        assert code == 0, (args, code)
    run("init")
    run("task", "new", "E02-T9", "Resume proof")
    run("start", "E02-T9", "--phase", "build")
    run("finding", "add", "E02-T9", "--severity", "major", "Handle CRLF in bodies")
    run("task", "set", "E02-T9", "--round", "1")
    sys.stdin = io.StringIO(
        "## Done\\n\\nParser.\\n\\n## Next\\n\\nWire the gate to the validator.\\n\\n"
        "## Open questions\\n\\nNone.\\n"
    )
    run("handoff", "E02-T9", "--from", "first-session")
    """
)


@pytest.mark.ac("E02-AC-15")
def test_a_second_process_resumes_from_the_files_alone(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    first = subprocess.run(
        [sys.executable, "-c", FIRST_SESSION, str(KIT_STATE_PY.parent), str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert first.returncode == 0, first.stdout + first.stderr
    second = subprocess.run(
        [sys.executable, str(KIT_STATE_PY), "resume"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert second.returncode == 0, second.stdout + second.stderr
    for expected in (
        "E02-T9",
        "in-progress",
        "Handle CRLF in bodies",
        "Wire the gate to the validator.",
    ):
        assert expected in second.stdout, (expected, second.stdout)
    data = json.loads(
        subprocess.run(
            [sys.executable, str(KIT_STATE_PY), "--root", str(root), "resume", "--json"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    assert data["task"]["front"]["review_round"] == 1


# --- AC-16: this repo uses its own state files ----------------------------------------------------


def _front(rel: str) -> dict[str, object]:
    parsed = state.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
    assert not isinstance(parsed, str), parsed
    return parsed[0]


@pytest.mark.ac("E02-AC-16")
def test_this_repo_tracks_e02_in_its_own_state_files() -> None:
    assert state.validate(REPO_ROOT) == []
    assert state.task_ids(REPO_ROOT) >= {"E02-T1", "E02-T2", "E02-T3"}
    assert _front(".agentic/tasks/E02-T1.md")["status"] == "done"
    assert _front(".agentic/tasks/E02-T2.md")["status"] == "done"
    assert "+++" in (REPO_ROOT / ".agentic" / "STATE.md").read_text(encoding="utf-8")


@pytest.mark.ac("E02-AC-16")
def test_this_repo_has_the_glossary_and_adr_readme() -> None:
    assert (REPO_ROOT / "docs" / "GLOSSARY.md").is_file()
    assert (REPO_ROOT / "docs" / "adr" / "README.md").is_file()


# --- AC-17: standard library only ---------------------------------------------------------------


@pytest.mark.ac("E02-AC-17")
def test_state_py_imports_only_the_standard_library() -> None:
    import ast

    tree = ast.parse(KIT_STATE_PY.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
    foreign = sorted({n.split(".")[0] for n in names} - set(sys.stdlib_module_names))
    assert not foreign, foreign
    assert tomllib  # the parser the state files rely on
