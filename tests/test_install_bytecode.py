"""Regression: the installer leaves no bytecode in the repo it installs into.

`test_install.py::test_fresh_install_creates_exactly_the_layout` failed when run on its own:
build.py loads agents.py and state.py only when it runs, after the installer had turned
bytecode back on, so `__pycache__` folders appeared in the target repo. Earlier tests in a full
run hid it. These tests turn bytecode on first, so they fail the same way in any order.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from factory_installer import cli
from tests._ac import REPO_ROOT


def _git_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


def _bytecode(root: Path) -> list[str]:
    return sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.name == "__pycache__" or p.suffix == ".pyc"
    )


def test_a_fresh_install_writes_no_bytecode_into_the_repo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    repo = _git_repo(tmp_path / "repo")
    assert cli.main([str(repo)]) == 0
    capsys.readouterr()
    assert _bytecode(repo) == []
    assert sys.dont_write_bytecode is False


def test_install_check_writes_no_bytecode_into_the_repo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    assert cli.main([str(repo)]) == 0
    for cache in sorted(repo.rglob("__pycache__"), reverse=True):
        for f in cache.iterdir():
            f.unlink()
        cache.rmdir()
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    assert cli.main(["check", str(repo)]) == 0
    capsys.readouterr()
    assert _bytecode(repo) == []


def test_the_fresh_install_layout_test_passes_on_its_own() -> None:
    """The original failure: that one test, alone, in a fresh interpreter."""
    test = "tests/test_install.py::test_fresh_install_creates_exactly_the_layout"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", "-p", "no:cacheprovider", test],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
