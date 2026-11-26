"""E13/T4: the pipeline is a kit file this repo installs, its checks take it in, CI runs its tests
on three OSes, and every E13 acceptance criterion but the live run has a test.

Covers E13 AC-22, and the three OSes of AC-20. Expectations come from the E13 spec (AC-20,
AC-22, "Where things live") and design note ("Source layout"), not from the implementation.
ruff, `ruff format --check` and `mypy --strict` are the gate's own checks, so here it's enough
that they're pointed at the pipeline.
"""

from __future__ import annotations

import tomllib

import pytest

from tests._ac import COLLECTED_AC_IDS, REPO_ROOT, spec_ac_ids
from tests._repo import KIT_FILES

KIT = (".factory/workflow/pipeline.py", ".factory/workflow/pipeline.md")
LIVE = "E13-AC-21"  # the product owner's live run on a real issue: no test can hold it


@pytest.mark.ac("E13-AC-22")
def test_e13_spec_defines_ac_01_to_ac_23() -> None:
    assert spec_ac_ids("E13") == {f"E13-AC-{n:02d}" for n in range(1, 24)}


@pytest.mark.ac("E13-AC-22")
def test_every_e13_ac_but_the_live_run_has_a_test(request: pytest.FixtureRequest) -> None:
    missing = spec_ac_ids("E13") - {LIVE} - request.config.stash[COLLECTED_AC_IDS]
    assert not missing, f"E13 ACs with no test: {sorted(missing)}"


@pytest.mark.ac("E13-AC-22")
@pytest.mark.parametrize("rel", KIT)
def test_the_pipeline_is_a_kit_file_and_this_repo_commits_its_install(rel: str) -> None:
    assert rel in KIT_FILES
    kit = (REPO_ROOT / "kit" / rel).read_bytes().replace(b"\r\n", b"\n")
    installed = (REPO_ROOT / rel).read_bytes().replace(b"\r\n", b"\n")
    assert installed == kit, "run install.py . and commit its output"


@pytest.mark.ac("E13-AC-22")
def test_lint_types_tests_and_coverage_take_in_the_pipeline() -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    tool = project["tool"]
    assert "kit/.factory/workflow" in tool["mypy"]["files"]
    assert tool["mypy"]["strict"] is True
    assert "kit/.factory/workflow" in tool["pytest"]["ini_options"]["pythonpath"]
    assert "kit/.factory/workflow" in tool["coverage"]["run"]["source"]
    excluded = [str(item) for item in tool.get("ruff", {}).get("exclude", [])]
    assert not any("workflow" in item for item in excluded), excluded


@pytest.mark.ac("E13-AC-20")
@pytest.mark.ac("E13-AC-22")
def test_ci_runs_the_tests_on_ubuntu_macos_and_windows() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "factory-gate.yml").read_text(
        encoding="utf-8"
    )
    for os_name in ("ubuntu-latest", "macos-latest", "windows-latest"):
        assert os_name in workflow
    narrowed = [line for line in workflow.splitlines() if "--checks" in line]
    for line in narrowed:
        assert "tests" in line.split("--checks", 1)[1], f"tests must run there: {line.strip()}"
    assert "not slow" not in workflow, "CI must run the slow end-to-end tests too"
