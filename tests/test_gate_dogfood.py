"""E05 AC-22: this repo has its own kit installed by its own installer (ADR 0009)."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from tests._ac import REPO_ROOT


def _dry_run_report() -> dict[str, object]:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "install.py"), str(REPO_ROOT), "--dry-run", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert isinstance(report, dict)
    return report


@pytest.mark.ac("E05-AC-22")
def test_this_repo_has_its_own_kit_installed() -> None:
    assert (REPO_ROOT / ".factory" / "manifest.json").is_file()
    assert (REPO_ROOT / ".factory" / "gates" / "gate.py").is_file()
    assert (REPO_ROOT / ".agentic" / "config.toml").is_file()


@pytest.mark.ac("E05-AC-22")
def test_installed_kit_is_up_to_date_with_kit_source() -> None:
    report = _dry_run_report()
    files = report["files"]
    assert report["up_to_date"] is True, f"run `python install.py` to refresh the copy: {files}"


@pytest.mark.ac("E05-AC-22")
def test_installed_gate_is_the_kit_gate() -> None:
    kit = (REPO_ROOT / "kit" / ".factory" / "gates" / "gate.py").read_bytes()
    installed = (REPO_ROOT / ".factory" / "gates" / "gate.py").read_bytes()
    assert installed.replace(b"\r\n", b"\n") == kit.replace(b"\r\n", b"\n")
