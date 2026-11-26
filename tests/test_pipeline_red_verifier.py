"""E13/T6: a red Verifier, or a driver gate that isn't green for the head, stops the review stage.

Covers E13 AC-13 as amended on 26 Nov 2026 (issue #105). The live run on #82 found that the
driver counted the Verifier's session as done because it exited 0, though the Verifier's own gate
had gone red. The product owner's decisions: the review stage, and `check review`, need the
driver's newest gate report to be a pass, for the head or for a commit whose only later changes
are under `.agentic/` (widened the same day for #106); and the Verifier's reply ends with `VERDICT: pass` or
`VERDICT: fail <checks>`, read as the last such line of the session's JSON `result`. A fail, a
missing verdict or an unreadable result stops the job as `needs-human`, and it doesn't go back
to the gate stage.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import pipeline
from tests._pipeline import (
    REVIEWERS,
    TASK,
    TASK_REL,
    commit,
    gate_report,
    head,
    repo,
    task_text,
)
from tests._pipeline_driver import calls, read
from tests._pipeline_slices import (
    finding,
    gate_calls,
    one_task_plan,
    slice_turns,
    start,
    to_slices,
    turns,
)

AC = "E13-AC-13"
OTHERS = REVIEWERS[1:]  # the five reviewers after the Verifier


def reply(text: str) -> dict[str, Any]:
    """A fake-agent action that prints a session's JSON output with this `result`."""
    return {"print": json.dumps({"result": text, "total_cost_usd": 0.01})}


def roles(log: Path) -> list[str]:
    return [c["role"] for c in calls(log)]


def drive_with_verifier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *verifier: dict[str, Any],
) -> tuple[Path, Path, int]:
    """Run a one-task job to its end, with this turn for the Verifier."""
    script = turns(one_task_plan(), slice_turns(), {"verifier": [list(verifier)]})
    root, _, log = start(tmp_path, monkeypatch, capsys, script)
    return root, log, to_slices(root, monkeypatch, capsys)


def assert_stopped_at_review(root: Path, log: Path, code: int) -> dict[str, Any]:
    record = read(root)
    assert code == 1
    assert (record["status"], record["stage"]) == ("needs-human", "review")
    assert not any(role in roles(log) for role in OTHERS)
    assert "docs-writer" not in roles(log)
    return record


# --- the Verifier's verdict ---------------------------------------------------------------------


@pytest.mark.ac(AC)
def test_a_red_verdict_with_exit_0_stops_the_job_and_no_later_reviewer_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    text = "I ran the full gate on the head. It failed.\n\nVERDICT: fail python tests"
    root, log, code = drive_with_verifier(tmp_path, monkeypatch, capsys, reply(text))
    record = assert_stopped_at_review(root, log, code)
    assert "verifier" in record["reason"] and "python tests" in record["reason"]
    verifier = [s for s in record["sessions"] if s["role"] == "verifier"]
    assert [s["exit_code"] for s in verifier] == [0]


@pytest.mark.ac(AC)
def test_a_red_verdict_does_not_go_back_to_the_gate_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    text = "VERDICT: fail python tests"
    root, log, code = drive_with_verifier(tmp_path, monkeypatch, capsys, reply(text))
    assert_stopped_at_review(root, log, code)
    assert len(gate_calls(tmp_path)) == 1
    assert "debugger" not in roles(log)


@pytest.mark.ac(AC)
def test_the_last_verdict_line_counts_and_may_come_before_the_end_of_the_reply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    text = (
        "## Done\n\nVERDICT: pass\n\nThen the rerun went red.\nVERDICT: fail python tests\n\nBye."
    )
    root, log, code = drive_with_verifier(tmp_path, monkeypatch, capsys, reply(text))
    record = assert_stopped_at_review(root, log, code)
    assert "python tests" in record["reason"]


@pytest.mark.ac(AC)
def test_a_green_verdict_runs_the_five_reviewers_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    text = "VERDICT: fail python tests\nThe rerun was green.\nVERDICT: pass\n\n## Next\n\nReview."
    root, log, code = drive_with_verifier(tmp_path, monkeypatch, capsys, reply(text))
    assert code == 0
    assert read(root)["status"] == "awaiting-merge"
    review = [role for role in roles(log) if role in REVIEWERS]
    assert review == list(REVIEWERS)


@pytest.mark.ac(AC)
def test_the_verifier_s_prompt_asks_for_the_verdict_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, log, _ = drive_with_verifier(tmp_path, monkeypatch, capsys, reply("VERDICT: pass"))
    prompts = {c["role"]: c["prompt"] for c in calls(log)}
    assert "VERDICT: pass" in prompts["verifier"]
    assert "VERDICT: fail <checks>" in prompts["verifier"]
    assert "VERDICT:" not in prompts["spec-reviewer"]


@pytest.mark.ac(AC)
@pytest.mark.parametrize(
    "action",
    [
        reply("I ran the gate and it looks fine."),  # no verdict line
        reply("The verdict is pass."),  # not a VERDICT: line
        {"print": "VERDICT: pass"},  # not the session's JSON output
        {"print": json.dumps({"result": None, "total_cost_usd": 0.01})},  # no result text
    ],
)
def test_a_missing_or_unreadable_verdict_stops_the_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    action: dict[str, Any],
) -> None:
    root, log, code = drive_with_verifier(tmp_path, monkeypatch, capsys, action)
    record = assert_stopped_at_review(root, log, code)
    assert "verifier" in record["reason"] and "verdict" in record["reason"]


# --- the driver's own gate report ---------------------------------------------------------------


@pytest.mark.ac(AC)
def test_the_review_stage_stops_when_the_head_has_changed_since_the_green_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    change = [{"write": {"widgets_1.py": "WIDGETS = 2\n"}}, {"commit": "fix: widgets"}]
    root, log, code = drive_with_verifier(
        tmp_path, monkeypatch, capsys, *change, reply("VERDICT: pass")
    )
    record = assert_stopped_at_review(root, log, code)
    assert "gate report" in record["reason"]


@pytest.mark.ac(AC)
def test_findings_commits_to_the_task_file_keep_the_green_gate_good_for_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    note = finding(TASK, "minor", "Name the widget sizes")
    root, log, code = drive_with_verifier(
        tmp_path, monkeypatch, capsys, note, reply("VERDICT: pass")
    )
    assert code == 0
    assert read(root)["status"] == "awaiting-merge"
    assert [role for role in roles(log) if role in REVIEWERS] == list(REVIEWERS)


# --- `check review` -----------------------------------------------------------------------------


def check_review(root: Path, report: dict[str, Any] | None) -> list[pipeline.Problem]:
    checkout = pipeline.Checkout(
        root=root, epic="E31", task=TASK, reviews=REVIEWERS, gate_report=report
    )
    return pipeline.check("review", checkout)


def gated(tmp_path: Path) -> tuple[Path, str]:
    """A repo whose head has been gated, then its task file committed in review round 1."""
    root = repo(tmp_path)
    gated_at = head(root)
    commit(root, {TASK_REL: task_text(review_round=1)}, "chore: review round 1")
    return root, gated_at


@pytest.mark.ac(AC)
def test_check_review_passes_with_a_green_report_for_the_head(tmp_path: Path) -> None:
    root, _ = gated(tmp_path)
    assert check_review(root, gate_report(head(root))) == []


@pytest.mark.ac(AC)
def test_check_review_passes_when_only_the_task_file_changed_since_the_report(
    tmp_path: Path,
) -> None:
    root, gated_at = gated(tmp_path)
    assert check_review(root, gate_report(gated_at)) == []


@pytest.mark.ac(AC)
def test_check_review_passes_when_only_files_under_agentic_changed_since_the_report(
    tmp_path: Path,
) -> None:
    root, gated_at = gated(tmp_path)
    commit(root, {".agentic/handoffs/20261126T000000Z-E31-T1.md": "## Done\n"}, "chore: handoff")
    assert check_review(root, gate_report(gated_at)) == []


@pytest.mark.ac(AC)
def test_check_review_fails_with_no_gate_report(tmp_path: Path) -> None:
    root, _ = gated(tmp_path)
    problems = check_review(root, None)
    assert len(problems) == 1 and problems[0].path == "gate report"


@pytest.mark.ac(AC)
def test_check_review_fails_with_a_red_report_for_the_head(tmp_path: Path) -> None:
    root, _ = gated(tmp_path)
    problems = check_review(root, gate_report(head(root), verdict="fail"))
    assert len(problems) == 1 and problems[0].path == "gate report"


@pytest.mark.ac(AC)
def test_check_review_fails_when_other_files_changed_since_the_report(tmp_path: Path) -> None:
    root, gated_at = gated(tmp_path)
    commit(root, {"widgets.py": "WIDGETS = 2\n"}, "fix: widgets")
    problems = check_review(root, gate_report(gated_at))
    assert len(problems) == 1 and problems[0].path == "gate report"


@pytest.mark.ac(AC)
def test_check_review_fails_on_a_report_for_a_commit_not_on_the_branch(tmp_path: Path) -> None:
    root, _ = gated(tmp_path)
    problems = check_review(root, gate_report("0" * 40))
    assert len(problems) == 1 and problems[0].path == "gate report"
