"""E05 AC-21: the gate ships in the kit and is installed and upgraded like any kit file.

Pulled into E05/T2 because ADR 0007 puts gate.py in the kit, so it ships from its first commit.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from factory_installer import cli
from tests._ac import REPO_ROOT
from tests._repo import MANIFEST, git_repo, normalised_hash

KIT_GATE = REPO_ROOT / "kit" / ".factory" / "gates" / "gate.py"
INSTALLED_GATE = ".factory/gates/gate.py"


def _installed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Path:
    repo = git_repo(tmp_path / "repo")
    assert cli.main([str(repo)]) == 0
    capsys.readouterr()
    return repo


@pytest.mark.ac("E05-AC-21")
def test_install_ships_the_gate_and_an_empty_profiles_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _installed(tmp_path, capsys)
    expected = KIT_GATE.read_bytes().replace(b"\r\n", b"\n")
    assert (repo / INSTALLED_GATE).read_bytes() == expected
    assert (repo / ".factory" / "gates" / "profiles" / ".gitkeep").is_file()
    assert not (repo / ".factory" / "gates" / ".gitkeep").exists()


@pytest.mark.ac("E05-AC-21")
def test_the_gate_is_tracked_in_the_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _installed(tmp_path, capsys)
    files = json.loads((repo / MANIFEST).read_text(encoding="utf-8"))["files"]
    assert files[INSTALLED_GATE] == normalised_hash((repo / INSTALLED_GATE).read_bytes())


@pytest.mark.ac("E05-AC-21")
def test_the_installed_gate_runs_in_the_installed_repo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _installed(tmp_path, capsys)
    result = subprocess.run(
        [sys.executable, INSTALLED_GATE],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "no profile applies" in result.stderr
