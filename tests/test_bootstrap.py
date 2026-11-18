"""T1 bootstrap: this repo's license, project metadata, tooling and line-ending policy."""

from __future__ import annotations

import tomllib
from typing import Any

import pytest

from tests._ac import REPO_ROOT


def _pyproject() -> dict[str, Any]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)


@pytest.mark.ac("AC-22")
def test_license_is_apache_2() -> None:
    text = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Apache License" in text
    assert "Version 2.0, January 2004" in text


@pytest.mark.ac("AC-22")
def test_pyproject_requires_python_3_11_and_declares_apache_license() -> None:
    project = _pyproject()["project"]
    assert project["requires-python"] == ">=3.11"
    assert project["license"] == "Apache-2.0"


@pytest.mark.ac("AC-22")
def test_project_is_managed_by_uv() -> None:
    assert (REPO_ROOT / "uv.lock").is_file()


@pytest.mark.ac("AC-22")
def test_kit_version_file_matches_pyproject_version() -> None:
    kit_version = (REPO_ROOT / "kit" / "VERSION").read_text(encoding="utf-8").strip()
    assert kit_version == _pyproject()["project"]["version"]


@pytest.mark.ac("AC-02")
def test_project_has_no_runtime_dependencies() -> None:
    assert _pyproject()["project"].get("dependencies", []) == []


@pytest.mark.ac("AC-23")
def test_dev_tools_are_declared() -> None:
    dev = " ".join(_pyproject()["dependency-groups"]["dev"])
    for tool in ("ruff", "mypy", "pytest", "coverage"):
        assert tool in dev, f"{tool} missing from the dev dependency group"


@pytest.mark.ac("AC-23")
def test_mypy_runs_strict() -> None:
    assert _pyproject()["tool"]["mypy"]["strict"] is True


@pytest.mark.ac("AC-20")
def test_repo_enforces_lf_line_endings() -> None:
    lines = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "* text=auto eol=lf" in lines
