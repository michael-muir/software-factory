"""E13-T10: resuming at the review stage gates a stale pass again, instead of stopping.

Covers E13 AC-13, as amended on 28 Nov 2026 by the product owner's decision on #117. Resuming the
live run on #82 at review stopped at once: `resume` starts a new attempt, so every reviewer is
pending again, and the previous round's Adversary had committed an attack test after the gated
commit, so the strict check before the first reviewer failed. Now:

- when no reviewer has run in the attempt, and the newest gate report is a pass but the head has
  changes outside `.agentic/` since its commit, the driver runs the full gate again, and the
  reviews start against it when it's green;
- when that gate is red, the job stops as `needs-human` with the failed checks, and no reviewer
  runs (there's no Debugger loop in review);
- changes only under `.agentic/` need no gate;
- the check before each later reviewer stays strict, so a reviewer that changes code still stops
  the job;
- the driver gates again at most once per attempt, and stops if the head still differs after it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from tests._pipeline import JOB
from tests._pipeline_driver import call, calls, read
from tests._pipeline_slices import (
    FAKE_GATE,
    RED,
    drive,
    gate_calls,
    one_task_plan,
    slice_config,
    slice_turns,
    start,
    to_slices,
    turns,
)

AC = "E13-AC-13"
ATTACK = "tests/test_attack_widgets.py"
ATTACK_TEXT = "def test_widgets_resist_attack() -> None:\n    assert True\n"
LATER = ("standards-reviewer", "security-reviewer", "perf-reviewer", "adversary")


def roles(log: Path) -> list[str]:
    return [c["role"] for c in calls(log)]


def reply(text: str) -> dict[str, Any]:
    """A fake-agent action that prints a session's JSON output with this `result`."""
    return {"print": json.dumps({"result": text, "total_cost_usd": 0.01})}


def change(files: dict[str, str], message: str = "test(E31-T1): attack tests") -> list[Any]:
    """A reviewer's turn that writes these files and commits them."""
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
    config: str | None = None,
) -> tuple[Path, Path, dict[str, Any]]:
    """Run a one-task job until it stops at the review stage, with these reviewers' turns."""
    script = turns(one_task_plan(), slice_turns(), reviews)
    root, _, log = start(tmp_path, monkeypatch, capsys, script, config)
    record = stopped_at_review(root, to_slices(root, monkeypatch, capsys))
    return root, log, record


def resume(root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> int:
    assert call(root, monkeypatch, capsys, "resume", JOB)[0] == 0
    return drive(root, monkeypatch, capsys)


def drifting_gate(tmp_path: Path, on_call: int) -> str:
    """The driver's config with a gate that runs the fake gate, then, on its `on_call`-th run,
    commits a new file after writing its report, so the head moves past the gated commit."""
    wrapper = tmp_path / "drifting_gate.py"
    counter = tmp_path / "drifting-gate-calls.txt"
    wrapper.write_text(
        "import subprocess, sys\n"
        "from pathlib import Path\n"
        f"counter = Path({str(counter)!r})\n"
        "n = int(counter.read_text()) + 1 if counter.is_file() else 1\n"
        "counter.write_text(str(n))\n"
        f"code = subprocess.run([sys.executable, {str(FAKE_GATE)!r}, *sys.argv[1:]]).returncode\n"
        f"if n == {on_call}:\n"
        "    Path('drift.py').write_text('DRIFT = 1\\n')\n"
        "    who = ['-c', 'user.name=t', '-c', 'user.email=t@example.invalid']\n"
        "    subprocess.run(['git', *who, 'add', 'drift.py'], check=True)\n"
        "    subprocess.run(['git', *who, 'commit', '-q', '-m', 'drift'], check=True)\n"
        "sys.exit(code)\n",
        encoding="utf-8",
    )
    old = json.dumps([sys.executable, str(FAKE_GATE)])
    new = json.dumps([sys.executable, str(wrapper)])
    text = slice_config()
    assert old in text
    return text.replace(old, new)


# --- (a) a resume after an attack test was added gates again, then reviews -----------------------


@pytest.mark.ac(AC)
def test_resuming_review_after_an_added_attack_test_gates_again_then_reviews(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    reviews = {"spec-reviewer": [change({ATTACK: ATTACK_TEXT}), []]}
    root, log, record = first_attempt(tmp_path, monkeypatch, capsys, reviews)
    assert ATTACK in record["reason"]
    assert len(gate_calls(tmp_path)) == 1
    stopped_at = len(calls(log))

    code = resume(root, monkeypatch, capsys)
    assert code == 0, read(root).get("reason")
    record = read(root)
    assert record["status"] == "awaiting-merge"
    after = roles(log)[stopped_at:]
    assert after[0] == "verifier"
    assert [r for r in after if r in ("verifier", "spec-reviewer", *LATER)] == [
        "verifier",
        "spec-reviewer",
        *LATER,
    ]
    review_gates = [
        s
        for s in record["sessions"]
        if s["stage"] == "review" and s["role"] == "gate" and s.get("attempt") == 2
    ]
    assert len(review_gates) == 1
    regate = review_gates[0]
    verifier = next(
        s
        for s in record["sessions"]
        if s["role"] == "verifier" and s.get("attempt") == 2 and s["stage"] == "review"
    )
    assert record["sessions"].index(regate) < record["sessions"].index(verifier)
    gates = record["gates"]
    assert [g["verdict"] for g in gates] == ["pass", "pass", "pass"]
    assert len(gate_calls(tmp_path)) == 3  # the gate stage, review's gate again, the docs stage
    assert gates[1]["commit"] != gates[0]["commit"]


# --- (b) a red gate in review stops the job ---------------------------------------------------


@pytest.mark.ac(AC)
def test_a_red_gate_again_at_review_stops_the_job_and_no_reviewer_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    reviews = {"spec-reviewer": [change({RED: "red\n"}, "test(E31-T1): breaks it"), []]}
    root, log, _ = first_attempt(tmp_path, monkeypatch, capsys, reviews)
    stopped_at = len(calls(log))

    code = resume(root, monkeypatch, capsys)
    record = stopped_at_review(root, code)
    assert "python tests" in record["reason"]
    assert len(gate_calls(tmp_path)) == 2
    assert record["gates"][-1]["verdict"] == "fail"
    assert roles(log)[stopped_at:] == []  # no reviewer, and no Debugger
    assert "debugger" not in roles(log)


# --- (c) changes only under .agentic/ need no gate ----------------------------------------------


@pytest.mark.ac(AC)
def test_no_gate_again_when_the_head_differs_only_under_agentic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The first attempt doesn't end red (E13-T11): the Verifier passes, then a reviewer quits.
    note = {".agentic/notes/verifier.md": "The tests step passed.\n"}
    green_turn = [*change(note, "chore(E31-T1): verifier notes"), reply("VERDICT: pass")]
    reviews = {"verifier": [green_turn, []], "spec-reviewer": [[{"exit": 1}], []]}
    root, log, record = first_attempt(tmp_path, monkeypatch, capsys, reviews)
    assert "spec-reviewer" in record["reason"]
    assert len(gate_calls(tmp_path)) == 1

    code = resume(root, monkeypatch, capsys)
    assert code == 0, read(root).get("reason")
    record = read(root)
    assert record["status"] == "awaiting-merge"
    assert not any(s["stage"] == "review" and s["role"] == "gate" for s in record["sessions"])
    assert len(gate_calls(tmp_path)) == 2  # the gate stage and the docs stage only
    assert roles(log).count("verifier") == 2


# --- (d) a reviewer that changes code mid-review still stops the job ---------------------------


@pytest.mark.ac(AC)
def test_a_reviewer_changing_code_in_the_first_attempt_stops_with_no_gate_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    reviews = {"spec-reviewer": [change({"widgets_1.py": "WIDGETS = 2\n"})]}
    _, log, record = first_attempt(tmp_path, monkeypatch, capsys, reviews)
    assert "widgets_1.py" in record["reason"]
    assert len(gate_calls(tmp_path)) == 1
    assert not any(role in roles(log) for role in LATER)


@pytest.mark.ac(AC)
def test_a_reviewer_changing_code_after_the_gate_again_still_stops_the_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    reviews = {
        "spec-reviewer": [change({ATTACK: ATTACK_TEXT}), []],
        "standards-reviewer": [change({"widgets_1.py": "WIDGETS = 2\n"})],
    }
    script = turns(one_task_plan(), slice_turns(), reviews)
    root, _, log = start(tmp_path, monkeypatch, capsys, script)
    stopped_at_review(root, to_slices(root, monkeypatch, capsys))
    assert "standards-reviewer" not in roles(log)
    stopped_at = len(calls(log))

    record = stopped_at_review(root, resume(root, monkeypatch, capsys))
    assert "widgets_1.py" in record["reason"]
    assert len(gate_calls(tmp_path)) == 2  # the gate stage and one gate again, no more
    after = roles(log)[stopped_at:]
    assert after == ["verifier", "spec-reviewer", "standards-reviewer"]


# --- (e) at most one gate again per attempt -------------------------------------------------------


@pytest.mark.ac(AC)
def test_the_driver_gates_again_at_most_once_and_stops_if_the_head_still_differs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    reviews = {"spec-reviewer": [change({ATTACK: ATTACK_TEXT}), []]}
    config = drifting_gate(tmp_path, on_call=2)
    root, log, _ = first_attempt(tmp_path, monkeypatch, capsys, reviews, config)
    stopped_at = len(calls(log))

    record = stopped_at_review(root, resume(root, monkeypatch, capsys))
    assert "drift.py" in record["reason"]
    assert len(gate_calls(tmp_path)) == 2  # the gate stage and one gate again, no more
    review_gates = [s for s in record["sessions"] if s["stage"] == "review" and s["role"] == "gate"]
    assert len(review_gates) == 1
    assert roles(log)[stopped_at:] == []


@pytest.mark.ac(AC)
def test_each_new_attempt_may_gate_again_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    reviews = {"spec-reviewer": [change({ATTACK: ATTACK_TEXT}), []]}
    config = drifting_gate(tmp_path, on_call=2)
    root, _, _ = first_attempt(tmp_path, monkeypatch, capsys, reviews, config)
    stopped_at_review(root, resume(root, monkeypatch, capsys))

    code = resume(root, monkeypatch, capsys)
    assert code == 0, read(root).get("reason")
    assert read(root)["status"] == "awaiting-merge"
    attempts = [
        s["attempt"]
        for s in read(root)["sessions"]
        if s["stage"] == "review" and s["role"] == "gate"
    ]
    assert attempts == [2, 3]
