"""T4: --force overwrites conflicting kit files, never state files (AC-10, ADR 0003)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from factory_installer import cli
from tests._repo import KIT_FILES, MANIFEST, STATE_FILES, git_repo, normalised_hash, snapshot

KIT_ROOT = Path(__file__).resolve().parent.parent / "kit"
CONFLICT_KIT = ".factory/.gitignore"
CONFLICT_STATE = ".agentic/STATE.md"


def _repo_with_conflicts(tmp_path: Path) -> Path:
    repo = git_repo(tmp_path / "repo")
    for rel, content in ((CONFLICT_KIT, b"my-own-rule\n"), (CONFLICT_STATE, b"# my state\n")):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_bytes(content)
    return repo


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, object]]:
    code = cli.main([*args, "--json"])
    return code, json.loads(capsys.readouterr().out)


def _files(report: dict[str, object]) -> dict[str, list[str]]:
    files = report["files"]
    assert isinstance(files, dict)
    return files


@pytest.mark.ac("AC-10")
def test_force_overwrites_a_conflicting_kit_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo_with_conflicts(tmp_path)
    code, report = _run(capsys, str(repo), "--force")
    assert code == 0
    kit_content = (KIT_ROOT / CONFLICT_KIT).read_bytes().replace(b"\r\n", b"\n")
    assert (repo / CONFLICT_KIT).read_bytes() == kit_content
    assert _files(report)["overwritten"] == [CONFLICT_KIT]


@pytest.mark.ac("AC-10")
def test_force_never_overwrites_a_state_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo_with_conflicts(tmp_path)
    code, report = _run(capsys, str(repo), "--force")
    assert code == 0
    assert (repo / CONFLICT_STATE).read_bytes() == b"# my state\n"
    assert _files(report)["skipped"] == [CONFLICT_STATE]


@pytest.mark.ac("AC-10")
def test_force_claims_the_overwritten_file_in_the_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo_with_conflicts(tmp_path)
    _run(capsys, str(repo), "--force")
    files = json.loads((repo / MANIFEST).read_text(encoding="utf-8"))["files"]
    assert set(files) == KIT_FILES
    assert files[CONFLICT_KIT] == normalised_hash((repo / CONFLICT_KIT).read_bytes())


@pytest.mark.ac("AC-10")
def test_force_counts_appear_in_the_text_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo_with_conflicts(tmp_path)
    code = cli.main([str(repo), "--force"])
    output = capsys.readouterr().out
    assert code == 0
    created = len(KIT_FILES | STATE_FILES) - 2
    assert f"{created} created, 1 skipped, 1 overwritten," in output


@pytest.mark.ac("AC-10")
def test_force_with_dry_run_reports_but_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo_with_conflicts(tmp_path)
    before = snapshot(repo)
    code, report = _run(capsys, str(repo), "--force", "--dry-run")
    assert code == 0
    assert snapshot(repo) == before
    assert _files(report)["overwritten"] == [CONFLICT_KIT]


@pytest.mark.ac("AC-10")
def test_without_force_the_kit_file_is_skipped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo_with_conflicts(tmp_path)
    code, report = _run(capsys, str(repo))
    assert code == 0
    assert (repo / CONFLICT_KIT).read_bytes() == b"my-own-rule\n"
    assert _files(report)["overwritten"] == []
    assert sorted(_files(report)["skipped"]) == sorted([CONFLICT_KIT, CONFLICT_STATE])
