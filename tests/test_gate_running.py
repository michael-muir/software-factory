"""E05/T3: hardened running - command not found, timeouts, purity, determinism.

Covers E05 AC-10, AC-11, AC-16, AC-17. Expectations come from the E05 spec and ADR 0008.
"""

from __future__ import annotations

import os
import stat
import sys
import time
from pathlib import Path

import pytest

from tests._gate import (
    PASS,
    checks_of,
    exits,
    gate_repo,
    git,
    profile,
    run_gate_json,
    touches,
)

MARKER = {"pyproject.toml": "[project]\nname = 'x'\n"}


def _repo(
    tmp_path: Path,
    checks: dict[str, list[str]],
    timeouts: dict[str, int] | None = None,
) -> Path:
    return gate_repo(
        tmp_path / "repo",
        {"py.toml": profile("py", ["pyproject.toml"], checks, timeouts=timeouts)},
        files=MARKER,
    )


def _check(report: dict[str, object], name: str) -> dict[str, object]:
    return next(c for c in checks_of(report) if c["check"] == name)


def _py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


# --- AC-10: command not found -----------------------------------------------------------------


@pytest.mark.ac("E05-AC-10")
def test_missing_program_fails_that_check_and_the_gate_goes_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(
        tmp_path,
        {
            "format": ["definitely-not-a-real-program-e05", "--check"],
            "lint": touches("ran-lint.txt"),
        },
    )
    code, report = run_gate_json(repo, monkeypatch, capsys)
    assert code == 1
    fmt = _check(report, "format")
    assert fmt["status"] == "fail"
    assert fmt["reason"] == "command not found: definitely-not-a-real-program-e05"
    assert _check(report, "lint")["status"] == "pass"
    assert (repo / "ran-lint.txt").is_file()


@pytest.mark.ac("E05-AC-10")
def test_programs_are_resolved_on_path_including_windows_script_wrappers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if sys.platform == "win32":
        (bin_dir / "fakecmd.cmd").write_text("@exit /b 0\r\n", encoding="utf-8")
    else:
        script = bin_dir / "fakecmd"
        script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    repo = _repo(tmp_path, {"tests": ["fakecmd"]})
    code, report = run_gate_json(repo, monkeypatch, capsys)
    tests = _check(report, "tests")
    assert code == 0, tests
    assert tests["status"] == "pass"
    command = tests["command"]
    assert isinstance(command, list)
    assert Path(command[0]).is_absolute()
    assert "fakecmd" in Path(command[0]).name


# --- AC-11: timeouts --------------------------------------------------------------------------


@pytest.mark.ac("E05-AC-11")
def test_a_check_over_its_timeout_fails_and_the_gate_goes_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(
        tmp_path,
        {"tests": _py("import time; time.sleep(30)"), "coverage": touches("ran-cov.txt")},
        timeouts={"tests": 1},
    )
    started = time.monotonic()
    code, report = run_gate_json(repo, monkeypatch, capsys)
    assert time.monotonic() - started < 15
    assert code == 1
    tests = _check(report, "tests")
    assert tests["status"] == "fail"
    assert tests["reason"] == "timed out after 1s"
    assert _check(report, "coverage")["status"] == "pass"


@pytest.mark.slow
@pytest.mark.ac("E05-AC-11")
def test_a_timeout_kills_the_whole_process_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    grandchild = "import time; time.sleep(3); open('ran-late.txt', 'w').close()"
    parent = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {grandchild!r}]); "
        "time.sleep(30)"
    )
    repo = _repo(tmp_path, {"tests": _py(parent)}, timeouts={"tests": 1})
    started = time.monotonic()
    code, report = run_gate_json(repo, monkeypatch, capsys)
    assert time.monotonic() - started < 15
    assert code == 1
    assert _check(report, "tests")["reason"] == "timed out after 1s"
    time.sleep(4)
    assert not (repo / "ran-late.txt").exists(), "a grandchild survived the timeout"


@pytest.mark.ac("E05-AC-11")
def test_default_timeout_is_600_seconds() -> None:
    import gate

    assert gate.DEFAULT_TIMEOUT_S == 600


# --- AC-16: the gate never changes the repo ---------------------------------------------------


def _status(repo: Path) -> str:
    return git(repo, "status", "--porcelain", "--untracked-files=all")


@pytest.mark.ac("E05-AC-16")
def test_check_that_modifies_a_tracked_file_fails_naming_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(
        tmp_path,
        {"format": _py("open('pyproject.toml', 'a').write('# reformatted\\n')"), "lint": PASS},
    )
    code, report = run_gate_json(repo, monkeypatch, capsys)
    assert code == 1
    fmt = _check(report, "format")
    assert fmt["status"] == "fail"
    assert "modified the repository" in str(fmt["reason"])
    assert "pyproject.toml" in str(fmt["reason"])
    assert _check(report, "lint")["status"] == "pass"


@pytest.mark.ac("E05-AC-16")
def test_check_that_creates_an_untracked_file_fails_naming_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, {"build": _py("open('dist-out.bin', 'w').write('x')")})
    code, report = run_gate_json(repo, monkeypatch, capsys)
    assert code == 1
    build = _check(report, "build")
    assert "modified the repository" in str(build["reason"])
    assert "dist-out.bin" in str(build["reason"])


@pytest.mark.ac("E05-AC-16")
def test_writing_git_ignored_files_is_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, {"tests": touches("ran-ignored.txt")})
    code, report = run_gate_json(repo, monkeypatch, capsys)
    assert code == 0
    assert _check(report, "tests")["status"] == "pass"


@pytest.mark.ac("E05-AC-16")
def test_further_changes_to_an_already_modified_file_are_caught(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, {"format": _py("open('pyproject.toml', 'a').write('# more\\n')")})
    with (repo / "pyproject.toml").open("a", encoding="utf-8") as f:
        f.write("# my uncommitted edit\n")
    code, report = run_gate_json(repo, monkeypatch, capsys)
    assert code == 1
    assert "pyproject.toml" in str(_check(report, "format")["reason"])


@pytest.mark.ac("E05-AC-16")
def test_changes_to_an_existing_untracked_file_are_caught(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, {"lint": _py("open('notes.md', 'a').write('appended\\n')")})
    (repo / "notes.md").write_text("draft\n", encoding="utf-8")
    code, report = run_gate_json(repo, monkeypatch, capsys)
    assert code == 1
    assert "notes.md" in str(_check(report, "lint")["reason"])


@pytest.mark.ac("E05-AC-16")
def test_a_clean_gate_run_leaves_git_status_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, {"format": PASS, "tests": exits(1), "lint": touches("ran-l.txt")})
    (repo / "wip.py").write_text("x = 1\n", encoding="utf-8")
    before = _status(repo)
    run_gate_json(repo, monkeypatch, capsys)
    assert _status(repo) == before


# --- AC-17: determinism -----------------------------------------------------------------------


@pytest.mark.ac("E05-AC-17")
def test_two_runs_on_the_same_state_give_the_same_verdict_and_statuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(
        tmp_path,
        {
            "format": PASS,
            "lint": exits(2),
            "types": ["definitely-not-a-real-program-e05"],
            "tests": touches("ran-t.txt"),
        },
    )
    code_1, first = run_gate_json(repo, monkeypatch, capsys)
    code_2, second = run_gate_json(repo, monkeypatch, capsys)

    def shape(report: dict[str, object]) -> list[tuple[object, ...]]:
        return [(c["profile"], c["check"], c["status"], c["reason"]) for c in checks_of(report)]

    assert code_1 == code_2 == 1
    assert first["verdict"] == second["verdict"] == "fail"
    assert shape(first) == shape(second)
