"""The GitHub workflow runs mutation on one OS only (product owner decision, 20 Nov 2026).

Mutation scores the tests, not the OS, and Windows runners take about 3x as long: PR #71's
mutation step passed 3600 s on Windows but took about 1,160 s on Ubuntu and macOS. With several
OSes, Ubuntu (else the first OS listed) runs the full gate, and every other OS runs each gate
check but mutation. Covers E07 AC-14's workflow, as changed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from factory_installer import pipelines
from factory_installer.pipelines import PipelineSpec, render
from tests._ac import REPO_ROOT

KIT = REPO_ROOT / "kit"
WITHOUT_MUTATION = "--checks format,lint,types,build,tests,coverage"


def _spec(os_list: tuple[str, ...]) -> PipelineSpec:
    return PipelineSpec(
        profiles=("python",),
        has_uv_lock=True,
        python_command=("uv", "run", "python"),
        base_branch="main",
        os=os_list,
    )


def _job(os_list: tuple[str, ...]) -> dict[str, Any]:
    data = yaml.safe_load(render("github", _spec(os_list)))
    job = data["jobs"]["gate"]
    assert isinstance(job, dict)
    return job


def _gate_runs(job: dict[str, Any]) -> list[str]:
    return [str(s["run"]) for s in job["steps"] if ".factory/gates/gate.py" in str(s.get("run"))]


def _checks_by_os(job: dict[str, Any]) -> dict[str, str]:
    """What each runner's `${{ matrix.checks }}` expands to (GitHub's include rule)."""
    matrix = job["strategy"]["matrix"]
    found = {os: "" for os in matrix["os"]}
    for entry in matrix.get("include", []):
        assert entry["os"] in found, entry  # an include only adds to a listed OS
        found[entry["os"]] = entry["checks"]
    return found


@pytest.mark.ac("E07-AC-14")
@pytest.mark.parametrize(
    ("os_list", "full"),
    [
        (("ubuntu", "windows", "macos"), "ubuntu-latest"),
        (("windows", "ubuntu"), "ubuntu-latest"),
        (("windows", "macos"), "windows-latest"),
        (("macos", "windows"), "macos-latest"),
    ],
)
def test_one_os_runs_mutation_and_the_others_run_every_other_check(
    os_list: tuple[str, ...], full: str
) -> None:
    checks = _checks_by_os(_job(os_list))
    assert checks.pop(full) == ""
    assert checks
    assert set(checks.values()) == {WITHOUT_MUTATION}


@pytest.mark.ac("E07-AC-14")
def test_both_gate_steps_pass_the_matrix_checks() -> None:
    runs = _gate_runs(_job(("ubuntu", "windows", "macos")))
    assert len(runs) == 2
    for run in runs:
        assert run.endswith(" ${{ matrix.checks }}"), run


@pytest.mark.ac("E07-AC-14")
@pytest.mark.parametrize("os_list", [("ubuntu",), ("windows",), ("macos",)])
def test_a_single_os_runs_the_full_gate_unchanged(os_list: tuple[str, ...]) -> None:
    job = _job(os_list)
    assert "include" not in job["strategy"]["matrix"]
    assert _gate_runs(job) == [
        "uv run python .factory/gates/gate.py --base-ref origin/${{ github.base_ref }}",
        "uv run python .factory/gates/gate.py",
    ]


@pytest.mark.ac("E07-AC-14")
def test_the_skip_list_is_the_gates_own_check_list_without_mutation() -> None:
    gate = pipelines._load_gate(KIT)
    assert tuple(gate.CHECK_ORDER) == pipelines.CHECK_ORDER
    assert "mutation" in gate.CHECK_ORDER
    names = WITHOUT_MUTATION.removeprefix("--checks ").split(",")
    assert names == [c for c in gate.CHECK_ORDER if c != "mutation"]
    assert gate.parse_checks(",".join(names)) == names  # the gate accepts the list


@pytest.mark.ac("E07-AC-14")
def test_spec_for_reads_the_kits_check_list(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    spec = pipelines.spec_for(KIT, repo, {"os": ["ubuntu", "windows"]})
    assert spec.check_order == pipelines.CHECK_ORDER
    assert spec.without_mutation() == WITHOUT_MUTATION


def test_this_repos_workflow_runs_mutation_on_ubuntu_only() -> None:
    text = (REPO_ROOT / ".github" / "workflows" / "factory-gate.yml").read_text(encoding="utf-8")
    checks = _checks_by_os(yaml.safe_load(text)["jobs"]["gate"])
    assert checks == {
        "ubuntu-latest": "",
        "windows-latest": WITHOUT_MUTATION,
        "macos-latest": WITHOUT_MUTATION,
    }
    assert re.search(r"gate\.py --base-ref [^\n]*\$\{\{ matrix\.checks \}\}", text)
