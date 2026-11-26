"""E13/T8: the Debugger stops for a human, and a relock is a recorded human decision.

Covers E13 AC-12 (amended 26 Nov 2026) and AC-23. Expectations come from the E13 spec's
Changes entry of 26 Nov 2026, the design note's Changes and ADR 0047, not from the code:

- After a Debugger session in the gate stage, a new open blocker finding in the task file stops
  the job as `needs-human`, lists the findings, and spends no more gate retries. The driver
  commits the finding if the Debugger left it uncommitted.
- `pipeline.py approve <job> relock --task <id> --by NAME [--files f...]` is accepted only while
  the job is `needs-human`. It records the decision and its files, and sets the job `ready`.
  `--files` defaults to the files whose hashes no longer match, on the slice branch.
- The next `run` sends `agents.py lock --replace <task> <every file in the record, plus the
  approved ones> --approved-by NAME` on the slice's runner job, after checking that only the
  approved files' hashes changed. It commits `test(<task>): relock approved by NAME`, marks the
  Debugger's blocker findings fixed, and reruns the stopped stage.
"""

from __future__ import annotations

import hashlib
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from tests._pipeline import JOB, LOCK_REL, TASK, TASK_REL, TEST_REL, TESTS, git
from tests._pipeline_driver import call, calls, e18, read
from tests._pipeline_slices import (
    AGENTS_PY,
    DEBUG_FIX,
    RED,
    commit,
    finding,
    gate_calls,
    one_task_plan,
    slice_config,
    slice_turns,
    start,
    task_entry,
    to_slices,
    turns,
)

BRANCH = f"factory/{JOB}-t1-1"
MORE_REL = "tests/test_widgets_more.py"
MORE = """import pytest


@pytest.mark.ac("E31-AC-01")
def test_widgets_do_more() -> None:
    assert False
"""
ASK = "Relock E31-T1: test_widgets_do_one expects the old widget size"


def roles(log: Path) -> list[str]:
    return [c["role"] for c in calls(log)]


def lf_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8").replace(b"\r\n", b"\n")).hexdigest()


def toml_at(root: Path, ref: str, rel: str) -> dict[str, Any]:
    front = git(root, "show", f"{ref}:{rel}")
    if rel.endswith(".md"):
        front = front.split("+++")[1]
    return tomllib.loads(front)


def hashes(lock: Mapping[str, Any]) -> dict[str, str]:
    return {str(f["path"]): str(f["sha256"]) for f in lock["files"]}


def stopped_by_the_debugger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    tests: Mapping[str, str] | None = None,
    debugger_commits: bool = False,
) -> tuple[Path, Path]:
    """A slice whose gate is red, and whose Debugger records a blocker: the job stops."""
    debugger = [finding(TASK, "blocker", ASK)]
    if debugger_commits:
        debugger.append(commit(f"chore({TASK}): needs a relock"))
    script = turns(one_task_plan(), slice_turns(red=True, tests=tests), {"debugger": [debugger]})
    root, _, log = start(tmp_path, monkeypatch, capsys, script)
    assert to_slices(root, monkeypatch, capsys) == 1
    return root, log


def po_commits(root: Path, tmp_path: Path, changes: Mapping[str, str | None]) -> str:
    """The product owner changes files on the slice branch, as the PO's decision allows."""
    where = tmp_path / "po-worktree"
    git(root, "worktree", "add", "-q", str(where), BRANCH)
    for rel, text in changes.items():
        if text is None:
            git(where, "rm", "-q", rel)
        else:
            (where / rel).write_text(text, encoding="utf-8", newline="\n")
    git(where, "add", "-A")
    git(where, "commit", "-q", "-m", f"test({TASK}): fix the expected size")
    git(root, "worktree", "remove", str(where))
    return git(root, "rev-parse", BRANCH).strip()


def approve(
    root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *more: str
) -> tuple[int, str, str]:
    return call(root, monkeypatch, capsys, "approve", JOB, "relock", *more)


def relock_sessions(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [s for s in record["sessions"] if s["role"] == "relock"]


# --- AC-12 (amended): the Debugger stops for a human ----------------------------------------


@pytest.mark.ac("E13-AC-12")
def test_a_debugger_blocker_finding_stops_the_job_and_spends_no_more_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, log = stopped_by_the_debugger(tmp_path, monkeypatch, capsys)
    record = read(root)
    assert (record["status"], record["stage"]) == ("needs-human", "gate")
    assert "F1" in record["reason"] and ASK in record["reason"]
    assert "debugger" in record["reason"]
    assert roles(log).count("debugger") == 1
    assert len(gate_calls(tmp_path)) == 1
    assert "verifier" not in roles(log)
    assert e18(root)["status"] == "blocked"


@pytest.mark.ac("E13-AC-12")
def test_the_driver_commits_a_blocker_finding_the_debugger_left_uncommitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _ = stopped_by_the_debugger(tmp_path, monkeypatch, capsys)
    data = toml_at(root, BRANCH, TASK_REL)
    assert [(f["id"], f["severity"], f["status"]) for f in data["findings"]] == [
        ("F1", "blocker", "open")
    ]
    debugger = [s for s in read(root)["sessions"] if s["role"] == "debugger"]
    assert debugger[-1]["blockers"] == ["F1"]


@pytest.mark.ac("E13-AC-12")
def test_a_blocker_the_debugger_committed_itself_stops_the_job_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, log = stopped_by_the_debugger(tmp_path, monkeypatch, capsys, debugger_commits=True)
    record = read(root)
    assert (record["status"], record["stage"]) == ("needs-human", "gate")
    assert "F1" in record["reason"]
    assert roles(log).count("debugger") == 1
    assert git(root, "log", "-1", "--format=%s", BRANCH).strip() == f"chore({TASK}): needs a relock"


@pytest.mark.ac("E13-AC-12")
def test_a_minor_finding_from_the_debugger_does_not_stop_the_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    debugger = [finding(TASK, "minor", "The widget size is a magic number"), *DEBUG_FIX]
    script = turns(one_task_plan(), slice_turns(red=True), {"debugger": [debugger]})
    root, _, log = start(tmp_path, monkeypatch, capsys, script)
    assert to_slices(root, monkeypatch, capsys) == 0
    assert read(root)["status"] == "awaiting-merge"
    assert "verifier" in roles(log)


# --- AC-23: approving a relock --------------------------------------------------------------


@pytest.mark.ac("E13-AC-23")
def test_an_approved_relock_is_carried_out_by_the_driver_and_the_stage_reruns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _ = stopped_by_the_debugger(tmp_path, monkeypatch, capsys)
    fixed = TESTS.replace("assert False", "assert True")
    po_commits(root, tmp_path, {TEST_REL: fixed, RED: None})
    code, out, err = approve(root, monkeypatch, capsys, "--task", TASK, "--by", "po")
    assert code == 0, err
    assert "relock" in out
    record = read(root)
    assert (record["status"], record["reason"]) == ("ready", "")
    decision = record["decisions"][-1]
    assert (decision["checkpoint"], decision["verdict"], decision["by"]) == (
        "relock",
        "approve",
        "po",
    )
    assert decision["files"] == [TEST_REL]
    assert decision["lock_task"] == TASK

    assert call(root, monkeypatch, capsys, "run", JOB)[0] == 0
    record = read(root)
    assert record["status"] == "awaiting-merge"
    [relock] = relock_sessions(record)
    lock = [sys.executable, str(AGENTS_PY), "lock", "--replace", TASK, TEST_REL]
    assert relock["argv"] == [*lock, "--approved-by", "po"]
    assert relock["run"] == f"{JOB}-t1-2"
    head = str(task_entry(root)["head"])
    subjects = git(root, "log", "--format=%s", head).splitlines()
    assert f"test({TASK}): relock approved by po" in subjects
    locked = toml_at(root, head, LOCK_REL)
    assert locked["approved_by"] == "po"
    assert hashes(locked) == {TEST_REL: lf_sha256(fixed)}
    findings = toml_at(root, head, TASK_REL)["findings"]
    assert [(f["id"], f["status"]) for f in findings] == [("F1", "fixed")]
    gates = [g["verdict"] for g in record["gates"]]
    assert gates[:2] == ["fail", "pass"]


@pytest.mark.ac("E13-AC-23")
def test_the_relock_lists_every_locked_file_and_only_the_approved_hash_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tests = {TEST_REL: TESTS, MORE_REL: MORE}
    root, _ = stopped_by_the_debugger(tmp_path, monkeypatch, capsys, tests=tests)
    before = hashes(toml_at(root, BRANCH, LOCK_REL))
    fixed = MORE.replace("assert False", "assert True")
    po_commits(root, tmp_path, {MORE_REL: fixed, RED: None})
    code, _, err = approve(root, monkeypatch, capsys, "--task", TASK, "--by", "po")
    assert code == 0, err
    assert read(root)["decisions"][-1]["files"] == [MORE_REL]
    assert call(root, monkeypatch, capsys, "run", JOB)[0] == 0
    [relock] = relock_sessions(read(root))
    argv = relock["argv"]
    assert argv[argv.index("--replace") + 1 :] == [TASK, TEST_REL, MORE_REL, "--approved-by", "po"]
    after = hashes(toml_at(root, str(task_entry(root)["head"]), LOCK_REL))
    assert after[TEST_REL] == before[TEST_REL]
    assert after[MORE_REL] == lf_sha256(fixed) != before[MORE_REL]


@pytest.mark.ac("E13-AC-23")
def test_files_names_the_approved_files_and_a_new_file_joins_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _ = stopped_by_the_debugger(tmp_path, monkeypatch, capsys)
    po_commits(root, tmp_path, {MORE_REL: MORE, RED: None})
    args = ("--task", TASK, "--by", "po", "--files", MORE_REL)
    code, _, err = approve(root, monkeypatch, capsys, *args)
    assert code == 0, err
    assert read(root)["decisions"][-1]["files"] == [MORE_REL]
    assert call(root, monkeypatch, capsys, "run", JOB)[0] == 0
    [relock] = relock_sessions(read(root))
    assert relock["argv"][-4:] == [TEST_REL, MORE_REL, "--approved-by", "po"]
    locked = toml_at(root, str(task_entry(root)["head"]), LOCK_REL)
    assert set(hashes(locked)) == {TEST_REL, MORE_REL}


@pytest.mark.ac("E13-AC-23")
def test_a_changed_file_that_is_not_approved_is_refused_at_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tests = {TEST_REL: TESTS, MORE_REL: MORE}
    root, _ = stopped_by_the_debugger(tmp_path, monkeypatch, capsys, tests=tests)
    changes = {TEST_REL: TESTS + "\n", MORE_REL: MORE + "\n", RED: None}
    po_commits(root, tmp_path, changes)
    args = ("--task", TASK, "--by", "po", "--files", TEST_REL)
    code, _, err = approve(root, monkeypatch, capsys, *args)
    assert code == 1
    assert MORE_REL in err
    record = read(root)
    assert record["status"] == "needs-human"
    assert record["decisions"][-1]["checkpoint"] != "relock"


@pytest.mark.ac("E13-AC-23")
def test_the_driver_stops_when_a_file_that_is_not_approved_changed_after_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tests = {TEST_REL: TESTS, MORE_REL: MORE}
    root, _ = stopped_by_the_debugger(tmp_path, monkeypatch, capsys, tests=tests)
    po_commits(root, tmp_path, {TEST_REL: TESTS + "\n", RED: None})
    assert approve(root, monkeypatch, capsys, "--task", TASK, "--by", "po")[0] == 0
    po_commits(root, tmp_path, {MORE_REL: MORE + "\n"})
    assert call(root, monkeypatch, capsys, "run", JOB)[0] == 1
    record = read(root)
    assert (record["status"], record["stage"]) == ("needs-human", "gate")
    assert "relock" in record["reason"] and MORE_REL in record["reason"]
    assert relock_sessions(record) == []
    assert (
        git(root, "log", "-1", "--format=%s", BRANCH).strip()
        == f"test({TASK}): fix the expected size"
    )


@pytest.mark.ac("E13-AC-23")
def test_relock_approval_is_refused_unless_the_job_needs_a_human(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = turns(one_task_plan(), slice_turns())
    root, _, _ = start(tmp_path, monkeypatch, capsys, script)
    assert call(root, monkeypatch, capsys, "run", JOB)[0] == 0
    assert read(root)["status"] == "awaiting-approval"
    code, _, err = approve(root, monkeypatch, capsys, "--task", TASK, "--by", "po")
    assert code == 1
    assert "needs-human" in err or "human" in err
    assert read(root)["status"] == "awaiting-approval"


@pytest.mark.ac("E13-AC-23")
def test_relock_approval_with_nothing_changed_and_no_files_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _ = stopped_by_the_debugger(tmp_path, monkeypatch, capsys)
    code, _, err = approve(root, monkeypatch, capsys, "--task", TASK, "--by", "po")
    assert code == 1
    assert "nothing to relock" in err
    assert read(root)["status"] == "needs-human"


@pytest.mark.ac("E13-AC-23")
@pytest.mark.parametrize(
    ("more", "code", "words"),
    [
        (("--by", "po"), 2, "--task"),
        (("--task", "E31-T9", "--by", "po"), 1, "E31-T9"),
        (("--task", TASK, "--by", "po", "--files", "tests/no_such_test.py"), 1, "no_such_test"),
    ],
)
def test_relock_approval_needs_a_task_with_a_lock_and_files_on_the_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    more: tuple[str, ...],
    code: int,
    words: str,
) -> None:
    root, _ = stopped_by_the_debugger(tmp_path, monkeypatch, capsys)
    got, _, err = approve(root, monkeypatch, capsys, *more)
    assert got == code
    assert words in err
    assert read(root)["status"] == "needs-human"


@pytest.mark.ac("E13-AC-23")
def test_only_approve_knows_the_relock_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _ = stopped_by_the_debugger(tmp_path, monkeypatch, capsys)
    args = ("reject", JOB, "relock", "--by", "po", "--note", "no")
    code, _, _ = call(root, monkeypatch, capsys, *args)
    assert code == 2
    assert read(root)["status"] == "needs-human"


@pytest.mark.ac("E13-AC-23")
def test_a_relock_with_gate_retries_left_reruns_the_gate_with_fresh_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = slice_config(gate_retries=1)
    script = turns(
        one_task_plan(), slice_turns(red=True), {"debugger": [[finding(TASK, "blocker", ASK)]]}
    )
    root, _, log = start(tmp_path, monkeypatch, capsys, script, config)
    assert to_slices(root, monkeypatch, capsys) == 1
    po_commits(root, tmp_path, {TEST_REL: TESTS + "\n"})
    assert approve(root, monkeypatch, capsys, "--task", TASK, "--by", "po")[0] == 0
    assert call(root, monkeypatch, capsys, "run", JOB)[0] == 1
    record = read(root)
    assert relock_sessions(record)[0]["exit_code"] == 0
    assert record["attempt"] == 2
    assert roles(log).count("debugger") == 2
    assert [g["verdict"] for g in record["gates"]] == ["fail", "fail"]
