"""E05/T4: threshold placeholders and changed files for mutation (E05 AC-12 to AC-15).

Commands echo their arguments (ARGS=a|b|c) so each test can see exactly what the gate passed.
Expectations come from the E05 spec, not from the implementation.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests._gate import (
    PASS,
    checks_of,
    gate_repo,
    git,
    profile,
    run_gate_json,
)

MARKER = {"pyproject.toml": "[project]\nname = 'x'\n"}
ECHO = [sys.executable, "-c", "import sys; print('ARGS=' + '|'.join(sys.argv[1:]))"]


def _check(report: dict[str, object], name: str) -> dict[str, object]:
    return next(c for c in checks_of(report) if c["check"] == name)


def _args(report: dict[str, object], name: str) -> list[str]:
    tail = str(_check(report, name)["output_tail"])
    line = next(line for line in tail.splitlines() if line.startswith("ARGS="))
    rest = line.removeprefix("ARGS=")
    return rest.split("|") if rest else []


def _repo(
    tmp_path: Path,
    checks: dict[str, list[str]],
    *,
    config: str | None = None,
    files: dict[str, str] | None = None,
    mutation_paths: tuple[str, ...] = ("*.py",),
) -> Path:
    return gate_repo(
        tmp_path / "repo",
        {"py.toml": profile("py", ["pyproject.toml"], checks, mutation_paths=mutation_paths)},
        config=config,
        files={**MARKER, **(files or {})},
    )


# --- AC-12: threshold placeholders ------------------------------------------------------------


@pytest.mark.ac("E05-AC-12")
def test_threshold_placeholders_default_to_80_and_60(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(
        tmp_path,
        {"coverage": [*ECHO, "--fail-under={coverage_percent}", "min={mutation_percent}%"]},
    )
    code, report = run_gate_json(repo, monkeypatch, capsys)
    assert code == 0
    assert _args(report, "coverage") == ["--fail-under=80", "min=60%"]


@pytest.mark.ac("E05-AC-12")
def test_threshold_placeholders_follow_the_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(
        tmp_path,
        {"coverage": [*ECHO, "{coverage_percent}", "{mutation_percent}"]},
        config="[gates]\ncoverage_threshold = 0.9\nmutation_threshold = 0.55\n",
    )
    _, report = run_gate_json(repo, monkeypatch, capsys)
    assert _args(report, "coverage") == ["90", "55"]


# --- AC-13: changed files ---------------------------------------------------------------------


def _feature_branch_repo(tmp_path: Path, mutation: list[str]) -> Path:
    repo = _repo(
        tmp_path,
        {"mutation": mutation},
        files={
            "c.py": "c = 1\n",
            "e.py": "e = 1\n",
            "keep.py": "k = 1\n",
            ".gitignore": "ran-*.txt\nignored.py\n",
        },
    )
    git(repo, "checkout", "-q", "-b", "feature")
    (repo / "a.py").write_text("a = 1\n", encoding="utf-8")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "f.py").write_text("f = 1\n", encoding="utf-8")
    (repo / "e.py").unlink()
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "feature work")
    (repo / "b.py").write_text("b = 1\n", encoding="utf-8")
    git(repo, "add", "b.py")
    (repo / "c.py").write_text("c = 2\n", encoding="utf-8")
    (repo / "d.py").write_text("d = 1\n", encoding="utf-8")
    (repo / "notes.md").write_text("notes\n", encoding="utf-8")
    (repo / "ignored.py").write_text("i = 1\n", encoding="utf-8")
    return repo


@pytest.mark.ac("E05-AC-13")
def test_changed_files_are_committed_staged_unstaged_and_untracked_minus_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _feature_branch_repo(tmp_path, [*ECHO, "{changed_files}"])
    code, report = run_gate_json(repo, monkeypatch, capsys)
    assert code == 0
    assert _args(report, "mutation") == ["a.py", "b.py", "c.py", "d.py", "pkg/f.py"]


@pytest.mark.ac("E05-AC-13")
def test_report_lists_the_changed_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _feature_branch_repo(tmp_path, [*ECHO, "{changed_files}"])
    _, report = run_gate_json(repo, monkeypatch, capsys)
    changed = report["changed_files"]
    assert isinstance(changed, list)
    assert {"a.py", "b.py", "c.py", "d.py", "pkg/f.py"} <= set(changed)
    assert "e.py" not in changed
    assert "ignored.py" not in changed
    assert "keep.py" not in changed


@pytest.mark.ac("E05-AC-13")
def test_a_path_with_spaces_stays_one_argument(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, {"mutation": [*ECHO, "{changed_files}"]})
    (repo / "my module.py").write_text("x = 1\n", encoding="utf-8")
    _, report = run_gate_json(repo, monkeypatch, capsys)
    assert _args(report, "mutation") == ["my module.py"]


@pytest.mark.ac("E05-AC-13")
def test_scope_all_expands_to_every_tracked_matching_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(
        tmp_path,
        {"mutation": [*ECHO, "{changed_files}"]},
        config='[gates]\nmutation_scope = "all"\n',
        files={"x.py": "x = 1\n", "y/z.py": "z = 1\n", "readme.md": "hi\n"},
    )
    (repo / "untracked.py").write_text("u = 1\n", encoding="utf-8")
    _, report = run_gate_json(repo, monkeypatch, capsys)
    assert _args(report, "mutation") == ["x.py", "y/z.py"]


@pytest.mark.ac("E05-AC-13")
def test_mutation_paths_globs_filter_the_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(
        tmp_path,
        {"mutation": [*ECHO, "{changed_files}"]},
        mutation_paths=("src/*.py",),
    )
    (repo / "src").mkdir()
    (repo / "src" / "core.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "tool.py").write_text("t = 1\n", encoding="utf-8")
    _, report = run_gate_json(repo, monkeypatch, capsys)
    assert _args(report, "mutation") == ["src/core.py"]


# --- AC-14: nothing to mutate -----------------------------------------------------------------


@pytest.mark.ac("E05-AC-14")
def test_no_changed_files_skips_mutation_without_running_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    marker = [sys.executable, "-c", "open('ran-mut.txt', 'w').close()", "{changed_files}"]
    repo = _repo(tmp_path, {"tests": PASS, "mutation": marker})
    code, report = run_gate_json(repo, monkeypatch, capsys)
    assert code == 0
    assert report["verdict"] == "pass"
    mutation = _check(report, "mutation")
    assert mutation["status"] == "skipped"
    assert "no changed files" in str(mutation["reason"])
    assert not (repo / "ran-mut.txt").exists()


@pytest.mark.ac("E05-AC-14")
def test_changed_files_that_match_no_glob_also_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, {"mutation": [*ECHO, "{changed_files}"]})
    (repo / "notes.md").write_text("only docs changed\n", encoding="utf-8")
    code, report = run_gate_json(repo, monkeypatch, capsys)
    assert code == 0
    assert _check(report, "mutation")["status"] == "skipped"


# --- AC-15: missing base ref ------------------------------------------------------------------


@pytest.mark.ac("E05-AC-15")
def test_missing_base_ref_fails_only_checks_that_need_changed_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(
        tmp_path,
        {"tests": PASS, "mutation": [*ECHO, "{changed_files}"]},
        config='[gates]\nbase_ref = "release-9"\n',
    )
    (repo / "new.py").write_text("n = 1\n", encoding="utf-8")
    code, report = run_gate_json(repo, monkeypatch, capsys)
    assert code == 1
    mutation = _check(report, "mutation")
    assert mutation["status"] == "fail"
    assert "release-9" in str(mutation["reason"])
    assert _check(report, "tests")["status"] == "pass"


@pytest.mark.ac("E05-AC-15")
def test_missing_base_ref_does_not_matter_without_changed_files_placeholder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(
        tmp_path,
        {"tests": PASS, "coverage": [*ECHO, "{coverage_percent}"]},
        config='[gates]\nbase_ref = "release-9"\n',
    )
    code, report = run_gate_json(repo, monkeypatch, capsys)
    assert code == 0
    assert report["base_ref"] == "release-9"
