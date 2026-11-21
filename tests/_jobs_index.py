"""Helpers for the E18/T2 index tests: repos with state files and worktrees, list and status.

The shapes come from the E18 design note ("The index", "Readers") and the T2 contract for
`list --json`: an object with `jobs`, `runner_jobs`, `usage`, `worktrees` and `problems`.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import pytest

import run as runner
from tests._ac import REPO_ROOT
from tests._halt import factory_repo, state_py
from tests._jobs import call, git, index_path

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "jobs"
SECTIONS = ("jobs", "runner_jobs", "usage", "worktrees", "problems")

__all__ = ["FIXTURES", "SECTIONS", "factory_repo", "state_py"]


def listing(
    cwd: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *args: str
) -> dict[str, Any]:
    """`jobs.py list --json`, which must succeed."""
    code, out, err = call(cwd, monkeypatch, capsys, "list", "--json", *args)
    assert code == 0, err
    data: dict[str, Any] = json.loads(out)
    return data


def by_id(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in items}


def real(path: str | Path) -> str:
    return os.path.normcase(os.path.realpath(path))


def worktree_entry(data: dict[str, Any], path: Path) -> dict[str, Any]:
    found: list[dict[str, Any]] = [w for w in data["worktrees"] if real(w["path"]) == real(path)]
    assert len(found) == 1, data["worktrees"]
    return found[0]


def run_py(
    cwd: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *args: str
) -> tuple[int, str, str]:
    """`run.py <args>` in-process (E16), from `cwd`."""
    monkeypatch.chdir(cwd)
    capsys.readouterr()
    code = runner.main(list(args))
    out = capsys.readouterr()
    return code, out.out, out.err


def runner_status(
    cwd: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], job: str
) -> dict[str, Any]:
    code, out, err = run_py(cwd, monkeypatch, capsys, "status", job, "--json")
    assert code == 0, err
    data: dict[str, Any] = json.loads(out)
    return data


def submit(
    cwd: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *args: str
) -> str:
    code, out, err = run_py(cwd, monkeypatch, capsys, "submit", *args)
    assert code == 0, err
    return out.strip()


def add_worktree(repo: Path, path: Path, branch: str) -> Path:
    git(repo, "worktree", "add", "-q", "-b", branch, str(path))
    return path


def state(worktree: Path, *args: str) -> None:
    """Run the worktree's own state.py; it must succeed."""
    result = state_py(worktree, *args)
    assert result.returncode == 0, result.stderr


def write_handoff(worktree: Path, task: str, next_text: str, tmp: Path) -> None:
    body = tmp / f"handoff-{task}-{abs(hash(next_text))}.md"
    body.write_text(f"## Done\n\nSome.\n\n## Next\n\n{next_text}\n\n## Open questions\n\nNone.\n")
    state(worktree, "handoff", task, "--from", "tester", "--body-file", str(body))


def user_version(repo: Path) -> int:
    con = sqlite3.connect(index_path(repo))
    try:
        return int(con.execute("PRAGMA user_version").fetchone()[0])
    finally:
        con.close()


def set_user_version(repo: Path, version: int) -> None:
    con = sqlite3.connect(index_path(repo))
    try:
        con.execute(f"PRAGMA user_version = {version}")
        con.commit()
    finally:
        con.close()


def git_ok(repo: Path, *args: str) -> bool:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, check=False)
    return result.returncode == 0
