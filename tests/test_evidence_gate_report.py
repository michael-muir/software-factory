"""E08/T1: the gate report names its commit, `--json-out` saves the JSON from the same run, and
`Report.from_json` rebuilds a report (ADR 0025).

Covers E08 AC-01 and AC-02. Expectations come from the E08 spec and design note, not from the
implementation.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import gate
from tests._gate import (
    PASS,
    checks_of,
    exits,
    gate_repo,
    git,
    profile,
    run_gate,
    run_gate_json,
    touches,
)

MARKER = {"pyproject.toml": "[project]\nname = 'x'\n"}
OLD_KEYS = ["verdict", "root", "base_ref", "profiles", "changed_files", "locks", "docs", "checks"]


def _repo(tmp_path: Path, checks: dict[str, list[str]] | None = None) -> Path:
    return gate_repo(
        tmp_path / "repo",
        {"py.toml": profile("py", ["pyproject.toml"], checks or {"format": PASS, "lint": PASS})},
        files=MARKER,
    )


def _head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").strip()


def _lines(output: str) -> list[str]:
    return output.strip().splitlines()


# --- AC-01: the commit and the dirty flag --------------------------------------------------------


@pytest.mark.ac("E08-AC-01")
def test_the_json_report_names_the_commit_and_a_clean_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    code, report = run_gate_json(repo, monkeypatch, capsys)
    assert code == 0
    assert report["commit"] == _head(repo)
    assert report["dirty"] is False


@pytest.mark.ac("E08-AC-01")
def test_a_tracked_edit_makes_the_report_dirty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\nname = 'y'\n", encoding="utf-8")
    _, report = run_gate_json(repo, monkeypatch, capsys)
    assert report["commit"] == _head(repo)
    assert report["dirty"] is True


@pytest.mark.ac("E08-AC-01")
def test_a_staged_change_makes_the_report_dirty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    (repo / "new.txt").write_text("new\n", encoding="utf-8")
    git(repo, "add", "new.txt")
    _, report = run_gate_json(repo, monkeypatch, capsys)
    assert report["dirty"] is True


@pytest.mark.ac("E08-AC-01")
def test_untracked_files_do_not_make_the_report_dirty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    (repo / "scratch.txt").write_text("scratch\n", encoding="utf-8")
    _, report = run_gate_json(repo, monkeypatch, capsys)
    assert report["dirty"] is False


@pytest.mark.ac("E08-AC-01")
def test_the_text_report_has_a_commit_line_after_the_base_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    code, output = run_gate(repo, monkeypatch, capsys)
    assert code == 0
    lines = _lines(output)
    base = next(i for i, line in enumerate(lines) if line.startswith("Base: "))
    assert lines[base + 1] == f"Commit: {_head(repo)}"


@pytest.mark.ac("E08-AC-01")
def test_a_dirty_text_report_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\nname = 'y'\n", encoding="utf-8")
    _, output = run_gate(repo, monkeypatch, capsys)
    assert f"Commit: {_head(repo)} (uncommitted changes)" in _lines(output)


@pytest.mark.ac("E08-AC-01")
def test_a_repo_with_no_commits_names_no_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "fresh"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    profiles = repo / ".factory" / "gates" / "profiles"
    profiles.mkdir(parents=True)
    (profiles / "py.toml").write_text(
        profile("py", ["pyproject.toml"], {"format": PASS}), encoding="utf-8"
    )
    (repo / "pyproject.toml").write_text(MARKER["pyproject.toml"], encoding="utf-8")
    _, report = run_gate_json(repo, monkeypatch, capsys)
    assert report["commit"] is None
    _, output = run_gate(repo, monkeypatch, capsys)
    assert "Commit: none" in _lines(output)


@pytest.mark.ac("E08-AC-01")
def test_everything_already_in_the_json_report_stays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    _, report = run_gate_json(repo, monkeypatch, capsys)
    assert [key for key in report if key in OLD_KEYS] == OLD_KEYS
    assert report["verdict"] == "pass"
    assert report["locks"] == {"locked": 0, "broken": []}
    assert [c["check"] for c in checks_of(report)][:2] == ["format", "lint"]


@pytest.mark.ac("E08-AC-01")
def test_everything_already_in_the_text_report_stays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    _, output = run_gate(repo, monkeypatch, capsys)
    lines = _lines(output)
    assert lines[0] == f"Gate: {repo}"
    assert lines[1].startswith("Base: ")
    assert lines[2].startswith("Commit: ")
    assert lines[3].startswith("Locks: ")
    assert lines[4].startswith("Docs: ")
    assert lines[-1] == "PASS"


# --- AC-02: --json-out --------------------------------------------------------------------------


@pytest.mark.ac("E08-AC-02")
def test_json_out_prints_text_and_saves_the_same_runs_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    out = tmp_path / "gate-report.json"
    code, output = run_gate(repo, monkeypatch, capsys, "--json-out", str(out))
    assert code == 0
    assert _lines(output)[-1] == "PASS"
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["verdict"] == "pass"
    assert data["commit"] == _head(repo)
    # Same run: the saved JSON rebuilds exactly the text that was printed, durations included.
    assert gate.Report.from_json(data).to_text() == output.strip()


@pytest.mark.ac("E08-AC-02")
def test_json_out_with_json_prints_the_same_json_it_saves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    out = tmp_path / "gate-report.json"
    code, output = run_gate(repo, monkeypatch, capsys, "--json", "--json-out", str(out))
    assert code == 0
    assert json.loads(output) == json.loads(out.read_text(encoding="utf-8"))


@pytest.mark.ac("E08-AC-02")
def test_json_out_is_written_when_the_verdict_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, {"format": PASS, "lint": exits(1)})
    out = tmp_path / "gate-report.json"
    code, output = run_gate(repo, monkeypatch, capsys, "--json-out", str(out))
    assert code == 1
    assert _lines(output)[-1] == "FAIL"
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["verdict"] == "fail"
    assert gate.Report.from_json(data).to_text() == output.strip()


@pytest.mark.ac("E08-AC-02")
def test_json_out_uses_lf_and_ends_with_a_newline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    out = tmp_path / "gate-report.json"
    run_gate(repo, monkeypatch, capsys, "--json-out", str(out))
    raw = out.read_bytes()
    assert b"\r\n" not in raw
    assert raw.endswith(b"}\n")


@pytest.mark.ac("E08-AC-02")
def test_a_relative_json_out_is_relative_to_the_working_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    (repo / "out").mkdir()
    code, _ = run_gate(repo, monkeypatch, capsys, "--json-out", "out/report.json")
    assert code == 0
    assert json.loads((repo / "out" / "report.json").read_text(encoding="utf-8"))["verdict"]


@pytest.mark.ac("E08-AC-02")
@pytest.mark.parametrize("where", ["missing-folder/report.json", "a-folder"])
def test_a_json_out_that_cannot_be_written_exits_2_before_any_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], where: str
) -> None:
    repo = _repo(tmp_path, {"format": touches("ran-format.txt"), "lint": PASS})
    (tmp_path / "a-folder").mkdir()
    code, output = run_gate(repo, monkeypatch, capsys, "--json-out", str(tmp_path / where))
    assert code == 2
    assert "--json-out" in output
    assert not (repo / "ran-format.txt").exists(), "no check may run"


# --- AC-02: Report.from_json, the one renderer (ADR 0025) ----------------------------------------


def _full_report() -> gate.Report:
    return gate.Report(
        root="/work/repo",
        base_ref="origin/main",
        profiles=["python", "ts"],
        changed_files=["a.py", "b.ts"],
        results=[
            gate.Result("python", "format", "pass", exit_code=0, duration_s=0.21, command=["x"]),
            gate.Result(
                "python",
                "tests",
                "fail",
                reason="exit 1",
                exit_code=1,
                duration_s=12.5,
                command=["pytest"],
                output_tail="E   assert 1 == 2\nFAILED t.py::test_x",
            ),
            gate.Result("ts", "mutation", "skipped", reason="no changed files"),
            gate.Result("ts", "build", "n/a", reason="not defined by the profile"),
        ],
        locked=3,
        broken_locks=[],
        docs_checked=5,
        doc_problems=["docs/specs/E99-x.md: ## Goal: missing heading"],
        commit="0123456789abcdef0123456789abcdef01234567",
        dirty=False,
    )


@pytest.mark.ac("E08-AC-02")
def test_from_json_round_trips_text_and_json() -> None:
    report = _full_report()
    again = gate.Report.from_json(json.loads(report.to_json()))
    assert again.to_text() == report.to_text()
    assert again.to_json() == report.to_json()


@pytest.mark.ac("E08-AC-02")
def test_from_json_round_trips_broken_locks_and_a_dirty_tree() -> None:
    report = _full_report()
    report.results = []
    report.broken_locks = ["tests/t.py: locked by E08-T1: changed"]
    report.dirty = True
    again = gate.Report.from_json(json.loads(report.to_json()))
    assert again.to_text() == report.to_text()
    assert "uncommitted changes" in again.to_text()
