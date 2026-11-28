"""REVIEW-T2: lock hashes match the manifest's, mutation never edits the working tree, and the
gate report always carries lock status (code review items 8 to 10; ADRs 0004, 0010, 0018).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import agents
import gate
import mutate_python
from factory_installer.kit import content_hash
from tests._ac import REPO_ROOT
from tests._gate import PASS, gate_repo, profile, run_gate, touches
from tests._repo import git_repo

KIT = REPO_ROOT / "kit" / ".factory"
LOCKED = "tests/test_widget.py"
TEST_TEXT = "def test_widget() -> None:\n    assert True\n"
STATE = """+++
phase = "test"
track = "full"
active_task = ""
blockers = []
updated = 2026-11-19T08:00:00Z
+++
"""
TASK = """+++
id = "R-T2"
title = "A slice"
status = "in-progress"
review_round = 0
created = 2026-11-19T08:00:00Z
updated = 2026-11-19T08:00:00Z
+++

## Goal

## Acceptance criteria

## Notes
"""


# --- item 8: lock hashes are the manifest's hashes (ADR 0004) ------------------------------------


@pytest.mark.parametrize(
    "data",
    [b"a\nb\n", b"a\r\nb\r\n", b"a\rb\r", b"mixed\r\nand\rlone\n", b"", b"\r\n\r\n\r"],
)
def test_lock_hashes_equal_the_manifest_hashes(data: bytes) -> None:
    assert agents.lf_sha256(data) == content_hash(data)


def test_a_lone_cr_is_content_not_a_line_ending() -> None:
    assert agents.lf_sha256(b"a\rb") == hashlib.sha256(b"a\rb").hexdigest()
    assert agents.lf_sha256(b"a\r\nb") == hashlib.sha256(b"a\nb").hexdigest()


# --- item 10: the gate report carries lock status ------------------------------------------------


def locked_repo(tmp_path: Path, *, lock: bool = True) -> Path:
    repo = gate_repo(
        tmp_path / "repo",
        {
            "py.toml": profile(
                "py", ["marker.txt"], {"format": touches("ran-format.txt"), "lint": PASS}
            )
        },
        files={"marker.txt": "x\n"},
    )
    files = {".agentic/STATE.md": STATE, ".agentic/tasks/R-T2.md": TASK, LOCKED: TEST_TEXT}
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8", newline="\n")
    for rel in ("state/state.py", "agents/agents.py"):
        (repo / ".factory" / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(KIT / rel, repo / ".factory" / rel)
    if lock:
        agents.lock(repo, "R-T2", [repo / LOCKED])
    return repo


def test_the_json_report_counts_locked_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = locked_repo(tmp_path)
    code, output = run_gate(repo, monkeypatch, capsys, "--json")
    assert code == 0, output
    report = json.loads(output[output.index("{") :])
    assert report["locks"] == {"locked": 1, "broken": []}
    assert report["verdict"] == "pass"


def test_a_broken_lock_still_produces_a_json_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = locked_repo(tmp_path)
    (repo / LOCKED).write_text("def test_widget() -> None:\n    assert False\n", "utf-8")
    monkeypatch.chdir(repo)
    code = gate.main(["--json"])
    out = capsys.readouterr()
    assert code == 1
    report = json.loads(out.out)
    assert report["verdict"] == "fail"
    assert report["locks"] == {"locked": 1, "broken": [f"{LOCKED}: locked by R-T2: changed"]}
    assert report["checks"] == []
    assert not (repo / "ran-format.txt").exists()


def test_the_text_report_shows_lock_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = locked_repo(tmp_path)
    code, output = run_gate(repo, monkeypatch, capsys)
    assert code == 0, output
    assert "Locks: 1 locked file, none changed" in output
    (repo / LOCKED).unlink()
    code, output = run_gate(repo, monkeypatch, capsys)
    assert code == 1, output
    assert f"{LOCKED}: locked by R-T2: missing" in output
    assert output.rstrip().endswith("FAIL")


def test_a_repo_without_locks_reports_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = locked_repo(tmp_path, lock=False)
    code, output = run_gate(repo, monkeypatch, capsys, "--json")
    assert code == 0, output
    assert json.loads(output[output.index("{") :])["locks"] == {"locked": 0, "broken": []}


# --- item 9: mutation runs on a copy, never the working tree (ADR 0010) --------------------------


def project(tmp_path: Path, test_body: str = "    assert add(2, 3) == 5\n") -> Path:
    root = git_repo(tmp_path / "proj")
    files = {
        ".gitignore": "ignored.txt\n",
        "pyproject.toml": "[project]\nname = 'p'\nversion = '0'\n",
        "calc.py": "def add(a: int, b: int) -> int:\n    return a + b\n",
        "test_calc.py": "from calc import add\n\n\ndef test_add() -> None:\n" + test_body,
        "ignored.txt": "secret\n",
        "untracked.txt": "new\n",
    }
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    subprocess.run(
        ["git", "add", ".gitignore", "pyproject.toml", "calc.py", "test_calc.py"],
        cwd=root,
        check=True,
    )
    return root


def test_the_copy_holds_the_files_git_sees_in_a_fresh_repo(tmp_path: Path) -> None:
    root = project(tmp_path)
    dest = tmp_path / "copy"
    mutate_python.project_copy(root, dest)
    copied = {
        p.relative_to(dest).as_posix()
        for p in dest.rglob("*")
        if p.is_file() and ".git" not in p.parts
    }
    assert copied == {".gitignore", "pyproject.toml", "calc.py", "test_calc.py", "untracked.txt"}
    assert (dest / ".git").is_dir()
    assert (dest / "calc.py").read_bytes() == (root / "calc.py").read_bytes()


class FakeCosmicRay:
    """Stands in for cosmic-ray: records where it ran and fills a minimal session database."""

    def __init__(self) -> None:
        self.cwds: list[Path] = []

    def __call__(self, *args: str, cwd: Path) -> None:
        self.cwds.append(cwd)
        command, _config, session = args
        db = sqlite3.connect(session)
        with db:
            if command == "init":
                db.execute(
                    "CREATE TABLE mutation_specs (job_id, module_path, operator_name, occurrence,"
                    " start_pos_row, start_pos_col)"
                )
                db.execute("CREATE TABLE work_items (job_id)")
                db.execute("INSERT INTO mutation_specs VALUES ('j1', 'calc.py', 'op', 0, 2, 4)")
                db.execute("INSERT INTO work_items VALUES ('j1')")
            else:
                db.execute("CREATE TABLE work_results (job_id, test_outcome)")
                db.execute("INSERT INTO work_results VALUES ('j1', 'KILLED')")
        db.close()


def test_cosmic_ray_runs_in_a_copy_not_the_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path)
    fake = FakeCosmicRay()
    monkeypatch.setattr(mutate_python, "_cosmic_ray", fake)
    assert mutate_python.run(root, ["calc.py"], 60.0) == 0, capsys.readouterr()
    assert [path != root for path in fake.cwds] == [True, True]
    assert not fake.cwds[0].exists(), "the copy is removed afterwards"


def test_red_tests_are_not_scored_and_fail_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Red tests are never scored, and fail mutation too (E06 AC-10, amended 28 Nov 2026)."""
    root = project(tmp_path, test_body="    assert add(2, 3) == 6\n")
    fake = FakeCosmicRay()
    monkeypatch.setattr(mutate_python, "_cosmic_ray", fake)
    assert mutate_python.run(root, ["calc.py"], 60.0) == 1
    assert "fails before any mutation" in capsys.readouterr().out
    assert fake.cwds == []


def test_a_copy_that_fails_where_the_project_passes_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken copy would count every mutant as killed: exit 2, never a false pass."""
    body = "    assert open('ignored.txt').read() == 'secret\\n'\n"
    root = project(tmp_path, test_body=body)
    fake = FakeCosmicRay()
    monkeypatch.setattr(mutate_python, "_cosmic_ray", fake)
    with pytest.raises(mutate_python.HelperError, match="copy"):
        mutate_python.run(root, ["calc.py"], 60.0)
    assert fake.cwds == []


def test_the_baseline_uses_the_pinned_interpreter(tmp_path: Path) -> None:
    root = project(tmp_path)
    dest = tmp_path / "copy"
    mutate_python.project_copy(root, dest)
    command = mutate_python.test_command(sys.executable, [])
    assert mutate_python.tests_pass(command, dest) is True
