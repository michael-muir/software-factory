"""E03/T1: test locks, `agents.py check` for lock records, the gate's lock check, install check.

Covers E03 AC-03 and AC-04 (for lock records) and AC-09 to AC-11. Expectations come from the
E03 spec, the design note and ADRs 0016 and 0018, not from the implementation.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path

import pytest

import agents
from factory_installer import cli
from tests._ac import REPO_ROOT
from tests._gate import PASS, gate_repo, profile, run_gate, touches

KIT = REPO_ROOT / "kit" / ".factory"
KIT_STATE = KIT / "state" / "state.py"
KIT_AGENTS = KIT / "agents" / "agents.py"

STATE_REL = ".agentic/STATE.md"
LOCKS_REL = ".agentic/locks"
TEST_REL = "tests/test_widget.py"
OTHER_REL = "tests/test_gadget.py"
TEST_TEXT = "def test_widget() -> None:\n    assert True\n"
OTHER_TEXT = "def test_gadget() -> None:\n    assert True\n"

VALID_STATE = """+++
phase = "test"
track = "full"
active_task = ""
blockers = []
updated = 2026-11-18T21:30:00Z
+++
"""


def task_text(task_id: str) -> str:
    return f"""+++
id = "{task_id}"
title = "A slice"
status = "in-progress"
review_round = 0
created = 2026-11-18T21:30:00Z
updated = 2026-11-18T21:30:00Z
+++

## Goal

## Acceptance criteria

## Notes
"""


def lf_sha256(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")).hexdigest()


def write_repo(root: Path, files: Mapping[str, str | None] | None = None) -> Path:
    """A repo-like root: valid STATE.md, tasks E03-T1 and E03-T2, and two test files."""
    contents: dict[str, str | None] = {
        STATE_REL: VALID_STATE,
        ".agentic/tasks/E03-T1.md": task_text("E03-T1"),
        ".agentic/tasks/E03-T2.md": task_text("E03-T2"),
        TEST_REL: TEST_TEXT,
        OTHER_REL: OTHER_TEXT,
    }
    contents.update(files or {})
    for rel, text in contents.items():
        if text is None:
            continue
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return root


def lock_record(task: str, entries: Mapping[str, str], **extra: str) -> str:
    lines = [f'task = "{task}"', "locked = 2026-11-19T03:00:00Z"]
    lines += [f"{key} = {value}" for key, value in extra.items()]
    for path, sha in entries.items():
        lines += ["", "[[files]]", f'path = "{path}"', f'sha256 = "{sha}"']
    return "\n".join(lines) + "\n"


def run(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *args: str,
) -> tuple[int, str]:
    monkeypatch.chdir(root)
    code = agents.main(list(args))
    out = capsys.readouterr()
    return code, out.out + out.err


def problems(root: Path) -> list[str]:
    return [str(p) for p in agents.validate(root)]


def record(root: Path, task: str) -> dict[str, object]:
    with (root / LOCKS_REL / f"{task}.toml").open("rb") as f:
        return tomllib.load(f)


# --- AC-09: lock and unlock ---------------------------------------------------------------------


@pytest.mark.ac("E03-AC-09")
def test_lock_writes_a_record_with_each_files_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write_repo(tmp_path)
    code, output = run(root, monkeypatch, capsys, "lock", "E03-T1", TEST_REL, OTHER_REL)
    assert code == 0, output
    data = record(root, "E03-T1")
    assert set(data) == {"task", "locked", "files"}
    assert data["task"] == "E03-T1"
    files = data["files"]
    assert isinstance(files, list)
    assert {f["path"]: f["sha256"] for f in files} == {
        TEST_REL: lf_sha256(TEST_TEXT.encode()),
        OTHER_REL: lf_sha256(OTHER_TEXT.encode()),
    }
    assert all(set(f) == {"path", "sha256"} for f in files)


@pytest.mark.ac("E03-AC-09")
def test_lock_writes_the_locked_time_in_utc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write_repo(tmp_path)
    assert run(root, monkeypatch, capsys, "lock", "E03-T1", TEST_REL)[0] == 0
    text = (root / LOCKS_REL / "E03-T1.toml").read_text(encoding="utf-8")
    assert re.search(r"^locked = \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$", text, re.MULTILINE), text


@pytest.mark.ac("E03-AC-09")
def test_the_hash_ignores_line_endings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write_repo(tmp_path)
    (root / TEST_REL).write_bytes(TEST_TEXT.replace("\n", "\r\n").encode())
    assert run(root, monkeypatch, capsys, "lock", "E03-T1", TEST_REL)[0] == 0
    files = record(root, "E03-T1")["files"]
    assert isinstance(files, list)
    assert files[0]["sha256"] == hashlib.sha256(TEST_TEXT.encode()).hexdigest()


@pytest.mark.ac("E03-AC-09")
def test_lock_stores_repo_relative_posix_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write_repo(tmp_path)
    monkeypatch.chdir(root / "tests")
    code = agents.main(["lock", "E03-T1", "test_widget.py"])
    assert code == 0, capsys.readouterr()
    files = record(root, "E03-T1")["files"]
    assert isinstance(files, list)
    assert [f["path"] for f in files] == [TEST_REL]


@pytest.mark.ac("E03-AC-09")
def test_lock_needs_an_existing_task_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write_repo(tmp_path)
    code, output = run(root, monkeypatch, capsys, "lock", "E09-T1", TEST_REL)
    assert code == 1, output
    assert "E09-T1" in output
    assert not (root / LOCKS_REL / "E09-T1.toml").exists()


@pytest.mark.ac("E03-AC-09")
@pytest.mark.parametrize("bad", ["tests/missing.py", "tests", "../outside.py"])
def test_lock_needs_existing_files_inside_the_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], bad: str
) -> None:
    root = write_repo(tmp_path / "repo")
    (tmp_path / "outside.py").write_text("x = 1\n", encoding="utf-8")
    code, output = run(root, monkeypatch, capsys, "lock", "E03-T1", TEST_REL, bad)
    assert code == 1, output
    assert not (root / LOCKS_REL / "E03-T1.toml").exists()


@pytest.mark.ac("E03-AC-09")
def test_lock_refuses_to_replace_a_record_without_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write_repo(tmp_path)
    assert run(root, monkeypatch, capsys, "lock", "E03-T1", TEST_REL)[0] == 0
    before = (root / LOCKS_REL / "E03-T1.toml").read_bytes()
    code, output = run(root, monkeypatch, capsys, "lock", "E03-T1", OTHER_REL)
    assert code == 1, output
    assert "--replace" in output
    assert (root / LOCKS_REL / "E03-T1.toml").read_bytes() == before


@pytest.mark.ac("E03-AC-09")
def test_lock_replace_rewrites_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write_repo(tmp_path)
    assert run(root, monkeypatch, capsys, "lock", "E03-T1", TEST_REL)[0] == 0
    (root / TEST_REL).write_text(TEST_TEXT + "# fixed\n", encoding="utf-8")
    code, output = run(root, monkeypatch, capsys, "lock", "--replace", "E03-T1", TEST_REL)
    assert code == 0, output
    files = record(root, "E03-T1")["files"]
    assert isinstance(files, list)
    assert files == [{"path": TEST_REL, "sha256": lf_sha256((TEST_TEXT + "# fixed\n").encode())}]


@pytest.mark.ac("E03-AC-09")
def test_unlock_removes_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write_repo(tmp_path)
    assert run(root, monkeypatch, capsys, "lock", "E03-T1", TEST_REL)[0] == 0
    code, output = run(root, monkeypatch, capsys, "unlock", "E03-T1")
    assert code == 0, output
    assert not (root / LOCKS_REL / "E03-T1.toml").exists()


@pytest.mark.ac("E03-AC-09")
def test_unlock_without_a_record_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write_repo(tmp_path)
    code, output = run(root, monkeypatch, capsys, "unlock", "E03-T1")
    assert code == 1, output


@pytest.mark.ac("E03-AC-09")
def test_lock_writes_atomically_and_leaves_no_temp_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write_repo(tmp_path)
    assert run(root, monkeypatch, capsys, "lock", "E03-T1", TEST_REL)[0] == 0
    assert sorted(p.name for p in (root / LOCKS_REL).iterdir()) == ["E03-T1.toml"]
    assert b"\r" not in (root / LOCKS_REL / "E03-T1.toml").read_bytes()


@pytest.mark.ac("E03-AC-09")
def test_a_written_record_is_valid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write_repo(tmp_path)
    assert run(root, monkeypatch, capsys, "lock", "E03-T1", TEST_REL, OTHER_REL)[0] == 0
    assert problems(root) == []
    assert agents.verify_locks(root) == []


# --- AC-11 and AC-03: lock records are validated ------------------------------------------------


def _locked(root: Path, text: str, task: str = "E03-T1") -> Path:
    path = root / LOCKS_REL / f"{task}.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return root


GOOD_SHA = lf_sha256(TEST_TEXT.encode())


@pytest.mark.ac("E03-AC-11")
def test_a_hand_written_valid_record_has_no_problems(tmp_path: Path) -> None:
    root = _locked(write_repo(tmp_path), lock_record("E03-T1", {TEST_REL: GOOD_SHA}))
    assert problems(root) == []


@pytest.mark.ac("E03-AC-11")
@pytest.mark.parametrize(
    ("text", "where"),
    [
        (lock_record("E03-T1", {TEST_REL: GOOD_SHA}, owner='"me"'), "owner"),
        ("locked = 2026-11-19T03:00:00Z\n", "task"),
        (lock_record("E03-T1", {TEST_REL: "abc123"}), "files[0].sha256"),
        (lock_record("E03-T1", {TEST_REL: GOOD_SHA.upper()}), "files[0].sha256"),
        (lock_record("E03-T1", {"/abs/test.py": GOOD_SHA}), "files[0].path"),
        (lock_record("E03-T1", {"../test.py": GOOD_SHA}), "files[0].path"),
        (lock_record("E03-T1", {"tests\\\\test_widget.py": GOOD_SHA}), "files[0].path"),
        (lock_record("E03-T1", {}), "files"),
        ('task = "E03-T1"\nlocked = "yesterday"\n', "locked"),
        ("task = [\n", "toml"),
    ],
)
def test_invalid_records_are_reported_by_key(tmp_path: Path, text: str, where: str) -> None:
    root = _locked(write_repo(tmp_path), text)
    found = problems(root)
    assert found, text
    assert any(p.startswith(f"{LOCKS_REL}/E03-T1.toml: ") for p in found), found
    if where != "toml":
        assert any(p.startswith(f"{LOCKS_REL}/E03-T1.toml: {where}: ") for p in found), found


@pytest.mark.ac("E03-AC-11")
def test_a_record_must_name_an_existing_task(tmp_path: Path) -> None:
    root = _locked(write_repo(tmp_path), lock_record("E09-T1", {TEST_REL: GOOD_SHA}), "E09-T1")
    found = problems(root)
    assert any(p.startswith(f"{LOCKS_REL}/E09-T1.toml: task: ") for p in found), found


@pytest.mark.ac("E03-AC-11")
def test_a_records_task_must_match_its_file_name(tmp_path: Path) -> None:
    root = _locked(write_repo(tmp_path), lock_record("E03-T2", {TEST_REL: GOOD_SHA}), "E03-T1")
    found = problems(root)
    assert any(p.startswith(f"{LOCKS_REL}/E03-T1.toml: task: ") for p in found), found


@pytest.mark.ac("E03-AC-11")
def test_no_path_is_locked_by_two_tasks(tmp_path: Path) -> None:
    root = write_repo(tmp_path)
    _locked(root, lock_record("E03-T1", {TEST_REL: GOOD_SHA}), "E03-T1")
    _locked(root, lock_record("E03-T2", {TEST_REL: GOOD_SHA}), "E03-T2")
    found = problems(root)
    assert any(TEST_REL in p and "E03-T1" in p for p in found), found


@pytest.mark.ac("E03-AC-11")
def test_a_path_listed_twice_in_one_record_is_a_problem(tmp_path: Path) -> None:
    text = lock_record("E03-T1", {TEST_REL: GOOD_SHA}) + (
        f'\n[[files]]\npath = "{TEST_REL}"\nsha256 = "{GOOD_SHA}"\n'
    )
    root = _locked(write_repo(tmp_path), text)
    assert any(p.startswith(f"{LOCKS_REL}/E03-T1.toml: files[1].path: ") for p in problems(root))


@pytest.mark.ac("E03-AC-11")
def test_non_toml_files_in_the_locks_folder_are_ignored(tmp_path: Path) -> None:
    root = write_repo(tmp_path)
    (root / LOCKS_REL).mkdir(parents=True)
    (root / LOCKS_REL / ".gitkeep").write_text("", encoding="utf-8")
    assert problems(root) == []


@pytest.mark.ac("E03-AC-03")
def test_check_exits_0_with_valid_locks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _locked(write_repo(tmp_path), lock_record("E03-T1", {TEST_REL: GOOD_SHA}))
    code, output = run(root, monkeypatch, capsys, "check")
    assert code == 0, output


@pytest.mark.ac("E03-AC-03")
def test_check_prints_one_line_per_problem_and_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _locked(write_repo(tmp_path), lock_record("E03-T1", {TEST_REL: "nope"}, owner='"me"'))
    code, output = run(root, monkeypatch, capsys, "check")
    assert code == 1, output
    lines = [line for line in output.splitlines() if line.startswith(f"{LOCKS_REL}/")]
    assert len(lines) == 2, output
    assert all(re.fullmatch(r"[^:]+: [^:]+: .+", line) for line in lines), lines


@pytest.mark.ac("E03-AC-03")
def test_check_takes_a_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _locked(write_repo(tmp_path / "repo"), lock_record("E03-T1", {TEST_REL: "nope"}))
    monkeypatch.chdir(tmp_path)
    assert agents.main(["--root", str(root), "check"]) == 1
    assert f"{LOCKS_REL}/E03-T1.toml" in capsys.readouterr().out


@pytest.mark.ac("E03-AC-03")
def test_check_does_not_compare_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A changed locked file is a gate failure (exit 1 there), not an invalid record."""
    root = _locked(write_repo(tmp_path), lock_record("E03-T1", {TEST_REL: GOOD_SHA}))
    (root / TEST_REL).write_text(TEST_TEXT + "# changed\n", encoding="utf-8")
    assert problems(root) == []
    assert agents.verify_locks(root) != []


# --- ADR 0016: agents.py is built on state.py ---------------------------------------------------


@pytest.mark.ac("E03-AC-03")
def test_agents_py_needs_its_sibling_state_py(tmp_path: Path) -> None:
    lonely = tmp_path / ".factory" / "agents"
    lonely.mkdir(parents=True)
    shutil.copyfile(KIT_AGENTS, lonely / "agents.py")
    result = subprocess.run(
        [sys.executable, str(lonely / "agents.py"), "check"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, result
    assert "state.py" in result.stderr


@pytest.mark.ac("E03-AC-03")
def test_agents_py_runs_as_a_script_beside_state_py(tmp_path: Path) -> None:
    root = _locked(write_repo(tmp_path), lock_record("E03-T1", {TEST_REL: GOOD_SHA}))
    for module, rel in ((KIT_STATE, "state/state.py"), (KIT_AGENTS, "agents/agents.py")):
        (root / ".factory" / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(module, root / ".factory" / rel)
    result = subprocess.run(
        [sys.executable, str(root / ".factory" / "agents" / "agents.py"), "check"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result


# --- AC-10: the gate checks locks ---------------------------------------------------------------


def _gated(
    tmp_path: Path,
    lock: Mapping[str, str] | None = None,
    *,
    kit_agents: bool = True,
) -> Path:
    repo = gate_repo(
        tmp_path / "repo",
        {
            "py.toml": profile(
                "py", ["marker.txt"], {"format": touches("ran-format.txt"), "lint": PASS}
            )
        },
        files={"marker.txt": "x\n"},
    )
    write_repo(repo)
    if lock is not None:
        _locked(repo, lock_record("E03-T1", lock))
    copies = [(KIT_STATE, "state/state.py")]
    if kit_agents:
        copies.append((KIT_AGENTS, "agents/agents.py"))
    for module, rel in copies:
        (repo / ".factory" / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(module, repo / ".factory" / rel)
    return repo


@pytest.mark.ac("E03-AC-10")
def test_the_gate_passes_with_intact_locks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _gated(tmp_path, {TEST_REL: GOOD_SHA})
    code, output = run_gate(repo, monkeypatch, capsys)
    assert code == 0, output
    assert (repo / "ran-format.txt").exists()


@pytest.mark.ac("E03-AC-10")
def test_a_changed_locked_file_fails_the_gate_and_runs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _gated(tmp_path, {TEST_REL: GOOD_SHA})
    (repo / TEST_REL).write_text(TEST_TEXT.replace("True", "False"), encoding="utf-8")
    code, output = run_gate(repo, monkeypatch, capsys)
    assert code == 1, output
    assert f"{TEST_REL}: locked by E03-T1: changed" in output
    assert not (repo / "ran-format.txt").exists()


@pytest.mark.ac("E03-AC-10")
def test_a_missing_locked_file_fails_the_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _gated(tmp_path, {TEST_REL: GOOD_SHA})
    (repo / TEST_REL).unlink()
    code, output = run_gate(repo, monkeypatch, capsys)
    assert code == 1, output
    assert f"{TEST_REL}: locked by E03-T1: missing" in output
    assert not (repo / "ran-format.txt").exists()


@pytest.mark.ac("E03-AC-10")
def test_every_broken_lock_gets_its_own_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _gated(tmp_path, {TEST_REL: GOOD_SHA, OTHER_REL: lf_sha256(OTHER_TEXT.encode())})
    (repo / TEST_REL).write_text("changed\n", encoding="utf-8")
    (repo / OTHER_REL).unlink()
    code, output = run_gate(repo, monkeypatch, capsys)
    assert code == 1, output
    assert f"{TEST_REL}: locked by E03-T1: changed" in output
    assert f"{OTHER_REL}: locked by E03-T1: missing" in output


@pytest.mark.ac("E03-AC-10")
def test_locks_are_checked_even_with_checks_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _gated(tmp_path, {TEST_REL: GOOD_SHA})
    (repo / TEST_REL).write_text("changed\n", encoding="utf-8")
    code, output = run_gate(repo, monkeypatch, capsys, "--checks", "format")
    assert code == 1, output
    assert f"{TEST_REL}: locked by E03-T1: changed" in output
    assert not (repo / "ran-format.txt").exists()


@pytest.mark.ac("E03-AC-10")
def test_line_ending_changes_do_not_break_a_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _gated(tmp_path, {TEST_REL: GOOD_SHA})
    (repo / TEST_REL).write_bytes(TEST_TEXT.replace("\n", "\r\n").encode())
    code, output = run_gate(repo, monkeypatch, capsys)
    assert code == 0, output


@pytest.mark.ac("E03-AC-04")
def test_the_gate_exits_2_on_an_invalid_lock_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _gated(tmp_path, {TEST_REL: "not-a-hash"})
    code, output = run_gate(repo, monkeypatch, capsys)
    assert code == 2, output
    assert f"{LOCKS_REL}/E03-T1.toml: files[0].sha256: " in output
    assert not (repo / "ran-format.txt").exists()


@pytest.mark.ac("E03-AC-04")
def test_the_gate_without_agents_py_skips_locks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _gated(tmp_path, {TEST_REL: GOOD_SHA}, kit_agents=False)
    (repo / TEST_REL).write_text("changed\n", encoding="utf-8")
    code, output = run_gate(repo, monkeypatch, capsys)
    assert code == 0, output


# --- AC-04: install.py check --------------------------------------------------------------------


def _with_config(root: Path) -> Path:
    shutil.copyfile(
        REPO_ROOT / "kit" / ".agentic" / "config.toml", root / ".agentic" / "config.toml"
    )
    return root


@pytest.mark.ac("E03-AC-04")
def test_install_check_passes_valid_locks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _with_config(_locked(write_repo(tmp_path), lock_record("E03-T1", {TEST_REL: GOOD_SHA})))
    assert cli.main(["check", str(root)]) == 0, capsys.readouterr()


@pytest.mark.ac("E03-AC-04")
def test_install_check_reports_lock_problems_in_the_same_format(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _with_config(_locked(write_repo(tmp_path), lock_record("E03-T1", {TEST_REL: "x"})))
    assert cli.main(["check", str(root)]) == 1
    out = capsys.readouterr()
    text = out.out + out.err
    assert f"{LOCKS_REL}/E03-T1.toml: files[0].sha256: " in text, text


@pytest.mark.ac("E03-AC-04")
def test_install_check_does_not_verify_hashes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _with_config(_locked(write_repo(tmp_path), lock_record("E03-T1", {TEST_REL: GOOD_SHA})))
    (root / TEST_REL).write_text("changed\n", encoding="utf-8")
    assert cli.main(["check", str(root)]) == 0, capsys.readouterr()
