"""E13/T2: the spec and design checkpoints, `approve` and `reject`, and the plumbing commit.

Covers E13 AC-11. Expectations come from the E13 spec (AC-11, "Status: **Approved by <name>,
<d Mon yyyy>** ..." and "Status: **Accepted by <name>, <d Mon yyyy>** ..."), the design note
("Forges and approvals") and ADR 0044: the status line is committed on the plan branch without a
checkout, and a branch that moved is never overwritten.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest

import docs
import pipeline
from tests._pipeline import DESIGN_REL, JOB, SPEC_REL, git
from tests._pipeline_driver import (
    PLAN,
    SPEC_REVISED,
    SPEC_TURN,
    FakeRunner,
    call,
    calls,
    driver_repo,
    jobs_module,
    new_job,
    read,
    script,
    use_runner,
)

AC = "E13-AC-11"
PLAN_BRANCH = f"factory/{JOB}-p1"


def today() -> str:
    now = dt.datetime.now(dt.UTC)
    return f"{now.day} {now:%b %Y}"


def at_spec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    turns: dict[str, Any] | None = None,
) -> tuple[Path, Path, FakeRunner]:
    root = driver_repo(tmp_path, monkeypatch)
    log = script(tmp_path, monkeypatch, PLAN if turns is None else turns)
    fake = use_runner(monkeypatch, FakeRunner(root))
    new_job(root, monkeypatch, capsys, tmp_path)
    assert call(root, monkeypatch, capsys, "run", JOB)[0] == 0
    return root, log, fake


def status_line(root: Path, branch: str, rel: str) -> str:
    text = git(root, "show", f"{branch}:{rel}")
    return next(line for line in text.splitlines() if line.startswith("Status:"))


def approve(root: Path, mp: pytest.MonkeyPatch, cap: Any, checkpoint: str) -> int:
    return call(root, mp, cap, "approve", JOB, checkpoint, "--by", "po")[0]


@pytest.mark.ac(AC)
def test_the_spec_checkpoint_waits_for_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _, _ = at_spec(tmp_path, monkeypatch, capsys)
    assert read(root)["status"] == "awaiting-approval"


@pytest.mark.ac(AC)
def test_approving_the_spec_commits_its_status_line_on_the_plan_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _, _ = at_spec(tmp_path, monkeypatch, capsys)
    before = git(root, "rev-parse", PLAN_BRANCH).strip()
    main = (git(root, "rev-parse", "main").strip(), git(root, "status", "--porcelain"))
    assert approve(root, monkeypatch, capsys, "spec") == 0
    after = git(root, "rev-parse", PLAN_BRANCH).strip()
    assert git(root, "rev-parse", f"{after}^").strip() == before
    line = status_line(root, PLAN_BRANCH, SPEC_REL)
    assert line == f"Status: **Approved by po, {today()}** · Next: design"
    text = git(root, "show", f"{PLAN_BRANCH}:{SPEC_REL}")
    assert docs.lint("spec", SPEC_REL, text) == []
    assert "approved by po" in git(root, "log", "-1", "--format=%s", PLAN_BRANCH)
    assert git(root, "diff", "--name-only", before, after).split() == [SPEC_REL]
    assert (git(root, "rev-parse", "main").strip(), git(root, "status", "--porcelain")) == main


@pytest.mark.ac(AC)
def test_approving_records_the_decision_and_moves_to_the_next_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _, _ = at_spec(tmp_path, monkeypatch, capsys)
    approve(root, monkeypatch, capsys, "spec")
    record = read(root)
    assert (record["status"], record["stage"]) == ("ready", "design")
    [decision] = record["decisions"]
    assert (decision["checkpoint"], decision["verdict"], decision["by"]) == (
        "spec",
        "approve",
        "po",
    )


@pytest.mark.ac(AC)
def test_approving_the_design_keeps_the_rest_of_its_status_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, log, _ = at_spec(tmp_path, monkeypatch, capsys)
    approve(root, monkeypatch, capsys, "spec")
    assert call(root, monkeypatch, capsys, "run", JOB)[0] == 0
    record = read(root)
    assert (record["status"], record["stage"]) == ("awaiting-approval", "design")
    assert approve(root, monkeypatch, capsys, "design") == 0
    branch = f"factory/{JOB}-p2"
    line = status_line(root, branch, DESIGN_REL)
    assert line == f"Status: **Accepted by po, {today()}** · ADRs: none yet"
    assert status_line(root, branch, SPEC_REL).startswith("Status: **Approved by po")
    record = read(root)
    assert (record["status"], record["stage"], record["task"]) == ("ready", "test", "E31-T1")
    assert [c["role"] for c in calls(log)] == ["spec-writer", "architect"]


@pytest.mark.ac(AC)
def test_rejecting_the_spec_sends_the_spec_writer_again_with_the_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    turns = {**PLAN, "spec-writer": [SPEC_TURN, SPEC_REVISED]}
    root, log, fake = at_spec(tmp_path, monkeypatch, capsys, turns)
    args = ("reject", JOB, "spec", "--by", "po", "--note", "Q1: option A.")
    assert call(root, monkeypatch, capsys, *args)[0] == 0
    record = read(root)
    assert (record["status"], record["stage"]) == ("ready", "spec")
    assert record["decisions"][-1]["verdict"] == "reject"
    assert call(root, monkeypatch, capsys, "run", JOB)[0] == 0
    second = calls(log)[1]
    assert second["role"] == "spec-writer"
    assert "The last review of this stage said: Q1: option A." in second["prompt"]
    assert "Q1: option A." not in calls(log)[0]["prompt"]
    submits = [c for c in fake.calls if c[0] == "submit"]
    assert submits[1] == ("submit", f"{JOB}-p2", PLAN_BRANCH, JOB)
    assert read(root)["status"] == "awaiting-approval"


@pytest.mark.ac(AC)
@pytest.mark.parametrize(
    "args",
    [
        ["approve", JOB, "design", "--by", "po"],  # waiting at spec, not design
        ["approve", JOB, "merge", "--by", "po"],  # a merge is never approved by command
        ["reject", JOB, "design", "--by", "po", "--note", "no"],
    ],
)
def test_a_checkpoint_the_job_is_not_waiting_at_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    args: list[str],
) -> None:
    root, _, _ = at_spec(tmp_path, monkeypatch, capsys)
    before = (read(root), git(root, "rev-parse", PLAN_BRANCH))
    assert call(root, monkeypatch, capsys, *args)[0] == 1
    assert (read(root), git(root, "rev-parse", PLAN_BRANCH)) == before


@pytest.mark.ac(AC)
def test_approving_a_job_that_is_not_waiting_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = driver_repo(tmp_path, monkeypatch)
    new_job(root, monkeypatch, capsys, tmp_path)
    assert approve(root, monkeypatch, capsys, "spec") == 1


@pytest.mark.ac(AC)
@pytest.mark.parametrize(
    "args",
    [
        ["approve", JOB, "spec"],  # no --by
        ["reject", JOB, "spec", "--by", "po"],  # no --note
        ["approve", JOB, "deploy", "--by", "po"],
        ["approve", "no-such-job", "spec", "--by", "po"],
    ],
)
def test_bad_approvals_exit_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    args: list[str],
) -> None:
    root, _, _ = at_spec(tmp_path, monkeypatch, capsys)
    assert call(root, monkeypatch, capsys, *args)[0] == 2


@pytest.mark.ac(AC)
def test_approve_is_refused_while_another_session_holds_the_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _, _ = at_spec(tmp_path, monkeypatch, capsys)
    jobs = jobs_module()
    repo = jobs.find_repo(root)
    jobs.claim(repo, jobs.load_config(repo), JOB, "someone-else")
    before = git(root, "rev-parse", PLAN_BRANCH)
    assert approve(root, monkeypatch, capsys, "spec") == 1
    assert git(root, "rev-parse", PLAN_BRANCH) == before
    assert read(root)["status"] == "awaiting-approval"


@pytest.mark.ac(AC)
def test_the_plumbing_commit_refuses_a_branch_that_moved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _, _ = at_spec(tmp_path, monkeypatch, capsys)
    head = git(root, "rev-parse", PLAN_BRANCH).strip()
    stale = git(root, "rev-parse", f"{head}^").strip()
    with pytest.raises(pipeline.Refused):
        pipeline.commit_file(root, PLAN_BRANCH, SPEC_REL, "changed\n", "a change", old=stale)
    assert git(root, "rev-parse", PLAN_BRANCH).strip() == head


@pytest.mark.ac(AC)
def test_the_plumbing_commit_changes_only_its_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _, _ = at_spec(tmp_path, monkeypatch, capsys)
    head = git(root, "rev-parse", PLAN_BRANCH).strip()
    new = pipeline.commit_file(root, PLAN_BRANCH, "notes/a.md", "hello\n", "add a note")
    assert git(root, "rev-parse", PLAN_BRANCH).strip() == new
    assert git(root, "diff", "--name-only", head, new).split() == ["notes/a.md"]
    assert git(root, "show", f"{new}:notes/a.md") == "hello\n"
    assert git(root, "show", f"{new}:{SPEC_REL}") == git(root, "show", f"{head}:{SPEC_REL}")
