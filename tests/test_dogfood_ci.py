"""E07/T4: this repo runs its own gate in GitHub Actions on three OSes.

Covers E07 AC-15, the parts a test can check. The hooks are switched on per clone, and the CI
runs on the E07 PR (AC-15) and the seeded-failure branch (AC-16) are evidence in the PR.
"""

from __future__ import annotations

import json
import tomllib

import pytest
import yaml

from factory_installer import pipelines
from factory_installer.kit import KIT_ROOT
from tests._ac import REPO_ROOT

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "factory-gate.yml"
OSES = ["ubuntu", "windows", "macos"]


@pytest.mark.ac("E07-AC-15")
def test_this_repo_runs_the_gate_through_uv() -> None:
    with (REPO_ROOT / ".agentic" / "config.toml").open("rb") as f:
        gates = tomllib.load(f)["gates"]
    assert gates["python_command"] == ["uv", "run", "python"]


@pytest.mark.ac("E07-AC-15")
def test_the_workflow_is_recorded_for_three_oses() -> None:
    data = json.loads((REPO_ROOT / ".factory" / "manifest.json").read_text(encoding="utf-8"))
    assert data["pipelines"] == {"github": {"os": OSES}}
    assert ".github/workflows/factory-gate.yml" in data["files"]


@pytest.mark.ac("E07-AC-15")
def test_the_committed_workflow_is_the_rendered_one() -> None:
    spec = pipelines.spec_for(KIT_ROOT, REPO_ROOT, {"os": OSES})
    assert spec.profiles == ("python",)
    assert spec.has_uv_lock
    expected = pipelines.render("github", spec)
    assert WORKFLOW.read_text(encoding="utf-8").replace("\r\n", "\n") == expected


@pytest.mark.ac("E07-AC-15")
def test_the_workflow_runs_on_ubuntu_windows_and_macos_with_uv() -> None:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = data["jobs"]["gate"]
    assert job["strategy"]["matrix"]["os"] == ["ubuntu-latest", "windows-latest", "macos-latest"]
    runs = [str(step.get("run", "")) for step in job["steps"]]
    assert "uv sync --locked" in runs
    assert runs[-1] == "uv run python .factory/gates/gate.py"
