"""Helpers for the E18 job index tests: temp repos, the job records' paths, the CLI in-process.

The layout comes from the E18 spec ("Where things live") and design note ("Job records").
"""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

import jobs
from tests._ac import REPO_ROOT
from tests._runner import factory_dir, git, runner_repo

JOBS_PY = REPO_ROOT / "kit" / ".factory" / "control" / "jobs.py"
T0 = 1_800_000_000.0  # a fixed "now" for the API, in Unix seconds (ADR 0052)
MINUTE = 60.0

__all__ = ["JOBS_PY", "MINUTE", "T0", "factory_dir", "git", "runner_repo"]


def jobs_repo(tmp_path: Path, config: str | None = None, *, name: str = "proj") -> Path:
    """A git repo on main with one commit (E16's helper), and `.agentic/config.toml` if given."""
    return runner_repo(tmp_path, config, name=name)


def work_dir(repo: Path) -> Path:
    """`<git-common-dir>/factory/work/`, where job records live."""
    return factory_dir(repo) / "work"


def record_path(repo: Path, job: str) -> Path:
    return work_dir(repo) / f"{job}.toml"


def index_path(repo: Path) -> Path:
    return factory_dir(repo) / "index.sqlite"


def record(repo: Path, job: str) -> dict[str, Any]:
    with record_path(repo, job).open("rb") as f:
        return tomllib.load(f)


def call(
    cwd: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *args: str,
) -> tuple[int, str, str]:
    """Run `jobs.py <args>` in-process from `cwd`; return the exit code, stdout and stderr."""
    monkeypatch.chdir(cwd)
    capsys.readouterr()
    code = jobs.main(list(args))
    out = capsys.readouterr()
    return code, out.out, out.err


def new(
    cwd: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    title: str = "A job",
    *args: str,
) -> str:
    """Create a job that must be accepted; return the id it printed."""
    code, out, err = call(cwd, monkeypatch, capsys, "new", title, *args)
    assert code == 0, err
    lines = out.strip().splitlines()
    assert len(lines) == 1, out
    return lines[0].strip()


def show(
    cwd: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    job: str,
) -> dict[str, Any]:
    code, out, err = call(cwd, monkeypatch, capsys, "show", job, "--json")
    assert code == 0, err
    data: dict[str, Any] = json.loads(out)
    return data


def api_repo(repo: Path) -> jobs.Repo:
    return jobs.find_repo(repo)


def run_jobs(cwd: Path, *args: str, isolated: bool = False) -> subprocess.CompletedProcess[str]:
    """`python jobs.py <args>` as a real process."""
    flags = ["-I", "-S"] if isolated else []
    return subprocess.run(
        [sys.executable, *flags, str(JOBS_PY), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
