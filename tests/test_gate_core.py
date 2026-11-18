"""E05/T2: gate CLI, settings, profiles, basic running, report and exit codes.

Covers E05 AC-01 to AC-09, AC-18, AC-19, plus the ADR 0007 defaults mirror (AC-20).
Expectations come from the E05 spec and ADRs 0007-0008, not from the implementation.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

import gate
from factory_installer import config_schema
from tests._gate import (
    CHECK_ORDER,
    GATE_PY,
    PASS,
    checks_of,
    exits,
    gate_repo,
    prints,
    profile,
    run_gate,
    run_gate_json,
    touches,
)

MARKER = {"pyproject.toml": "[project]\nname = 'x'\n"}


def _one_profile_repo(tmp_path: Path, **checks: list[str]) -> Path:
    return gate_repo(
        tmp_path / "repo",
        {"py.toml": profile("py", ["pyproject.toml"], checks)},
        files=MARKER,
    )


# --- AC-01: gates the git root ----------------------------------------------------------------


@pytest.mark.ac("E05-AC-01")
def test_gate_run_from_a_subdirectory_gates_the_repo_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _one_profile_repo(tmp_path, tests=touches("ran-tests.txt"))
    sub = repo / "src" / "pkg"
    sub.mkdir(parents=True)
    code, _ = run_gate(sub, monkeypatch, capsys)
    assert code == 0
    assert (repo / "ran-tests.txt").is_file()
    assert not (sub / "ran-tests.txt").exists()


@pytest.mark.ac("E05-AC-01")
@pytest.mark.ac("E05-AC-03")
def test_gate_outside_a_git_repo_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    code, output = run_gate(plain, monkeypatch, capsys)
    assert code == 2
    assert "git" in output.lower()


# --- AC-02: standard library only -------------------------------------------------------------


@pytest.mark.ac("E05-AC-02")
def test_gate_runs_isolated_without_site_packages(tmp_path: Path) -> None:
    repo = _one_profile_repo(tmp_path, tests=PASS)
    result = subprocess.run(
        [sys.executable, "-I", "-S", str(GATE_PY)],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.ac("E05-AC-02")
def test_gate_imports_only_the_standard_library() -> None:
    tree = ast.parse(GATE_PY.read_text(encoding="utf-8"))
    foreign: list[str] = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        foreign += [n for n in names if n.split(".")[0] not in sys.stdlib_module_names]
    assert not foreign, f"non-stdlib imports in gate.py: {foreign}"


# --- AC-03: exit codes ------------------------------------------------------------------------


@pytest.mark.ac("E05-AC-03")
def test_all_checks_pass_exits_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _one_profile_repo(tmp_path, format=PASS, tests=PASS)
    code, _ = run_gate(repo, monkeypatch, capsys)
    assert code == 0


@pytest.mark.ac("E05-AC-03")
def test_a_failing_check_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _one_profile_repo(tmp_path, format=PASS, tests=exits(3))
    code, _ = run_gate(repo, monkeypatch, capsys)
    assert code == 1


@pytest.mark.ac("E05-AC-03")
def test_a_profile_error_exits_2_before_any_check_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = gate_repo(
        tmp_path / "repo",
        {
            "a.toml": profile("a", ["pyproject.toml"], {"tests": touches("ran-a.txt")}),
            "broken.toml": "name = \n",
        },
        files=MARKER,
    )
    code, _ = run_gate(repo, monkeypatch, capsys)
    assert code == 2
    assert not (repo / "ran-a.txt").exists()


# --- AC-04: profile validation ----------------------------------------------------------------


@pytest.mark.ac("E05-AC-04")
@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("name = \n", "toml"),
        ('detect = ["x"]\n', "name"),
        ('name = "b"\n[checks.speed]\ncommand = ["x"]\n', "speed"),
        ('name = "b"\n[checks.tests]\ncommand = "pytest"\n', "command"),
        ('name = "b"\n[checks.tests]\ncommand = []\n', "command"),
        ('name = "b"\n[checks.tests]\ncommand = ["pytest", 3]\n', "command"),
        (
            'name = "b"\n[checks.mutation]\ncommand = ["mut", "--paths={changed_files}"]\n',
            "changed_files",
        ),
    ],
)
def test_malformed_profile_exits_2_naming_file_and_problem(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    text: str,
    problem: str,
) -> None:
    repo = gate_repo(tmp_path / "repo", {"bad.toml": text}, files=MARKER)
    code, output = run_gate(repo, monkeypatch, capsys)
    assert code == 2
    assert any("bad.toml" in line and problem in line.lower() for line in output.splitlines()), (
        output
    )


# --- AC-05 / AC-06: selection -----------------------------------------------------------------


@pytest.mark.ac("E05-AC-05")
def test_config_profiles_select_exactly_those_profiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = gate_repo(
        tmp_path / "repo",
        {
            "a.toml": profile("a", ["pyproject.toml"], {"tests": touches("ran-a.txt")}),
            "b.toml": profile("b", ["pyproject.toml"], {"tests": touches("ran-b.txt")}),
        },
        config='[gates]\nprofiles = ["b"]\n',
        files=MARKER,
    )
    code, report = run_gate_json(repo, monkeypatch, capsys)
    assert code == 0
    assert report["profiles"] == ["b"]
    assert (repo / "ran-b.txt").is_file()
    assert not (repo / "ran-a.txt").exists()


@pytest.mark.ac("E05-AC-05")
def test_without_config_profiles_are_detected_by_marker_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = gate_repo(
        tmp_path / "repo",
        {
            "py.toml": profile("py", ["pyproject.toml"], {"tests": PASS}),
            "js.toml": profile("js", ["package.json"], {"tests": PASS}),
        },
        files=MARKER,
    )
    code, report = run_gate_json(repo, monkeypatch, capsys)
    assert code == 0
    assert report["profiles"] == ["py"]


@pytest.mark.ac("E05-AC-06")
def test_unknown_profile_in_config_exits_2_listing_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = gate_repo(
        tmp_path / "repo",
        {"py.toml": profile("py", ["pyproject.toml"], {"tests": PASS})},
        config='[gates]\nprofiles = ["nope"]\n',
        files=MARKER,
    )
    code, output = run_gate(repo, monkeypatch, capsys)
    assert code == 2
    assert "nope" in output
    assert "py" in output


@pytest.mark.ac("E05-AC-06")
def test_no_applicable_profile_exits_2_listing_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = gate_repo(
        tmp_path / "repo",
        {"js.toml": profile("js", ["package.json"], {"tests": PASS})},
        files=MARKER,
    )
    code, output = run_gate(repo, monkeypatch, capsys)
    assert code == 2
    assert "js" in output


# --- AC-07: fixed order, n/a --------------------------------------------------------------------


@pytest.mark.ac("E05-AC-07")
def test_checks_report_in_fixed_order_with_undefined_ones_not_applicable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _one_profile_repo(tmp_path, tests=PASS, format=PASS)
    code, report = run_gate_json(repo, monkeypatch, capsys)
    assert code == 0
    checks = checks_of(report)
    assert [c["check"] for c in checks] == list(CHECK_ORDER)
    statuses = {c["check"]: c["status"] for c in checks}
    assert statuses["format"] == statuses["tests"] == "pass"
    assert all(statuses[c] == "n/a" for c in ("lint", "types", "build", "coverage", "mutation"))


@pytest.mark.ac("E05-AC-07")
def test_two_profiles_report_profile_by_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = gate_repo(
        tmp_path / "repo",
        {
            "a.toml": profile("a", ["pyproject.toml"], {"tests": PASS}),
            "b.toml": profile("b", ["pyproject.toml"], {"lint": PASS}),
        },
        files=MARKER,
    )
    _, report = run_gate_json(repo, monkeypatch, capsys)
    pairs = [(c["profile"], c["check"]) for c in checks_of(report)]
    assert pairs == [("a", c) for c in CHECK_ORDER] + [("b", c) for c in CHECK_ORDER]


# --- AC-08 / AC-09: running -------------------------------------------------------------------


@pytest.mark.ac("E05-AC-08")
def test_every_check_runs_after_an_earlier_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _one_profile_repo(tmp_path, format=exits(1), lint=touches("ran-lint.txt"))
    code, report = run_gate_json(repo, monkeypatch, capsys)
    assert code == 1
    statuses = {c["check"]: c["status"] for c in checks_of(report)}
    assert statuses["format"] == "fail"
    assert statuses["lint"] == "pass"
    assert (repo / "ran-lint.txt").is_file()


@pytest.mark.ac("E05-AC-08")
def test_any_nonzero_exit_fails_with_the_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _one_profile_repo(tmp_path, tests=exits(42))
    _, report = run_gate_json(repo, monkeypatch, capsys)
    tests = next(c for c in checks_of(report) if c["check"] == "tests")
    assert tests["status"] == "fail"
    assert tests["exit_code"] == 42


@pytest.mark.ac("E05-AC-09")
def test_commands_run_from_the_repo_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cwd_probe = [sys.executable, "-c", "import os; print('CWD=' + os.getcwd())"]
    repo = _one_profile_repo(tmp_path, tests=cwd_probe)
    sub = repo / "deep" / "er"
    sub.mkdir(parents=True)
    _, report = run_gate_json(sub, monkeypatch, capsys)
    tests = next(c for c in checks_of(report) if c["check"] == "tests")
    tail = str(tests["output_tail"])
    assert f"CWD={repo.resolve()}" in tail or f"CWD={repo}" in tail, tail


@pytest.mark.ac("E05-AC-09")
def test_arguments_are_never_interpreted_by_a_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    echo_arg = [sys.executable, "-c", "import sys; print('ARG=' + sys.argv[1])", "x && exit 7"]
    repo = _one_profile_repo(tmp_path, tests=echo_arg)
    code, report = run_gate_json(repo, monkeypatch, capsys)
    assert code == 0
    tests = next(c for c in checks_of(report) if c["check"] == "tests")
    assert "ARG=x && exit 7" in str(tests["output_tail"])


# --- AC-18 / AC-19: report --------------------------------------------------------------------


@pytest.mark.ac("E05-AC-18")
def test_text_report_has_a_line_per_check_and_ends_with_the_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _one_profile_repo(tmp_path, tests=PASS)
    code, output = run_gate(repo, monkeypatch, capsys)
    assert code == 0
    lines = output.strip().splitlines()
    for check in CHECK_ORDER:
        assert any("py" in line and check in line for line in lines), check
    assert any("tests" in line and "pass" in line and "s" in line for line in lines)
    assert lines[-1].strip() == "PASS"


@pytest.mark.ac("E05-AC-18")
def test_failed_check_shows_reason_and_last_40_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hundred = [f"line-{n:03d}" for n in range(1, 101)]
    repo = _one_profile_repo(tmp_path, tests=prints(*hundred, code=5))
    code, output = run_gate(repo, monkeypatch, capsys)
    assert code == 1
    assert "line-100" in output
    assert "line-061" in output
    assert "line-060" not in output
    assert "5" in output
    assert output.strip().splitlines()[-1].strip() == "FAIL"


@pytest.mark.ac("E05-AC-19")
def test_json_report_has_the_specified_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _one_profile_repo(tmp_path, tests=exits(1), format=PASS)
    code, report = run_gate_json(repo, monkeypatch, capsys)
    assert code == 1
    assert report["verdict"] == "fail"
    assert report["base_ref"] == "main"
    assert report["profiles"] == ["py"]
    assert isinstance(report["changed_files"], list)
    fields = {"profile", "check", "status", "reason", "exit_code", "duration_s", "command"}
    for check in checks_of(report):
        assert fields | {"output_tail"} <= set(check), check
    tests = next(c for c in checks_of(report) if c["check"] == "tests")
    assert tests["command"] == exits(1)
    assert tests["reason"]


# --- ADR 0007: the gate's defaults mirror config_schema ---------------------------------------


@pytest.mark.ac("E05-AC-20")
def test_gate_defaults_mirror_the_config_schema() -> None:
    schema = config_schema.SECTIONS["gates"]
    assert set(gate.DEFAULTS) <= set(schema)
    for key, value in gate.DEFAULTS.items():
        assert value == schema[key].default, key


@pytest.mark.ac("E05-AC-20")
def test_gate_rejects_a_bad_gates_setting_with_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = gate_repo(
        tmp_path / "repo",
        {"py.toml": profile("py", ["pyproject.toml"], {"tests": PASS})},
        config='[gates]\nprofiles = "py"\n',
        files=MARKER,
    )
    code, output = run_gate(repo, monkeypatch, capsys)
    assert code == 2
    assert "gates.profiles" in output
