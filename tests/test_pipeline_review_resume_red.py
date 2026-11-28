"""E13-T11: a resume after a red review gates again, once, before any session.

Covers E13 AC-13, as amended on 28 Nov 2026 by the product owner's decision on #120 (which also
covers #119). In the live run on #82 the Verifier rightly failed the slice, and the only later
change was its findings commit under `.agentic/`, so a `resume` didn't gate again and the
Verifier would have failed the same report. A red gate in review had the same gap: a human could
fix the code, but the newest report was red, so `resume` stopped at once. Now:

- on a new attempt at review, before any reviewer or gate in it, the driver runs the full gate
  again when the previous attempt at review ended red: a red gate in review, or a Verifier that
  failed, gave no verdict or didn't finish. That holds even when the head differs from the newest
  gate only under `.agentic/`, and even when the newest report is red;
- a green gate lets the Verifier and the reviewers run; a red one stops the job;
- a previous attempt that didn't end red keeps the rule for #117, so no needless gate;
- at most one gate again per attempt.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests._pipeline import JOB
from tests._pipeline_driver import call, calls, read
from tests._pipeline_slices import (
    RED,
    drive,
    gate_calls,
    one_task_plan,
    slice_turns,
    start,
    to_slices,
    turns,
)

AC = "E13-AC-13"
REVIEWERS = (
    "verifier",
    "spec-reviewer",
    "standards-reviewer",
    "security-reviewer",
    "perf-reviewer",
    "adversary",
)


def roles(log: Path) -> list[str]:
    return [c["role"] for c in calls(log)]


def reply(text: str) -> dict[str, Any]:
    """A fake-agent action that prints a session's JSON output with this `result`."""
    return {"print": json.dumps({"result": text, "total_cost_usd": 0.01})}


def red_verifier(n: int = 1) -> list[Any]:
    """A Verifier turn that commits a note under `.agentic/` and fails the slice."""
    note = {f".agentic/notes/verifier-{n}.md": "The mutation check failed.\n"}
    return [*change(note, "chore(E31-T1): verifier notes"), reply("VERDICT: fail mutation")]


def change(files: dict[str, str], message: str) -> list[Any]:
    return [{"write": files}, {"commit": message}]


def stopped_at_review(root: Path, code: int) -> dict[str, Any]:
    record = read(root)
    assert code == 1, record.get("reason")
    assert (record["status"], record["stage"]) == ("needs-human", "review")
    return record


def first_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    reviews: dict[str, Any],
) -> tuple[Path, Path, dict[str, Any]]:
    """Run a one-task job until it stops at the review stage, with these reviewers' turns."""
    script = turns(one_task_plan(), slice_turns(), reviews)
    root, _, log = start(tmp_path, monkeypatch, capsys, script)
    record = stopped_at_review(root, to_slices(root, monkeypatch, capsys))
    return root, log, record


def resume(root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> int:
    assert call(root, monkeypatch, capsys, "resume", JOB)[0] == 0
    return drive(root, monkeypatch, capsys)


def review_gates(record: dict[str, Any], attempt: int | None = None) -> list[dict[str, Any]]:
    return [
        s
        for s in record["sessions"]
        if s["stage"] == "review"
        and s["role"] == "gate"
        and (attempt is None or s.get("attempt") == attempt)
    ]


def first_session(record: dict[str, Any], attempt: int) -> dict[str, Any]:
    """The attempt's first review session that isn't one of the driver's commits."""
    return next(
        s
        for s in record["sessions"]
        if s["stage"] == "review" and s.get("attempt") == attempt and s["role"] != "commit"
    )


def branch_checkout(root: Path, record: dict[str, Any]) -> Path:
    """A checkout of the slice branch for a human: the stopped run's worktree when the runner
    kept it, otherwise a new one."""
    run = record["runs"][-1]
    worktree = Path(run["worktree"])
    if not worktree.is_dir():
        worktree = root.parent / "human"
        subprocess.run(
            ["git", "worktree", "add", "-q", str(worktree), str(run["branch"])],
            cwd=root,
            check=True,
            capture_output=True,
        )
    return worktree


def human_commit(worktree: Path, *args: str) -> None:
    who = ["-c", "user.name=human", "-c", "user.email=human@example.invalid"]
    subprocess.run(["git", *args], cwd=worktree, check=True, capture_output=True)
    subprocess.run(
        ["git", *who, "commit", "-q", "-m", "fix: the human fixes the code"],
        cwd=worktree,
        check=True,
        capture_output=True,
    )


# --- (a) a red Verifier, then resume: gate again once, then the reviews ------------------------


@pytest.mark.ac(AC)
def test_a_resume_after_a_red_verifier_gates_again_once_then_reviews(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, log, record = first_attempt(
        tmp_path, monkeypatch, capsys, {"verifier": [red_verifier(), []]}
    )
    assert "verifier" in record["reason"]
    assert len(gate_calls(tmp_path)) == 1
    stopped_at = len(calls(log))

    code = resume(root, monkeypatch, capsys)
    assert code == 0, read(root).get("reason")
    record = read(root)
    assert record["status"] == "awaiting-merge"
    assert len(review_gates(record, attempt=2)) == 1
    assert first_session(record, 2)["role"] == "gate"
    after = [r for r in roles(log)[stopped_at:] if r in REVIEWERS]
    assert after == list(REVIEWERS)
    assert [g["verdict"] for g in record["gates"]] == ["pass", "pass", "pass"]
    assert len(gate_calls(tmp_path)) == 3  # the gate stage, review's gate again, the docs stage


@pytest.mark.ac(AC)
def test_a_resume_after_a_verifier_with_no_verdict_gates_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    silent = [reply("I looked at it.")]
    root, _, record = first_attempt(tmp_path, monkeypatch, capsys, {"verifier": [silent, []]})
    assert "verdict" in record["reason"]

    code = resume(root, monkeypatch, capsys)
    assert code == 0, read(root).get("reason")
    assert len(review_gates(read(root), attempt=2)) == 1


@pytest.mark.ac(AC)
def test_a_resume_after_a_verifier_session_that_failed_gates_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _, record = first_attempt(
        tmp_path, monkeypatch, capsys, {"verifier": [[{"exit": 3}], []]}
    )
    assert "exited 3" in record["reason"]

    code = resume(root, monkeypatch, capsys)
    assert code == 0, read(root).get("reason")
    assert len(review_gates(read(root), attempt=2)) == 1


@pytest.mark.ac(AC)
def test_a_red_gate_again_after_a_red_verifier_stops_the_job_with_no_reviewer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, log, record = first_attempt(
        tmp_path, monkeypatch, capsys, {"verifier": [red_verifier(), []]}
    )
    worktree = branch_checkout(root, record)
    (worktree / RED).write_text("red\n", encoding="utf-8")
    human_commit(worktree, "add", RED)
    stopped_at = len(calls(log))

    record = stopped_at_review(root, resume(root, monkeypatch, capsys))
    assert "python tests" in record["reason"]
    assert record["gates"][-1]["verdict"] == "fail"
    assert len(review_gates(record, attempt=2)) == 1
    assert roles(log)[stopped_at:] == []
    assert "debugger" not in roles(log)


# --- (b) a red gate in review, a human fix, then resume: gate again ----------------------------


@pytest.mark.ac(AC)
def test_a_resume_after_a_red_gate_in_review_and_a_human_fix_gates_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    breaks = change({RED: "red\n"}, "test(E31-T1): breaks it")
    root, log, _ = first_attempt(tmp_path, monkeypatch, capsys, {"spec-reviewer": [breaks, []]})
    record = stopped_at_review(root, resume(root, monkeypatch, capsys))
    assert record["gates"][-1]["verdict"] == "fail"  # the gate again of #117, red
    assert len(gate_calls(tmp_path)) == 2

    worktree = branch_checkout(root, record)
    human_commit(worktree, "rm", "-q", RED)
    stopped_at = len(calls(log))

    code = resume(root, monkeypatch, capsys)
    assert code == 0, read(root).get("reason")
    record = read(root)
    assert record["status"] == "awaiting-merge"
    assert len(review_gates(record, attempt=3)) == 1
    assert first_session(record, 3)["role"] == "gate"
    assert record["gates"][2]["verdict"] == "pass"
    after = [r for r in roles(log)[stopped_at:] if r in REVIEWERS]
    assert after == list(REVIEWERS)


@pytest.mark.ac(AC)
def test_a_resume_after_a_red_gate_in_review_with_no_fix_stops_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    breaks = change({RED: "red\n"}, "test(E31-T1): breaks it")
    root, log, _ = first_attempt(tmp_path, monkeypatch, capsys, {"spec-reviewer": [breaks, []]})
    stopped_at_review(root, resume(root, monkeypatch, capsys))
    stopped_at = len(calls(log))

    record = stopped_at_review(root, resume(root, monkeypatch, capsys))
    assert "python tests" in record["reason"]
    assert len(review_gates(record, attempt=3)) == 1
    assert [g["verdict"] for g in record["gates"]] == ["pass", "fail", "fail"]
    assert roles(log)[stopped_at:] == []


# --- (c) a resume after a green review start doesn't gate again needlessly ---------------------


@pytest.mark.ac(AC)
def test_a_resume_after_a_green_review_start_does_not_gate_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    note = change({".agentic/notes/spec.md": "Looked.\n"}, "chore(E31-T1): spec notes")
    quits = [*note, {"exit": 1}]
    root, log, record = first_attempt(tmp_path, monkeypatch, capsys, {"spec-reviewer": [quits, []]})
    assert "spec-reviewer" in record["reason"]
    stopped_at = len(calls(log))

    code = resume(root, monkeypatch, capsys)
    assert code == 0, read(root).get("reason")
    record = read(root)
    assert record["status"] == "awaiting-merge"
    assert review_gates(record) == []
    assert len(gate_calls(tmp_path)) == 2  # the gate stage and the docs stage only
    assert roles(log)[stopped_at] == "verifier"


@pytest.mark.ac(AC)
def test_only_the_previous_attempt_at_review_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Attempt 1's red Verifier gates attempt 2 again; attempt 2 starts green, so attempt 3
    doesn't gate again."""
    quits = [{"exit": 1}]
    reviews = {"verifier": [red_verifier(), []], "spec-reviewer": [quits, []]}
    root, _, _ = first_attempt(tmp_path, monkeypatch, capsys, reviews)
    record = stopped_at_review(root, resume(root, monkeypatch, capsys))
    assert "spec-reviewer" in record["reason"]
    assert len(review_gates(record, attempt=2)) == 1

    code = resume(root, monkeypatch, capsys)
    assert code == 0, read(root).get("reason")
    record = read(root)
    assert record["status"] == "awaiting-merge"
    assert [s["attempt"] for s in review_gates(record)] == [2]


# --- (d) at most one gate again per attempt ------------------------------------------------------


@pytest.mark.ac(AC)
def test_a_red_verifier_after_the_gate_again_stops_with_no_second_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    reviews = {"verifier": [red_verifier(1), red_verifier(2), []]}
    root, log, _ = first_attempt(tmp_path, monkeypatch, capsys, reviews)
    stopped_at = len(calls(log))

    record = stopped_at_review(root, resume(root, monkeypatch, capsys))
    assert "verifier" in record["reason"]
    assert len(review_gates(record, attempt=2)) == 1
    assert len(gate_calls(tmp_path)) == 2  # the gate stage and one gate again, no more
    assert roles(log)[stopped_at:] == ["verifier"]

    code = resume(root, monkeypatch, capsys)
    assert code == 0, read(root).get("reason")
    record = read(root)
    assert [s["attempt"] for s in review_gates(record)] == [2, 3]
