"""Helpers for the E16 runner tests: temp git repos with a commit, the store's paths, the CLI.

The store layout comes from the E16 design note ("The store") and ADR 0030.
"""

from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest

import run as runner
from tests._ac import REPO_ROOT

RUN_PY = REPO_ROOT / "kit" / ".factory" / "runner" / "run.py"


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def runner_repo(tmp_path: Path, config: str | None = None, *, name: str = "proj") -> Path:
    """A git repo on branch main with one commit, and `.agentic/config.toml` if given."""
    root = tmp_path / name
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    (root / "README.md").write_text("fixture\n", encoding="utf-8")
    if config is not None:
        (root / ".agentic").mkdir()
        (root / ".agentic" / "config.toml").write_text(config, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "fixture")
    return root


def real(path: str | Path) -> str:
    """A path in a form two spellings of the same place agree on (macOS /private, Windows 8.3)."""
    return os.path.normcase(os.path.realpath(path))


def factory_dir(repo: Path) -> Path:
    """`<git-common-dir>/factory/` (ADR 0030)."""
    common = git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    return Path(common) / "factory"


def queue_file(repo: Path, job: str) -> Path:
    return factory_dir(repo) / "queue" / f"{job}.toml"


def job_dir(repo: Path, job: str) -> Path:
    return factory_dir(repo) / "jobs" / job


def read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        return tomllib.load(f)


def call(
    cwd: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *args: str,
) -> tuple[int, str, str]:
    """Run `run.py <args>` in-process from `cwd`; return the exit code, stdout and stderr."""
    monkeypatch.chdir(cwd)
    capsys.readouterr()
    code = runner.main(list(args))
    out = capsys.readouterr()
    return code, out.out, out.err


def submit(
    cwd: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *args: str,
) -> str:
    """Submit a job that must be accepted; return the id it printed."""
    code, out, err = call(cwd, monkeypatch, capsys, "submit", *args)
    assert code == 0, err
    lines = out.strip().splitlines()
    assert len(lines) == 1, out
    return lines[0].strip()
