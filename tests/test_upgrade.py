"""T5: re-runs and upgrades (AC-12 to AC-17), following ADR 0005 and ADR 0006.

Each test installs kit v1 from a throwaway copy of the real kit, changes the repo and/or builds
kit v2, then installs again with the hidden --kit option. Expectations come from the spec and ADRs.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from factory_installer import cli
from tests._kits import make_kit
from tests._repo import (
    KIT_FILES,
    MANIFEST,
    STATE_FILES,
    git_repo,
    normalised_hash,
    snapshot,
)

AGENTS = ".factory/agents/.gitkeep"
SKILLS = ".factory/skills/.gitkeep"
GATES = ".factory/gates/.gitkeep"
ADAPTERS = ".factory/adapters/.gitkeep"
STANDARDS = ".factory/standards/.gitkeep"
NEW_KIT_FILE = ".factory/workflow/pipeline.md"
CONFIG = ".agentic/config.toml"
STATE = ".agentic/STATE.md"
NEW_STATE_FILE = ".agentic/NOTES.md"
SIX = ("created", "skipped", "overwritten", "updated", "kept", "removed")


def _install(
    repo: Path, kit: Path, capsys: pytest.CaptureFixture[str], *extra: str
) -> dict[str, object]:
    code = cli.main([str(repo), "--kit", str(kit), "--json", *extra])
    out = capsys.readouterr().out
    assert code == 0, out
    report = json.loads(out)
    assert isinstance(report, dict)
    return report


def _install_text(repo: Path, kit: Path, capsys: pytest.CaptureFixture[str]) -> str:
    code = cli.main([str(repo), "--kit", str(kit)])
    out = capsys.readouterr()
    assert code == 0, out.out + out.err
    return out.out


def _files(report: dict[str, object]) -> dict[str, list[str]]:
    files = report["files"]
    assert isinstance(files, dict)
    return files


def _manifest(repo: Path) -> dict[str, object]:
    data = json.loads((repo / MANIFEST).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _manifest_files(repo: Path) -> dict[str, str]:
    files = _manifest(repo)["files"]
    assert isinstance(files, dict)
    return files


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _installed_v1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> tuple[Path, Path]:
    repo = git_repo(tmp_path / "repo")
    v1 = make_kit(tmp_path, "0.1.0")
    _install(repo, v1, capsys)
    return repo, v1


# --- AC-12: re-running the same version -------------------------------------------------------


@pytest.mark.ac("AC-12")
def test_rerun_changes_nothing_reports_up_to_date_and_git_is_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, v1 = _installed_v1(tmp_path, capsys)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "install kit")
    before = snapshot(repo)
    output = _install_text(repo, v1, capsys)
    assert "up to date" in output.lower()
    assert snapshot(repo) == before
    assert _git(repo, "status", "--porcelain", "--untracked-files=all") == ""


@pytest.mark.ac("AC-12")
def test_rerun_reports_every_file_unchanged_including_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, v1 = _installed_v1(tmp_path, capsys)
    report = _install(repo, v1, capsys)
    counts = report["counts"]
    assert isinstance(counts, dict)
    assert all(counts[label] == 0 for label in SIX), counts
    assert set(_files(report)["unchanged"]) == KIT_FILES | STATE_FILES
    assert report["pending_merge"] == []


@pytest.mark.ac("AC-12")
def test_missing_state_file_is_recreated_on_rerun(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, v1 = _installed_v1(tmp_path, capsys)
    (repo / ".agentic" / "tasks" / ".gitkeep").unlink()
    report = _install(repo, v1, capsys)
    assert _files(report)["created"] == [".agentic/tasks/.gitkeep"]
    assert (repo / ".agentic" / "tasks" / ".gitkeep").is_file()


# --- AC-13: untouched kit files are updated ---------------------------------------------------


@pytest.mark.ac("AC-13")
def test_upgrade_updates_untouched_kit_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = _installed_v1(tmp_path, capsys)
    v2 = make_kit(tmp_path, "0.2.0", {AGENTS: b"agents v2\n"})
    report = _install(repo, v2, capsys)
    assert (repo / AGENTS).read_bytes() == b"agents v2\n"
    assert _files(report)["updated"] == [AGENTS]
    assert report["kit_version"] == "0.2.0"


@pytest.mark.ac("AC-13")
def test_upgrade_creates_a_kit_file_new_in_this_version(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = _installed_v1(tmp_path, capsys)
    v2 = make_kit(tmp_path, "0.2.0", {NEW_KIT_FILE: b"# pipeline\n"})
    report = _install(repo, v2, capsys)
    assert (repo / NEW_KIT_FILE).read_bytes() == b"# pipeline\n"
    assert _files(report)["created"] == [NEW_KIT_FILE]


# --- AC-14: locally edited kit files are kept -------------------------------------------------


@pytest.mark.ac("AC-14")
def test_edited_kit_file_is_kept_and_new_version_written_beside_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = _installed_v1(tmp_path, capsys)
    (repo / SKILLS).write_bytes(b"my skills\n")
    v2 = make_kit(tmp_path, "0.2.0", {SKILLS: b"skills v2\n"})
    report = _install(repo, v2, capsys)
    assert (repo / SKILLS).read_bytes() == b"my skills\n"
    assert (repo / (SKILLS + ".factory-new")).read_bytes() == b"skills v2\n"
    assert _files(report)["kept"] == [SKILLS]
    assert report["pending_merge"] == [SKILLS + ".factory-new"]


@pytest.mark.ac("AC-14")
def test_text_report_lists_pending_merges_with_a_reminder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = _installed_v1(tmp_path, capsys)
    (repo / SKILLS).write_bytes(b"my skills\n")
    v2 = make_kit(tmp_path, "0.2.0", {SKILLS: b"skills v2\n"})
    output = _install_text(repo, v2, capsys)
    assert SKILLS + ".factory-new" in output
    assert "waiting to be merged" in output


@pytest.mark.ac("AC-14")
def test_factory_new_files_are_git_ignored(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = _installed_v1(tmp_path, capsys)
    (repo / SKILLS).write_bytes(b"my skills\n")
    v2 = make_kit(tmp_path, "0.2.0", {SKILLS: b"skills v2\n"})
    _install(repo, v2, capsys)
    status = _git(repo, "status", "--porcelain", "--untracked-files=all")
    assert ".factory-new" not in status


@pytest.mark.ac("AC-14")
def test_edited_file_the_kit_did_not_change_gets_no_factory_new(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = _installed_v1(tmp_path, capsys)
    (repo / SKILLS).write_bytes(b"my skills\n")
    v2 = make_kit(tmp_path, "0.2.0", {AGENTS: b"agents v2\n"})
    report = _install(repo, v2, capsys)
    assert _files(report)["kept"] == [SKILLS]
    assert not (repo / (SKILLS + ".factory-new")).exists()
    assert report["pending_merge"] == []


@pytest.mark.ac("AC-14")
def test_newer_upgrade_replaces_an_older_factory_new(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = _installed_v1(tmp_path, capsys)
    (repo / SKILLS).write_bytes(b"my skills\n")
    _install(repo, make_kit(tmp_path, "0.2.0", {SKILLS: b"skills v2\n"}), capsys)
    _install(repo, make_kit(tmp_path, "0.3.0", {SKILLS: b"skills v3\n"}), capsys)
    assert (repo / (SKILLS + ".factory-new")).read_bytes() == b"skills v3\n"
    assert (repo / SKILLS).read_bytes() == b"my skills\n"


@pytest.mark.ac("AC-10")
@pytest.mark.ac("AC-14")
def test_force_overwrites_an_edited_kit_file_on_upgrade(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = _installed_v1(tmp_path, capsys)
    (repo / SKILLS).write_bytes(b"my skills\n")
    v2 = make_kit(tmp_path, "0.2.0", {SKILLS: b"skills v2\n"})
    report = _install(repo, v2, capsys, "--force")
    assert (repo / SKILLS).read_bytes() == b"skills v2\n"
    assert _files(report)["overwritten"] == [SKILLS]
    assert not (repo / (SKILLS + ".factory-new")).exists()


# --- AC-15: files dropped from the kit --------------------------------------------------------


@pytest.mark.ac("AC-15")
def test_dropped_untouched_kit_file_is_removed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = _installed_v1(tmp_path, capsys)
    v2 = make_kit(tmp_path, "0.2.0", {ADAPTERS: None})
    report = _install(repo, v2, capsys)
    assert not (repo / ADAPTERS).exists()
    assert _files(report)["removed"] == [ADAPTERS]


@pytest.mark.ac("AC-15")
def test_dropped_edited_kit_file_is_kept(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = _installed_v1(tmp_path, capsys)
    (repo / GATES).write_bytes(b"my gates\n")
    v2 = make_kit(tmp_path, "0.2.0", {GATES: None})
    report = _install(repo, v2, capsys)
    assert (repo / GATES).read_bytes() == b"my gates\n"
    assert _files(report)["kept"] == [GATES]
    assert not (repo / (GATES + ".factory-new")).exists()


# --- AC-16: state files are never rewritten ---------------------------------------------------


@pytest.mark.ac("AC-16")
def test_upgrade_never_rewrites_state_but_adds_new_state_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = _installed_v1(tmp_path, capsys)
    installed_config = (repo / CONFIG).read_bytes()
    (repo / STATE).write_bytes(b"# our state\n")
    v2 = make_kit(
        tmp_path,
        "0.2.0",
        {
            CONFIG: installed_config + b"# a v2 comment\n",
            STATE: b"# STATE v2\n",
            NEW_STATE_FILE: b"# notes\n",
        },
    )
    report = _install(repo, v2, capsys)
    assert (repo / CONFIG).read_bytes() == installed_config
    assert (repo / STATE).read_bytes() == b"# our state\n"
    assert (repo / NEW_STATE_FILE).read_bytes() == b"# notes\n"
    assert _files(report)["created"] == [NEW_STATE_FILE]
    assert {CONFIG, STATE} <= set(_files(report)["unchanged"])


# --- AC-17: manifest after an upgrade ---------------------------------------------------------


@pytest.mark.ac("AC-17")
def test_manifest_after_upgrade_reflects_every_outcome(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = _installed_v1(tmp_path, capsys)
    v1_skills_hash = _manifest_files(repo)[SKILLS]
    (repo / SKILLS).write_bytes(b"my skills\n")
    (repo / STANDARDS).unlink()
    v2 = make_kit(
        tmp_path,
        "0.2.0",
        {
            AGENTS: b"agents v2\n",
            SKILLS: b"skills v2\n",
            ADAPTERS: None,
            NEW_KIT_FILE: b"# pipeline\n",
        },
    )
    _install(repo, v2, capsys)
    manifest = _manifest(repo)
    files = _manifest_files(repo)
    assert manifest["kit_version"] == "0.2.0"
    assert files[AGENTS] == normalised_hash((repo / AGENTS).read_bytes())
    assert files[NEW_KIT_FILE] == normalised_hash((repo / NEW_KIT_FILE).read_bytes())
    assert files[SKILLS] == v1_skills_hash, "a kept file keeps its old manifest hash"
    assert ADAPTERS not in files
    assert STANDARDS not in files
    assert not set(files) & STATE_FILES


@pytest.mark.ac("AC-17")
def test_kit_file_deleted_locally_stays_deleted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = _installed_v1(tmp_path, capsys)
    (repo / STANDARDS).unlink()
    v2 = make_kit(tmp_path, "0.2.0", {STANDARDS: b"standards v2\n"})
    report = _install(repo, v2, capsys)
    assert not (repo / STANDARDS).exists()
    assert _files(report)["deleted-locally"] == [STANDARDS]
    assert STANDARDS not in _manifest_files(repo)
    report = _install(repo, v2, capsys)
    assert not (repo / STANDARDS).exists()
