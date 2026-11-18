"""T3: fresh install end to end (AC-01 to AC-06, AC-08, AC-09, AC-11, AC-19 to AC-21).

Expectations come from the E01 spec and ADRs 0002-0005, not from the implementation.
Report contract defined here for later slices:
- text summary line: "<n> created, <n> skipped, <n> overwritten, <n> updated, <n> kept, <n> removed"
- --json: {"kit_version", "target", "dry_run", "counts": {...}, "files": {action: [paths]},
  "pending_merge": [paths]}; the manifest itself is bookkeeping and not listed in the report.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import install
from factory_installer import cli
from tests._ac import REPO_ROOT
from tests._repo import (
    INSTALLED_FILES,
    KIT_FILES,
    KIT_VERSION,
    MANIFEST,
    STATE_FILES,
    files_under,
    git_repo,
    normalised_hash,
    run_install_py,
    snapshot,
)

COUNT_LABELS = ("created", "skipped", "overwritten", "updated", "kept", "removed")


def _install(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str]:
    code = cli.main(list(args))
    out = capsys.readouterr()
    return code, out.out + out.err


def _install_json(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, object]]:
    code = cli.main([*args, "--json"])
    return code, json.loads(capsys.readouterr().out)


def _counts(output: str) -> dict[str, int]:
    found = {label: re.search(rf"(\d+) {label}\b", output) for label in COUNT_LABELS}
    missing = [label for label, match in found.items() if match is None]
    assert not missing, f"summary lacks counts for {missing}:\n{output}"
    return {label: int(match.group(1)) for label, match in found.items() if match}


# --- AC-01: the command -----------------------------------------------------------------------


@pytest.mark.ac("AC-01")
def test_install_into_given_path_exits_0(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path / "repo")
    code, _ = _install(capsys, str(repo))
    assert code == 0
    assert (repo / MANIFEST).is_file()


@pytest.mark.ac("AC-01")
def test_install_defaults_to_current_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = git_repo(tmp_path / "repo")
    monkeypatch.chdir(repo)
    code, _ = _install(capsys)
    assert code == 0
    assert (repo / MANIFEST).is_file()


@pytest.mark.ac("AC-01")
def test_install_py_installs_from_the_command_line(tmp_path: Path) -> None:
    repo = git_repo(tmp_path / "repo")
    result = run_install_py(str(repo))
    assert result.returncode == 0, result.stdout + result.stderr
    assert (repo / MANIFEST).is_file()


# --- AC-02: standard library only -------------------------------------------------------------


@pytest.mark.ac("AC-02")
def test_install_runs_isolated_without_site_packages(tmp_path: Path) -> None:
    repo = git_repo(tmp_path / "repo")
    result = subprocess.run(
        [sys.executable, "-I", "-S", str(REPO_ROOT / "install.py"), str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (repo / MANIFEST).is_file()


@pytest.mark.ac("AC-02")
def test_installer_imports_only_stdlib_or_itself() -> None:
    sources = [REPO_ROOT / "install.py", *sorted((REPO_ROOT / "factory_installer").glob("*.py"))]
    foreign: list[str] = []
    for source in sources:
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for name in names:
                top = name.split(".")[0]
                if top not in sys.stdlib_module_names and top != "factory_installer":
                    foreign.append(f"{source.name}: {name}")
    assert not foreign, f"non-stdlib imports: {foreign}"


# --- AC-03: Python version gate ---------------------------------------------------------------


@pytest.mark.ac("AC-03")
def test_version_gate_accepts_3_11_and_rejects_3_10() -> None:
    assert install.version_ok((3, 11, 0))
    assert install.version_ok((3, 15, 2))
    assert not install.version_ok((3, 10, 14))
    assert not install.version_ok((2, 7, 18))


@pytest.mark.ac("AC-03")
def test_old_python_is_refused_with_a_message_and_nothing_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = git_repo(tmp_path / "repo")
    before = snapshot(repo)
    monkeypatch.setattr(sys, "version_info", (3, 10, 14, "final", 0))
    monkeypatch.setattr(sys, "argv", ["install.py", str(repo)])
    code = install.run()
    assert code != 0
    assert "3.11" in capsys.readouterr().err
    assert snapshot(repo) == before


@pytest.mark.ac("AC-03")
def test_launcher_uses_only_old_python_syntax() -> None:
    tree = ast.parse((REPO_ROOT / "install.py").read_text(encoding="utf-8"))
    modern = [
        type(node).__name__
        for node in ast.walk(tree)
        if isinstance(node, ast.JoinedStr | ast.AnnAssign | ast.Match | ast.NamedExpr)
        or (isinstance(node, ast.arg) and node.annotation is not None)
        or (isinstance(node, ast.FunctionDef) and node.returns is not None)
    ]
    assert not modern, f"install.py must parse on old Pythons; found {modern}"


# --- AC-04: git working tree required ---------------------------------------------------------


@pytest.mark.ac("AC-04")
def test_non_git_target_is_refused_and_nothing_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "README.md").write_text("hello\n", encoding="utf-8")
    before = snapshot(plain)
    code, output = _install(capsys, str(plain))
    assert code != 0
    assert "git" in output.lower()
    assert snapshot(plain) == before


@pytest.mark.ac("AC-04")
def test_subdirectory_of_a_git_repo_is_accepted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sub = git_repo(tmp_path / "repo") / "services" / "api"
    sub.mkdir(parents=True)
    code, _ = _install(capsys, str(sub))
    assert code == 0
    assert (sub / MANIFEST).is_file()


# --- AC-05: dry run ---------------------------------------------------------------------------


@pytest.mark.ac("AC-05")
def test_dry_run_lists_every_file_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path / "repo")
    before = snapshot(repo)
    code, output = _install(capsys, str(repo), "--dry-run")
    assert code == 0
    assert snapshot(repo) == before
    for rel in KIT_FILES | STATE_FILES:
        assert rel in output, f"dry run does not mention {rel}"


@pytest.mark.ac("AC-05")
def test_dry_run_json_marks_dry_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = git_repo(tmp_path / "repo")
    code, report = _install_json(capsys, str(repo), "--dry-run")
    assert code == 0
    assert report["dry_run"] is True
    assert files_under(repo) == set()


# --- AC-06: fresh layout ----------------------------------------------------------------------


@pytest.mark.ac("AC-06")
def test_fresh_install_creates_exactly_the_layout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path / "repo")
    code, _ = _install(capsys, str(repo))
    assert code == 0
    assert files_under(repo) == INSTALLED_FILES


@pytest.mark.ac("AC-06")
def test_fresh_install_leaves_existing_project_files_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path / "repo")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (repo / "README.md").write_text("# app\n", encoding="utf-8")
    before = snapshot(repo)
    code, _ = _install(capsys, str(repo))
    assert code == 0
    after = snapshot(repo)
    assert {rel: after[rel] for rel in before} == before
    assert set(after) - set(before) == INSTALLED_FILES


@pytest.mark.ac("AC-07")
def test_installed_config_is_the_kit_default(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path / "repo")
    _install(capsys, str(repo))
    kit_config = (REPO_ROOT / "kit" / ".agentic" / "config.toml").read_bytes()
    assert (repo / ".agentic" / "config.toml").read_bytes() == kit_config.replace(b"\r\n", b"\n")
    assert cli.main(["check", str(repo)]) == 0


# --- AC-08: manifest --------------------------------------------------------------------------


@pytest.mark.ac("AC-08")
def test_manifest_records_kit_version_and_hash_of_every_kit_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path / "repo")
    _install(capsys, str(repo))
    manifest = json.loads((repo / MANIFEST).read_text(encoding="utf-8"))
    assert manifest["kit_version"] == KIT_VERSION
    assert set(manifest["files"]) == KIT_FILES
    for rel, digest in manifest["files"].items():
        assert digest == normalised_hash((repo / rel).read_bytes()), rel


@pytest.mark.ac("AC-08")
def test_manifest_excludes_state_files_and_itself(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path / "repo")
    _install(capsys, str(repo))
    files = json.loads((repo / MANIFEST).read_text(encoding="utf-8"))["files"]
    assert not set(files) & STATE_FILES
    assert MANIFEST not in files


# --- AC-09: existing files are never overwritten ----------------------------------------------


@pytest.mark.ac("AC-09")
def test_existing_files_are_skipped_unchanged_and_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path / "repo")
    (repo / ".agentic").mkdir()
    (repo / ".agentic" / "STATE.md").write_bytes(b"# my own state\n")
    (repo / ".factory").mkdir()
    (repo / ".factory" / ".gitignore").write_bytes(b"my-own-rule\n")
    code, report = _install_json(capsys, str(repo))
    assert code == 0
    assert (repo / ".agentic" / "STATE.md").read_bytes() == b"# my own state\n"
    assert (repo / ".factory" / ".gitignore").read_bytes() == b"my-own-rule\n"
    files = report["files"]
    assert isinstance(files, dict)
    assert set(files["skipped"]) == {".agentic/STATE.md", ".factory/.gitignore"}


@pytest.mark.ac("AC-09")
def test_skipped_kit_file_is_not_claimed_in_the_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path / "repo")
    (repo / ".factory").mkdir()
    (repo / ".factory" / ".gitignore").write_bytes(b"my-own-rule\n")
    _install(capsys, str(repo))
    files = json.loads((repo / MANIFEST).read_text(encoding="utf-8"))["files"]
    assert ".factory/.gitignore" not in files


# --- AC-11: summary counts --------------------------------------------------------------------


@pytest.mark.ac("AC-11")
def test_summary_reports_all_six_counts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = git_repo(tmp_path / "repo")
    (repo / ".agentic").mkdir()
    (repo / ".agentic" / "STATE.md").write_bytes(b"# mine\n")
    code, output = _install(capsys, str(repo))
    assert code == 0
    counts = _counts(output)
    assert counts["created"] == len(KIT_FILES | STATE_FILES) - 1
    assert counts["skipped"] == 1
    assert counts["overwritten"] == counts["updated"] == counts["kept"] == counts["removed"] == 0


# --- AC-19: never write outside the target ----------------------------------------------------


def _link_dir(link: Path, target: Path) -> None:
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        if sys.platform != "win32":
            pytest.skip("cannot create a directory symlink here")
        import _winapi

        try:
            _winapi.CreateJunction(str(target), str(link))
        except OSError:
            pytest.skip("cannot create a symlink or junction here")


@pytest.mark.ac("AC-19")
def test_path_escaping_the_target_aborts_before_any_write(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path / "repo")
    outside = tmp_path / "outside"
    outside.mkdir()
    _link_dir(repo / ".factory", outside)
    before_repo, before_outside = snapshot(repo), snapshot(outside)
    code, output = _install(capsys, str(repo))
    assert code != 0
    assert "outside" in output.lower()
    assert snapshot(outside) == before_outside
    assert snapshot(repo) == before_repo
    assert not (repo / ".agentic").exists()


# --- AC-20: UTF-8, LF -------------------------------------------------------------------------


@pytest.mark.ac("AC-20")
def test_written_files_are_utf8_with_lf_endings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path / "repo")
    _install(capsys, str(repo))
    for rel in INSTALLED_FILES:
        data = (repo / rel).read_bytes()
        assert b"\r\n" not in data, f"{rel} has CRLF line endings"
        data.decode("utf-8")


@pytest.mark.ac("AC-20")
def test_kit_ships_lf_gitattributes_in_both_directories(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path / "repo")
    _install(capsys, str(repo))
    for directory in (".factory", ".agentic"):
        lines = (repo / directory / ".gitattributes").read_text(encoding="utf-8").splitlines()
        assert "* text eol=lf" in lines, directory


@pytest.mark.ac("AC-14")
def test_kit_gitignores_factory_new_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path / "repo")
    _install(capsys, str(repo))
    lines = (repo / ".factory" / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "*.factory-new" in lines


# --- AC-21: JSON report -----------------------------------------------------------------------


@pytest.mark.ac("AC-21")
def test_json_report_matches_the_install(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path / "repo")
    code, report = _install_json(capsys, str(repo))
    assert code == 0
    assert report["kit_version"] == KIT_VERSION
    assert report["dry_run"] is False
    counts, files = report["counts"], report["files"]
    assert isinstance(counts, dict)
    assert isinstance(files, dict)
    for label in COUNT_LABELS:
        assert counts[label] == len(files.get(label, [])), label
    assert set(files["created"]) == KIT_FILES | STATE_FILES
    assert report["pending_merge"] == []
