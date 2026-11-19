"""E06/T1: the Python profile and its cosmic-ray helper, proven with real tools.

Covers E06 AC-01, AC-03, AC-04, AC-05, AC-05b, AC-07, AC-08, AC-09, AC-10 for Python.
Expectations come from the E06 spec and ADRs 0010-0011, not from the implementation.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import gate
import mutate_python
from factory_installer import cli
from tests._ac import REPO_ROOT
from tests._profile_fixtures import (
    PYTHON_SEEDS,
    git,
    python_project,
    run_gate,
    run_helper,
    statuses,
    tool_env,
)
from tests._repo import MANIFEST, git_repo

KIT_PROFILE = REPO_ROOT / "kit" / ".factory" / "gates" / "profiles" / "python.toml"
CHECKS = ("format", "lint", "types", "build", "tests", "coverage", "mutation")


def _profile() -> dict[str, object]:
    with KIT_PROFILE.open("rb") as f:
        return tomllib.load(f)


# --- AC-01: exact profile -----------------------------------------------------------------------


@pytest.mark.ac("E06-AC-01")
def test_python_profile_matches_the_spec() -> None:
    data = _profile()
    assert data["name"] == "python"
    assert data["detect"] == ["pyproject.toml", "setup.py", "setup.cfg"]
    assert data["mutation_paths"] == ["*.py"]
    checks = data["checks"]
    assert isinstance(checks, dict)
    commands = {name: table["command"] for name, table in checks.items()}
    assert commands == {
        "format": ["ruff", "format", "--check", "--extend-exclude", "./.factory", "."],
        "lint": ["ruff", "check", "--extend-exclude", "./.factory", "."],
        "types": ["mypy"],
        "tests": ["coverage", "run", "-m", "pytest"],
        "coverage": ["coverage", "report", "--fail-under={coverage_percent}"],
        "mutation": [
            "python",
            ".factory/gates/tools/mutate_python.py",
            "--min",
            "{mutation_percent}",
            "{changed_files}",
        ],
    }
    assert checks["mutation"]["timeout_s"] == 1800
    # E07/T4 change: the Windows CI runner needs more than 600 s for this repo's tests.
    assert checks["tests"]["timeout_s"] == 1200
    timed = ("mutation", "tests")
    assert all("timeout_s" not in table for name, table in checks.items() if name not in timed)


# --- AC-03: loads in the gate, ships in the kit -------------------------------------------------


@pytest.mark.ac("E06-AC-03")
def test_python_profile_loads_in_the_gate() -> None:
    profile = gate.parse_profile(KIT_PROFILE, "python.toml")
    assert profile.name == "python"
    assert set(profile.checks) == {"format", "lint", "types", "tests", "coverage", "mutation"}


@pytest.mark.ac("E06-AC-03")
def test_python_profile_and_helper_ship_in_the_kit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path / "repo")
    assert cli.main([str(repo)]) == 0
    capsys.readouterr()
    files = json.loads((repo / MANIFEST).read_text(encoding="utf-8"))["files"]
    assert ".factory/gates/profiles/python.toml" in files
    assert ".factory/gates/tools/mutate_python.py" in files


# --- AC-04: header comment ----------------------------------------------------------------------


@pytest.mark.ac("E06-AC-04")
def test_python_profile_header_names_tools_ignores_and_how_to_run() -> None:
    lines = KIT_PROFILE.read_text(encoding="utf-8").splitlines()
    header = "\n".join(
        line
        for line in lines[: next(i for i, s in enumerate(lines) if s and not s.startswith("#"))]
    )
    for tool in ("ruff", "mypy", "pytest", "coverage", "cosmic-ray"):
        assert tool in header, tool
    for ignored in (".coverage", ".mypy_cache", ".ruff_cache", ".pytest_cache"):
        assert ignored in header, ignored
    assert "uv run python .factory/gates/gate.py" in header


# --- AC-05: helper behaviour --------------------------------------------------------------------


@pytest.mark.ac("E06-AC-05")
def test_the_installed_kit_is_never_mutated() -> None:
    given = [
        ".factory/gates/gate.py",
        ".factory/gates/tools/mutate_python.py",
        "calc.py",
        "kit/.factory/gates/gate.py",
    ]
    assert mutate_python.select_sources(given) == ["calc.py", "kit/.factory/gates/gate.py"]


@pytest.mark.ac("E06-AC-05")
def test_test_files_are_never_mutated() -> None:
    given = [
        "calc.py",
        "pkg/core.py",
        "test_calc.py",
        "calc_test.py",
        "conftest.py",
        "tests/helpers.py",
        "pkg/test/util.py",
        "pkg/tests/deep/x.py",
    ]
    assert mutate_python.select_sources(given) == ["calc.py", "pkg/core.py"]


@pytest.mark.ac("E06-AC-05")
def test_kill_test_uses_the_pinned_interpreter() -> None:
    assert mutate_python.test_command("/py/bin/python3", []) == [
        "/py/bin/python3",
        "-m",
        "pytest",
        "-q",
        "-x",
    ]


def only_git_on_path(folder: Path) -> str:
    """A PATH with git (the helper copies the project with it) and no Python."""
    git = shutil.which("git")
    assert git is not None
    if os.name == "nt":  # Git for Windows keeps git.exe in a folder of its own (Git\\cmd)
        return str(Path(git).parent)
    folder.mkdir()
    (folder / "git").symlink_to(git)
    return str(folder)


@pytest.mark.slow
@pytest.mark.ac("E06-AC-05")
def test_helper_works_with_no_python_on_path(tmp_path: Path) -> None:
    project = python_project(tmp_path / "p")
    env = dict(os.environ)
    env["PATH"] = only_git_on_path(tmp_path / "bin")
    result = run_helper(project, "--min", "60", "calc.py", env=env)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.slow
@pytest.mark.ac("E06-AC-05")
def test_helper_passes_strong_tests_and_fails_weak_ones(tmp_path: Path) -> None:
    strong = python_project(tmp_path / "strong")
    weak = python_project(tmp_path / "weak", PYTHON_SEEDS["mutation"])
    assert run_helper(strong, "--min", "60", "calc.py").returncode == 0
    result = run_helper(weak, "--min", "60", "calc.py")
    assert result.returncode == 1, result.stdout + result.stderr


# --- AC-05b: sampling and narrowing -------------------------------------------------------------


@pytest.mark.ac("E06-AC-05b")
def test_sampling_is_deterministic_and_capped() -> None:
    ids = [f"job-{n:03d}" for n in range(200)]
    first = mutate_python.sample(ids, b"seed-a", 25)
    assert first == mutate_python.sample(list(reversed(ids)), b"seed-a", 25)
    assert len(first) == 25
    assert set(first) <= set(ids)
    assert mutate_python.sample(ids, b"seed-b", 25) != first
    assert sorted(mutate_python.sample(ids[:10], b"seed-a", 25)) == sorted(ids[:10])


@pytest.mark.ac("E06-AC-05b")
def test_settings_default_and_read_from_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    settings = mutate_python.load_settings(tmp_path)
    assert settings.max_mutants == 100
    assert settings.test_args == []
    (tmp_path / "pyproject.toml").write_text(
        "[tool.software-factory.mutation]\nmax-mutants = 7\ntest-args = ['-k', 'fast']\n",
        encoding="utf-8",
    )
    settings = mutate_python.load_settings(tmp_path)
    assert settings.max_mutants == 7
    assert settings.test_args == ["-k", "fast"]
    assert mutate_python.test_command("py", settings.test_args)[-2:] == ["-k", "fast"]


@pytest.mark.ac("E06-AC-05b")
@pytest.mark.parametrize(
    ("snippet", "key"),
    [("max-mutants = 0", "max-mutants"), ("test-args = 'fast'", "test-args")],
)
@pytest.mark.slow
def test_invalid_settings_exit_2_naming_the_key(tmp_path: Path, snippet: str, key: str) -> None:
    project = python_project(
        tmp_path / "p", extra_pyproject=f"[tool.software-factory.mutation]\n{snippet}\n"
    )
    result = run_helper(project, "--min", "60", "calc.py")
    assert result.returncode == 2
    assert key in result.stdout + result.stderr


@pytest.mark.slow
@pytest.mark.ac("E06-AC-05b")
def test_a_capped_run_says_how_many_were_sampled(tmp_path: Path) -> None:
    project = python_project(
        tmp_path / "p", extra_pyproject="[tool.software-factory.mutation]\nmax-mutants = 3\n"
    )
    result = run_helper(project, "--min", "0", "calc.py")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "sampled 3 of" in result.stdout


# --- AC-07: nothing to mutate, missing tools ----------------------------------------------------


@pytest.mark.slow
@pytest.mark.ac("E06-AC-07")
def test_only_test_files_means_nothing_to_mutate(tmp_path: Path) -> None:
    project = python_project(tmp_path / "p")
    result = run_helper(project, "--min", "60", "test_calc.py")
    assert result.returncode == 0
    assert "no source files to mutate" in result.stdout


@pytest.mark.slow
@pytest.mark.ac("E06-AC-07")
def test_missing_cosmic_ray_exits_2_naming_it(tmp_path: Path) -> None:
    project = python_project(tmp_path / "p")
    isolated = _run_helper_without_site_packages(project)
    assert isolated.returncode == 2
    assert "cosmic-ray" in isolated.stdout + isolated.stderr


def _run_helper_without_site_packages(project: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            ".factory/gates/tools/mutate_python.py",
            "--min",
            "60",
            "calc.py",
        ],
        cwd=project,
        capture_output=True,
        text=True,
        env=tool_env(),
        check=False,
    )


# --- AC-08: state outside the repo --------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.ac("E06-AC-08")
def test_helper_leaves_the_repo_and_its_temp_dir_clean(tmp_path: Path) -> None:
    project = python_project(tmp_path / "p")
    scratch = tmp_path / "scratch-tmp"
    scratch.mkdir()
    env = tool_env()
    for var in ("TMP", "TEMP", "TMPDIR"):
        env[var] = str(scratch)
    before = git(project, "status", "--porcelain", "--untracked-files=all")
    result = run_helper(project, "--min", "60", "calc.py", env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(project, "status", "--porcelain", "--untracked-files=all") == before
    assert list(scratch.iterdir()) == []
    assert (project / "calc.py").read_text(encoding="utf-8") == (
        REPO_ROOT / "tests" / "fixtures" / "python-ref" / "calc.py"
    ).read_text(encoding="utf-8")


# --- AC-09 / AC-10: reference and seeds through the real gate -----------------------------------


@pytest.mark.slow
@pytest.mark.ac("E06-AC-09")
def test_python_reference_passes_every_check(tmp_path: Path) -> None:
    code, report = run_gate(python_project(tmp_path / "ref"))
    assert code == 0, report
    assert report["profiles"] == ["python"]
    result = statuses(report)
    assert result == {c: ("n/a" if c == "build" else "pass") for c in CHECKS}, report


@pytest.mark.slow
@pytest.mark.ac("E06-AC-10")
@pytest.mark.parametrize("check", sorted(PYTHON_SEEDS))
def test_each_python_seed_fails_exactly_its_check(tmp_path: Path, check: str) -> None:
    code, report = run_gate(python_project(tmp_path / check, PYTHON_SEEDS[check]))
    assert code == 1, report
    result = statuses(report)
    expected = {c: ("n/a" if c == "build" else "pass") for c in CHECKS} | {check: "fail"}
    assert result == expected, json.dumps(report, indent=2)
