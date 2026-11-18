"""E06/T3: this repo is checked by its own gate with the Python profile.

Covers E06 AC-14, the parts a test can check. The gate run itself is evidence in the PR
(spec assumption 7): a test that ran the gate would run itself through the tests check.
"""

from __future__ import annotations

import subprocess
import tomllib

import pytest

import gate
from tests._ac import REPO_ROOT

# What ruff, mypy, pytest, coverage and Python itself write while the gate runs.
CHECK_OUTPUTS = (
    ".ruff_cache/x",
    ".mypy_cache/x",
    ".pytest_cache/x",
    ".coverage",
    ".coverage.host.1234.567890",
    "factory_installer/__pycache__/cli.cpython-312.pyc",
    "htmlcov/index.html",
)


def _pyproject() -> dict[str, object]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)


@pytest.mark.ac("E06-AC-14")
def test_cosmic_ray_is_a_dev_dependency() -> None:
    groups = _pyproject()["dependency-groups"]
    assert isinstance(groups, dict)
    assert any(str(dep).startswith("cosmic-ray") for dep in groups["dev"])


@pytest.mark.ac("E06-AC-14")
@pytest.mark.parametrize("path", CHECK_OUTPUTS)
def test_files_the_python_checks_write_are_ignored(path: str) -> None:
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", path],
        cwd=REPO_ROOT,
        check=False,
    )
    assert result.returncode == 0, f"{path} is not git-ignored"


@pytest.mark.ac("E06-AC-14")
def test_the_installed_gate_detects_only_the_python_profile() -> None:
    profiles = gate.load_profiles(REPO_ROOT)
    settings = gate.Settings.load(REPO_ROOT)
    detected = [p.name for p in gate.select_profiles(REPO_ROOT, profiles, settings)]
    assert detected == ["python"]
