"""E16/T4: the runner is a kit file this repo installs, CI runs its tests on three OSes, and every
E16 acceptance criterion has a test.

Covers E16 AC-20. Expectations come from the E16 spec and design note ("Source layout"), not
from the implementation. ruff, `ruff format --check` and `mypy --strict` are the gate's own
checks, so here it's enough that they're pointed at the runner.
"""

from __future__ import annotations

import tomllib

import pytest

from tests._ac import COLLECTED_AC_IDS, REPO_ROOT, spec_ac_ids
from tests._repo import KIT_FILES

RUN = ".factory/runner/run.py"


@pytest.mark.ac("E16-AC-20")
def test_e16_spec_defines_ac_01_to_ac_20() -> None:
    assert spec_ac_ids("E16") == {f"E16-AC-{n:02d}" for n in range(1, 21)}


@pytest.mark.ac("E16-AC-20")
def test_every_e16_ac_has_a_test(request: pytest.FixtureRequest) -> None:
    missing = spec_ac_ids("E16") - request.config.stash[COLLECTED_AC_IDS]
    assert not missing, f"E16 ACs with no test: {sorted(missing)}"


@pytest.mark.ac("E16-AC-20")
def test_the_runner_is_a_kit_file_and_this_repo_commits_its_install() -> None:
    assert RUN in KIT_FILES
    kit = (REPO_ROOT / "kit" / RUN).read_bytes().replace(b"\r\n", b"\n")
    installed = (REPO_ROOT / RUN).read_bytes().replace(b"\r\n", b"\n")
    assert installed == kit, "run install.py . and commit its output"


@pytest.mark.ac("E16-AC-20")
def test_ci_runs_the_tests_on_ubuntu_macos_and_windows() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "factory-gate.yml").read_text(
        encoding="utf-8"
    )
    for os_name in ("ubuntu-latest", "macos-latest", "windows-latest"):
        assert os_name in workflow
    narrowed = [line for line in workflow.splitlines() if "--checks" in line]
    assert narrowed, "the matrix narrows the checks on some OSes"
    for line in narrowed:
        assert "tests" in line.split("--checks", 1)[1], f"tests must run there: {line.strip()}"


@pytest.mark.ac("E16-AC-20")
def test_lint_types_tests_and_coverage_take_in_the_runner() -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    tool = project["tool"]
    assert "kit/.factory/runner" in tool["mypy"]["files"]
    assert tool["mypy"]["strict"] is True
    assert "kit/.factory/runner" in tool["pytest"]["ini_options"]["pythonpath"]
    assert "kit/.factory/runner" in tool["coverage"]["run"]["source"]
