"""E06/T2: the TS/JS profile and its Stryker helper, proven with real tools.

Covers E06 AC-02, AC-03, AC-04, AC-06, AC-07, AC-08, AC-11, AC-12, AC-13 for TS/JS.
Expectations come from the E06 spec and ADRs 0010-0011, not from the implementation.
"""

from __future__ import annotations

import json
import os
import shutil
import tomllib
from pathlib import Path

import pytest

import gate
import mutate_ts
from factory_installer import cli
from tests._ac import REPO_ROOT
from tests._profile_fixtures import (
    TS_ALSO_FAILS,
    TS_SEEDS,
    VENV_BIN,
    git,
    node_available,
    run_gate,
    run_ts_helper,
    statuses,
    tool_env,
    ts_project,
)
from tests._repo import MANIFEST, git_repo

KIT_PROFILE = REPO_ROOT / "kit" / ".factory" / "gates" / "profiles" / "ts-js.toml"
CHECKS = ("format", "lint", "types", "build", "tests", "coverage", "mutation")
NPX = ["npx", "--no-install"]

needs_node = pytest.mark.skipif(not node_available(), reason="node and npm are not on PATH")


def _profile() -> dict[str, object]:
    with KIT_PROFILE.open("rb") as f:
        return tomllib.load(f)


# --- AC-02: exact profile -----------------------------------------------------------------------


@pytest.mark.ac("E06-AC-02")
def test_ts_js_profile_matches_the_spec() -> None:
    data = _profile()
    assert data["name"] == "ts-js"
    assert data["detect"] == ["package.json"]
    assert data["mutation_paths"] == ["*.ts", "*.tsx", "*.js", "*.jsx", "*.mjs", "*.cjs"]
    checks = data["checks"]
    assert isinstance(checks, dict)
    commands = {name: table["command"] for name, table in checks.items()}
    assert commands == {
        "format": [*NPX, "prettier", "--check", "."],
        "lint": [*NPX, "eslint", "."],
        "types": [*NPX, "tsc", "--noEmit"],
        "build": ["npm", "run", "build", "--if-present"],
        "tests": [*NPX, "vitest", "run"],
        "coverage": [
            *NPX,
            "vitest",
            "run",
            "--coverage",
            "--coverage.thresholds.lines={coverage_percent}",
        ],
        "mutation": [
            "python",
            ".factory/gates/tools/mutate_ts.py",
            "--min",
            "{mutation_percent}",
            "--scope",
            "{mutation_scope}",
            "--base-ref",
            "{base_ref}",
            "{changed_files}",
        ],
    }
    assert checks["mutation"]["timeout_s"] == 1800
    assert all("timeout_s" not in table for name, table in checks.items() if name != "mutation")


# --- AC-03: loads in the gate, ships in the kit -------------------------------------------------


@pytest.mark.ac("E06-AC-03")
def test_ts_js_profile_loads_in_the_gate() -> None:
    profile = gate.parse_profile(KIT_PROFILE, "ts-js.toml")
    assert profile.name == "ts-js"
    assert set(profile.checks) == set(CHECKS)


@pytest.mark.ac("E06-AC-03")
def test_ts_js_profile_and_helper_ship_in_the_kit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path / "repo")
    assert cli.main([str(repo)]) == 0
    capsys.readouterr()
    files = json.loads((repo / MANIFEST).read_text(encoding="utf-8"))["files"]
    assert ".factory/gates/profiles/ts-js.toml" in files
    assert ".factory/gates/tools/mutate_ts.py" in files


# --- AC-04: header comment ----------------------------------------------------------------------


@pytest.mark.ac("E06-AC-04")
def test_ts_js_profile_header_names_tools_ignores_and_how_to_run() -> None:
    lines = KIT_PROFILE.read_text(encoding="utf-8").splitlines()
    first_setting = next(i for i, s in enumerate(lines) if s and not s.startswith("#"))
    header = "\n".join(lines[:first_setting])
    for tool in ("prettier", "eslint", "typescript", "vitest", "stryker"):
        assert tool in header.lower(), tool
    for ignored in ("node_modules", "dist", "coverage", ".stryker-tmp"):
        assert ignored in header, ignored
    assert "npx --no-install" in header
    assert "python .factory/gates/gate.py" in header


# --- AC-06: helper behaviour (units) ------------------------------------------------------------


@pytest.mark.ac("E06-AC-06")
def test_tool_config_files_are_never_mutated() -> None:
    given = [
        "eslint.config.js",
        "vitest.config.ts",
        "vite.config.mjs",
        "configs/stryker.config.cjs",
        "src/config.ts",
        "src/app.configure.ts",
    ]
    assert mutate_ts.select_sources(given) == ["src/config.ts", "src/app.configure.ts"]


@pytest.mark.ac("E06-AC-06")
def test_test_files_and_the_installed_kit_are_never_mutated() -> None:
    given = [
        "src/calc.ts",
        "src/view.tsx",
        "lib/util.mjs",
        "src/calc.test.ts",
        "src/calc.spec.js",
        "src/__tests__/helper.ts",
        ".factory/gates/whatever.js",
        "README.md",
    ]
    assert mutate_ts.select_sources(given) == ["src/calc.ts", "src/view.tsx", "lib/util.mjs"]


@pytest.mark.ac("E06-AC-06")
def test_score_counts_killed_and_timeouts_over_detected_and_undetected() -> None:
    report = {
        "files": {
            "src/a.ts": {
                "mutants": [
                    {"status": "Killed"},
                    {"status": "Timeout"},
                    {"status": "Survived"},
                    {"status": "NoCoverage"},
                    {"status": "CompileError"},
                    {"status": "Ignored"},
                ]
            }
        }
    }
    assert mutate_ts.score(report) == (2, 4)


@pytest.mark.ac("E06-AC-06")
def test_stryker_config_mutates_the_given_files_and_reports_outside_the_repo(
    tmp_path: Path,
) -> None:
    report = tmp_path / "out" / "mutation.json"
    config = mutate_ts.stryker_config(["src/calc.ts"], report)
    assert config["testRunner"] == "vitest"
    assert config["mutate"] == ["src/calc.ts"]
    assert config["reporters"] == ["json"]
    assert Path(config["jsonReporter"]["fileName"]) == report


@pytest.mark.slow
@needs_node
@pytest.mark.ac("E06-AC-06")
def test_helper_passes_strong_tests_and_fails_weak_ones(tmp_path: Path) -> None:
    strong = ts_project(tmp_path / "strong")
    weak = ts_project(tmp_path / "weak", TS_SEEDS["mutation"])
    ok = run_ts_helper(strong, "--min", "60", "src/calc.ts")
    assert ok.returncode == 0, ok.stdout + ok.stderr
    low = run_ts_helper(weak, "--min", "60", "src/calc.ts")
    assert low.returncode == 1, low.stdout + low.stderr


# --- AC-07: nothing to mutate, missing tools ----------------------------------------------------


@pytest.mark.ac("E06-AC-07")
def test_only_test_files_means_nothing_to_mutate(tmp_path: Path) -> None:
    project = git_repo(tmp_path / "p")
    shutil.copytree(REPO_ROOT / "kit" / ".factory", project / ".factory")
    result = run_ts_helper(project, "--min", "60", "src/calc.test.ts")
    assert result.returncode == 0
    assert "no source files to mutate" in result.stdout


@pytest.mark.ac("E06-AC-07")
def test_missing_npx_exits_2_naming_it(tmp_path: Path) -> None:
    project = git_repo(tmp_path / "p")
    shutil.copytree(REPO_ROOT / "kit" / ".factory", project / ".factory")
    env = dict(os.environ)
    env["PATH"] = str(VENV_BIN)
    result = run_ts_helper(project, "--min", "60", "src/calc.ts", env=env)
    assert result.returncode == 2
    assert "npx" in result.stdout + result.stderr


@pytest.mark.slow
@needs_node
@pytest.mark.ac("E06-AC-07")
def test_missing_stryker_exits_2_naming_it(tmp_path: Path) -> None:
    project = ts_project(tmp_path / "p")
    link = project / "node_modules"
    try:
        link.unlink()  # a symlink
    except OSError:
        os.rmdir(link)  # a Windows junction is removed like an empty directory
    assert not link.exists()
    result = run_ts_helper(project, "--min", "60", "src/calc.ts")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "stryker" in (result.stdout + result.stderr).lower()


# --- AC-08: state outside the repo --------------------------------------------------------------


@pytest.mark.slow
@needs_node
@pytest.mark.ac("E06-AC-08")
def test_helper_leaves_the_repo_and_its_temp_dir_clean(tmp_path: Path) -> None:
    project = ts_project(tmp_path / "p")
    scratch = tmp_path / "scratch-tmp"
    scratch.mkdir()
    env = tool_env()
    for var in ("TMP", "TEMP", "TMPDIR"):
        env[var] = str(scratch)
    before = git(project, "status", "--porcelain", "--untracked-files=all")
    result = run_ts_helper(project, "--min", "60", "src/calc.ts", env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(project, "status", "--porcelain", "--untracked-files=all") == before
    assert not (project / ".stryker-tmp").exists()
    assert not (project / "reports").exists()
    leftovers = [p.name for p in scratch.iterdir() if p.name.startswith("factory-mutate-")]
    assert leftovers == []


# --- AC-11 / AC-12: reference and seeds through the real gate -----------------------------------


@pytest.mark.slow
@needs_node
@pytest.mark.ac("E06-AC-11")
def test_ts_js_reference_passes_every_check(tmp_path: Path) -> None:
    code, report = run_gate(ts_project(tmp_path / "ref"))
    assert code == 0, json.dumps(report, indent=2)
    assert report["profiles"] == ["ts-js"]
    assert statuses(report) == {c: "pass" for c in CHECKS}


@pytest.mark.slow
@needs_node
@pytest.mark.ac("E06-AC-12")
@pytest.mark.parametrize("check", sorted(TS_SEEDS))
def test_each_ts_js_seed_fails_its_check(tmp_path: Path, check: str) -> None:
    code, report = run_gate(ts_project(tmp_path / check, TS_SEEDS[check]))
    assert code == 1, json.dumps(report, indent=2)
    failing = {check} | TS_ALSO_FAILS.get(check, set())
    expected = {c: ("fail" if c in failing else "pass") for c in CHECKS}
    assert statuses(report) == expected, json.dumps(report, indent=2)


# --- AC-13: skip only without node --------------------------------------------------------------


@pytest.mark.ac("E06-AC-13")
def test_ts_tests_skip_only_when_node_or_npm_is_missing() -> None:
    assert node_available() == (
        shutil.which("node") is not None and shutil.which("npm") is not None
    )
    condition, *_ = needs_node.args
    assert condition is (not node_available())
    assert "node" in needs_node.kwargs["reason"]
