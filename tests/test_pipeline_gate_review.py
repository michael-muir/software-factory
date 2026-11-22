"""E13/T3: the gate, review and docs stages of a slice, driven with a fake agent and a fake gate.

Covers E13 AC-12, AC-13 and AC-14. Expectations come from the E13 spec (those ACs, "The
stages"), the design note ("The driver": the commands the driver sends itself) and ADR 0040:
the driver runs the gate as a runner command and keeps its report; a red gate gets the Debugger
up to `gate_retries` times; each reviewer runs in its own session and the driver commits the
task file's findings; the docs stage's entry is committed and gated again on the new head.
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

import pipeline
from tests._pipeline import CHANGELOG, JOB, REVIEWERS, TASK, TASK_REL, git
from tests._pipeline_driver import calls, e18, read
from tests._pipeline_slices import (
    DEBUG_FIX,
    FAKE_GATE,
    RED,
    add_entry,
    finding,
    gate_calls,
    one_task_plan,
    run,
    slice_config,
    slice_turns,
    start,
    task_entry,
    to_slices,
    turns,
)


def roles(log: Path) -> list[str]:
    return [c["role"] for c in calls(log)]


def after(items: list[str], first: str) -> list[str]:
    return items[items.index(first) + 1 :]


def task_file_at(root: Path, commit: str) -> dict[str, Any]:
    text = git(root, "show", f"{commit}:{TASK_REL}")
    front = text.split("+++")[1]
    return tomllib.loads(front)


def subjects(root: Path, commit: str) -> list[str]:
    return git(root, "log", "--format=%s", commit).splitlines()


def commit_with(root: Path, commit: str, subject: str) -> str:
    lines = git(root, "log", "--format=%H %s", commit).splitlines()
    return next(line.split(" ", 1)[0] for line in lines if line.split(" ", 1)[1] == subject)


# --- AC-12: the gate ----------------------------------------------------------------------------


@pytest.mark.ac("E13-AC-12")
def test_the_driver_runs_the_gate_as_a_runner_command_and_keeps_its_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, fake, _ = start(tmp_path, monkeypatch, capsys, turns(one_task_plan(), slice_turns()))
    assert to_slices(root, monkeypatch, capsys) == 0
    record = read(root)
    gate = next(s for s in record["sessions"] if s["role"] == "gate")
    argv = gate["argv"]
    assert argv[:4] == [sys.executable, str(FAKE_GATE), ".factory/gates/gate.py", "--json-out"]
    out = Path(argv[4])
    assert out.parent.name == "factory-pipeline" and out.suffix == ".json"
    assert ("send", f"{JOB}-t1-1", *argv) in fake.calls
    first = record["gates"][0]
    assert (first["task"], first["verdict"]) == (TASK, "pass")
    report = json.loads(first["report"])
    assert report["verdict"] == "pass" and report["commit"] == first["commit"]
    assert subjects(root, first["commit"])[0] == f"feat({TASK}): widgets"
    assert Path(gate_calls(tmp_path)[0]["cwd"]).name == f"{JOB}-t1-1"


@pytest.mark.ac("E13-AC-12")
def test_a_red_gate_sends_the_debugger_the_report_then_runs_the_gate_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen = tmp_path / "debugger-saw.json"
    copy = "import os, shutil, sys; shutil.copy(os.environ['FACTORY_GATE_REPORT'], sys.argv[1])"
    debugger = [run(sys.executable, "-c", copy, str(seen)), *DEBUG_FIX]
    script = turns(one_task_plan(), slice_turns(red=True), {"debugger": [debugger]})
    root, _, log = start(tmp_path, monkeypatch, capsys, script)
    assert to_slices(root, monkeypatch, capsys) == 0
    assert after(roles(log), "implementer")[:2] == ["debugger", "verifier"]
    record = read(root)
    assert [g["verdict"] for g in record["gates"]] == ["fail", "pass", "pass"]
    assert json.loads(seen.read_text(encoding="utf-8"))["verdict"] == "fail"
    [session] = [c for c in calls(log) if c["role"] == "debugger"]
    assert "tests" in session["prompt"]
    assert len(gate_calls(tmp_path)) == 3
    assert record["status"] == "awaiting-merge"


@pytest.mark.ac("E13-AC-12")
def test_a_gate_still_red_after_its_retries_stops_for_a_human_with_the_failing_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = turns(one_task_plan(), slice_turns(red=True), {"debugger": [[]]})
    config = slice_config(gate_retries=1)
    root, _, log = start(tmp_path, monkeypatch, capsys, script, config)
    assert to_slices(root, monkeypatch, capsys) == 1
    record = read(root)
    assert (record["status"], record["stage"]) == ("needs-human", "gate")
    assert "gate" in record["reason"] and "tests" in record["reason"]
    assert roles(log).count("debugger") == 1
    assert "verifier" not in roles(log)
    assert len(gate_calls(tmp_path)) == 2
    assert e18(root)["status"] == "blocked"


@pytest.mark.ac("E13-AC-12")
def test_with_no_retries_a_red_gate_stops_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = turns(one_task_plan(), slice_turns(red=True), {"debugger": [DEBUG_FIX]})
    config = slice_config(gate_retries=0)
    root, _, log = start(tmp_path, monkeypatch, capsys, script, config)
    assert to_slices(root, monkeypatch, capsys) == 1
    assert "debugger" not in roles(log)
    assert len(gate_calls(tmp_path)) == 1
    assert read(root)["stage"] == "gate"


@pytest.mark.ac("E13-AC-12")
def test_a_gate_that_writes_no_report_stops_for_a_human(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = slice_config().replace(str(FAKE_GATE).replace("\\", "\\\\"), "no-such-gate.py")
    root, _, log = start(
        tmp_path, monkeypatch, capsys, turns(one_task_plan(), slice_turns()), broken
    )
    assert to_slices(root, monkeypatch, capsys) == 1
    record = read(root)
    assert (record["status"], record["stage"]) == ("needs-human", "gate")
    assert "report" in record["reason"]
    assert record["gates"] == []
    assert "debugger" not in roles(log)


# --- AC-13: review ------------------------------------------------------------------------------


@pytest.mark.ac("E13-AC-13")
def test_review_runs_the_verifier_then_the_five_reviewers_each_in_its_own_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _, log = start(tmp_path, monkeypatch, capsys, turns(one_task_plan(), slice_turns()))
    assert to_slices(root, monkeypatch, capsys) == 0
    assert after(roles(log), "implementer")[:7] == [*REVIEWERS, "docs-writer"]
    for entry in calls(log):
        if entry["role"] in REVIEWERS:
            assert entry["factory_role"] == entry["role"]
            assert entry["allowed"] == pipeline.role_allowed_tools(root, entry["role"])
            assert "at the review stage" in entry["prompt"]
    review = [s for s in read(root)["sessions"] if s["stage"] == "review" and s["role"] != "commit"]
    assert [s["role"] for s in review if s["role"] in REVIEWERS] == list(REVIEWERS)
    assert len({(s["run"], s["index"]) for s in review}) == len(review)


@pytest.mark.ac("E13-AC-13")
def test_the_driver_commits_each_reviewers_findings_on_the_slice_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    reviews = {
        "verifier": [[finding(TASK, "minor", "Name the widget sizes")]],
        "adversary": [[finding(TASK, "minor", "Two widgets clash")]],
    }
    script = turns(one_task_plan(), slice_turns(), reviews)
    root, _, _ = start(tmp_path, monkeypatch, capsys, script)
    assert to_slices(root, monkeypatch, capsys) == 0
    head = str(task_entry(root)["head"])
    log = subjects(root, head)
    assert f"chore({TASK}): review findings from verifier" in log
    assert f"chore({TASK}): review findings from adversary" in log
    assert f"chore({TASK}): review findings from spec-reviewer" not in log
    found = commit_with(root, head, f"chore({TASK}): review findings from verifier")
    assert git(root, "show", "--name-only", "--format=", found).split() == [TASK_REL]
    data = task_file_at(root, head)
    summaries = [f["summary"] for f in data["findings"]]
    assert summaries == ["Name the widget sizes", "Two widgets clash"]


@pytest.mark.ac("E13-AC-13")
def test_after_the_reviews_the_task_s_review_round_is_1_on_the_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _, _ = start(tmp_path, monkeypatch, capsys, turns(one_task_plan(), slice_turns()))
    assert to_slices(root, monkeypatch, capsys) == 0
    head = str(task_entry(root)["head"])
    assert task_file_at(root, head)["review_round"] == 1
    assert f"chore({TASK}): review round 1" in subjects(root, head)


@pytest.mark.ac("E13-AC-13")
@pytest.mark.parametrize("severity", ["blocker", "major"])
def test_an_open_blocker_or_major_finding_stops_the_job_and_the_reason_lists_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    severity: str,
) -> None:
    reviews = {"spec-reviewer": [[finding(TASK, severity, "AC-02 is not met")]]}
    root, _, log = start(
        tmp_path, monkeypatch, capsys, turns(one_task_plan(), slice_turns(), reviews)
    )
    assert to_slices(root, monkeypatch, capsys) == 1
    record = read(root)
    assert (record["status"], record["stage"]) == ("needs-human", "review")
    assert "AC-02 is not met" in record["reason"] and severity in record["reason"]
    assert "docs-writer" not in roles(log)
    assert e18(root)["status"] == "blocked"


@pytest.mark.ac("E13-AC-13")
def test_minor_findings_go_on_to_ship_and_appear_in_the_pr_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    reviews = {"verifier": [[finding(TASK, "minor", "Name the widget sizes")]]}
    root, _, _ = start(
        tmp_path, monkeypatch, capsys, turns(one_task_plan(), slice_turns(), reviews)
    )
    assert to_slices(root, monkeypatch, capsys) == 0
    assert read(root)["status"] == "awaiting-merge"
    assert "Name the widget sizes" in str(task_entry(root)["pr_body"])


# --- AC-14: docs --------------------------------------------------------------------------------


@pytest.mark.ac("E13-AC-14")
def test_docs_commits_the_changelog_entry_and_gates_the_new_head_for_ship(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _, _ = start(tmp_path, monkeypatch, capsys, turns(one_task_plan(), slice_turns()))
    assert to_slices(root, monkeypatch, capsys) == 0
    head = str(task_entry(root)["head"])
    changelog = git(root, "show", f"{head}:CHANGELOG.md")
    assert changelog != CHANGELOG
    assert changelog.index(f"- Widgets for {TASK}.") < changelog.index("## [0.1.0]")
    touched = git(root, "log", "--format=%s", head, "--", "CHANGELOG.md").splitlines()
    assert touched[0].startswith(f"docs({TASK})")
    gates = read(root)["gates"]
    assert len(gates) == 2
    assert gates[-1]["commit"] == head and gates[-1]["verdict"] == "pass"
    assert gates[-1]["commit"][:12] in str(task_entry(root)["pr_body"])


@pytest.mark.ac("E13-AC-14")
def test_a_docs_stage_with_no_changelog_entry_stops_for_a_human(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = turns(one_task_plan(), slice_turns(entry=False))
    root, _, log = start(tmp_path, monkeypatch, capsys, script)
    assert to_slices(root, monkeypatch, capsys) == 1
    record = read(root)
    assert (record["status"], record["stage"]) == ("needs-human", "docs")
    assert "Unreleased" in record["reason"]
    assert "integrator" not in roles(log)


@pytest.mark.ac("E13-AC-14")
def test_a_red_gate_after_the_docs_stage_stops_for_a_human(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    docs = {f"docs-writer@{TASK}": [[add_entry("- Widgets."), {"write": {RED: "red\n"}}]]}
    script = turns(one_task_plan(), slice_turns(), docs, {"debugger": [DEBUG_FIX]})
    root, _, log = start(tmp_path, monkeypatch, capsys, script)
    assert to_slices(root, monkeypatch, capsys) == 1
    record = read(root)
    assert (record["status"], record["stage"]) == ("needs-human", "docs")
    assert "tests" in record["reason"]
    assert [g["verdict"] for g in record["gates"]] == ["pass", "fail"]
    assert "debugger" not in roles(log) and "integrator" not in roles(log)
