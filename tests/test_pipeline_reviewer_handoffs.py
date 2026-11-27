"""E13-T7: reviewers hand off through their final reply, and use the driver's gate report.

Covers E13 AC-07 and AC-13, as amended on 26 Nov 2026 by the product owner's decisions on #106.
In the live run on #82, the reviewers without a shell couldn't write a handoff body past the E03
hook, and each reran the full gate. Now:

- a role without a shell ends its prompt with "Don't commit: the driver commits your files. End
  with your handoff note as your final reply, and stop.";
- every review session gets the task's newest gate report as `$FACTORY_GATE_REPORT`, the
  Verifier checks it rather than running the gate, and the others run only `gate.py --checks`;
- after a reviewer without a shell, the driver records its reply (the JSON `result`, or plain
  output) with `state.py handoff`, and commits it with the findings; a reply without the three
  headings adds a warning, and the stage carries on.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

import pipeline
from tests._ac import REPO_ROOT
from tests._pipeline import REVIEWERS, TASK, TASK_REL, git
from tests._pipeline_driver import calls, read
from tests._pipeline_slices import (
    finding,
    gate_calls,
    one_task_plan,
    run,
    slice_turns,
    start,
    task_entry,
    to_slices,
    turns,
)

NO_SHELL = "Don't commit: the driver commits your files. End with your handoff note as your final reply, and stop."  # noqa: E501
SHELL = "Work only in this worktree. Commit your work and stop."
NOTE = """## Done

- Checked the driver's gate report: a full pass on the head.

## Next

- The spec reviewer reads the change.

## Open questions

None.

VERDICT: pass"""
PLAIN_NOTE = NOTE.replace("VERDICT: pass", "Plain output, no JSON.")
NO_SHELL_REVIEWERS = [r for r in REVIEWERS if r != "adversary"]


def reply(text: str) -> dict[str, Any]:
    """The fake agent's final output: Claude Code's JSON, with the reply in `result`."""
    return {"print": json.dumps({"type": "result", "result": text, "total_cost_usd": 0.01})}


def handoffs_at(root: Path, commit: str) -> dict[str, str]:
    """The handoff notes in the commit's tree, by path."""
    names = git(root, "ls-tree", "-r", "--name-only", commit, "--", ".agentic/handoffs").split()
    return {name: git(root, "show", f"{commit}:{name}") for name in names}


def front(text: str) -> dict[str, Any]:
    import tomllib

    return tomllib.loads(text.split("+++")[1])


def body(text: str) -> str:
    return text.split("+++", 2)[2]


def commit_with(root: Path, commit: str, subject: str) -> str:
    lines = git(root, "log", "--format=%H %s", commit).splitlines()
    return next(line.split(" ", 1)[0] for line in lines if line.split(" ", 1)[1] == subject)


def env_spy(name: str, out: Path) -> dict[str, Any]:
    """A turn action that copies `$FACTORY_GATE_REPORT`'s file (or "unset") to `out`."""
    code = (
        "import os, sys; p = os.environ.get('FACTORY_GATE_REPORT'); "
        "open(sys.argv[1], 'w', encoding='utf-8').write("
        "open(p, encoding='utf-8').read() if p else 'unset')"
    )
    return run(sys.executable, "-c", code, str(out / f"{name}.json"))


# --- AC-07: the last prompt line ----------------------------------------------------------------


@pytest.mark.ac("E13-AC-07")
def test_a_role_without_a_shell_ends_with_the_no_commit_line() -> None:
    text = pipeline.prompt("review", "verifier", job="j", epic="E31", task="E31-T1", shell=False)
    lines = text.splitlines()
    assert lines[-1] == NO_SHELL
    assert "Commit your work and stop." not in text


@pytest.mark.ac("E13-AC-07")
def test_a_role_with_a_shell_still_commits_its_work() -> None:
    text = pipeline.prompt("build", "implementer", job="j", epic="E31", task="E31-T1", shell=True)
    assert text.splitlines()[-1] == SHELL
    assert NO_SHELL not in text


@pytest.mark.ac("E13-AC-07")
def test_the_driver_gives_every_session_the_last_line_its_card_calls_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _, log = start(tmp_path, monkeypatch, capsys, turns(one_task_plan(), slice_turns()))
    assert to_slices(root, monkeypatch, capsys) == 0
    seen = {}
    for entry in calls(log):
        last = entry["prompt"].splitlines()[-1]
        shell = pipeline.has_shell(root, entry["role"])
        assert last == (SHELL if shell else NO_SHELL), entry["role"]
        seen[entry["role"]] = shell
    assert seen["verifier"] is False and seen["spec-writer"] is False
    assert seen["docs-writer"] is False
    assert seen["implementer"] is True and seen["adversary"] is True


# --- AC-13: the driver's gate report for every review session -----------------------------------


@pytest.mark.ac("E13-AC-13")
def test_every_review_session_gets_the_newest_gate_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "seen"
    out.mkdir()
    spies = {role: [[env_spy(role, out)]] for role in REVIEWERS}
    script = turns(one_task_plan(), slice_turns(), spies)
    root, _, log = start(tmp_path, monkeypatch, capsys, script)
    assert to_slices(root, monkeypatch, capsys) == 0
    record = read(root)
    gate = json.loads(record["gates"][0]["report"])
    for role in REVIEWERS:
        handed = json.loads((out / f"{role}.json").read_text(encoding="utf-8"))
        assert handed == gate, role
    prompts = {c["role"]: c["prompt"] for c in calls(log) if c["role"] in REVIEWERS}
    for role, text in prompts.items():
        assert "$FACTORY_GATE_REPORT" in text, role
        assert "gate-report.json" in text, role


@pytest.mark.ac("E13-AC-13")
def test_the_verifier_is_told_to_check_the_report_and_not_run_the_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _, log = start(tmp_path, monkeypatch, capsys, turns(one_task_plan(), slice_turns()))
    assert to_slices(root, monkeypatch, capsys) == 0
    prompts = {c["role"]: c["prompt"] for c in calls(log) if c["role"] in REVIEWERS}
    verifier = prompts["verifier"]
    assert "don't run the gate" in verifier
    for part in ("--checks", "dirty", ".agentic/", "HEAD", "tagged"):
        assert part in verifier, part
    for role in REVIEWERS[1:]:
        assert "gate.py --checks <name>" in prompts[role], role
        assert "Don't run the full gate" in prompts[role], role


@pytest.mark.ac("E13-AC-13")
def test_in_a_fake_agent_run_only_the_driver_runs_the_full_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = turns(one_task_plan(), slice_turns(), {"verifier": [[reply(NOTE)]]})
    root, _, _ = start(tmp_path, monkeypatch, capsys, script)
    assert to_slices(root, monkeypatch, capsys) == 0
    record = read(root)
    gates = [s for s in record["sessions"] if s["role"] == "gate"]
    assert [s["stage"] for s in gates] == ["gate", "docs"]
    ran = gate_calls(tmp_path)
    assert len(ran) == len(gates) == 2
    assert all("--checks" not in c["argv"] for c in ran)


# --- AC-13: the handoff recorded from the reply ------------------------------------------------


@pytest.mark.ac("E13-AC-13")
def test_the_driver_records_a_reviewers_reply_as_its_handoff_and_commits_it_with_the_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    reviews = {"verifier": [[finding(TASK, "minor", "Name the widget sizes"), reply(NOTE)]]}
    script = turns(one_task_plan(), slice_turns(), reviews)
    root, _, _ = start(tmp_path, monkeypatch, capsys, script)
    assert to_slices(root, monkeypatch, capsys) == 0
    head = str(task_entry(root)["head"])
    notes = [text for text in handoffs_at(root, head).values() if front(text)["from"] == "verifier"]
    assert len(notes) == 1
    assert front(notes[0])["task"] == TASK
    assert body(notes[0]).strip() == NOTE  # intact, the VERDICT line included
    found = commit_with(root, head, f"chore({TASK}): review findings and handoff from verifier")
    files = git(root, "show", "--name-only", "--format=", found).split()
    assert TASK_REL in files
    assert [f for f in files if f.startswith(".agentic/handoffs/")] == [
        name for name, text in handoffs_at(root, head).items() if text == notes[0]
    ]
    assert not [w for w in read(root)["warnings"] if "verifier" in w]


@pytest.mark.ac("E13-AC-13")
def test_a_plain_output_reply_is_recorded_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    reviews = {"spec-reviewer": [[{"print": PLAIN_NOTE}]]}
    root, _, _ = start(
        tmp_path, monkeypatch, capsys, turns(one_task_plan(), slice_turns(), reviews)
    )
    assert to_slices(root, monkeypatch, capsys) == 0
    head = str(task_entry(root)["head"])
    notes = [t for t in handoffs_at(root, head).values() if front(t)["from"] == "spec-reviewer"]
    assert [body(t).strip() for t in notes] == [PLAIN_NOTE]
    subjects = git(root, "log", "--format=%s", head).splitlines()
    assert f"chore({TASK}): handoff from spec-reviewer" in subjects


@pytest.mark.ac("E13-AC-13")
def test_each_reviewer_without_a_shell_gets_its_own_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    reviews = {role: [[reply(NOTE.replace("spec reviewer", role))]] for role in REVIEWERS}
    root, _, _ = start(
        tmp_path, monkeypatch, capsys, turns(one_task_plan(), slice_turns(), reviews)
    )
    assert to_slices(root, monkeypatch, capsys) == 0
    head = str(task_entry(root)["head"])
    senders = sorted(front(t)["from"] for t in handoffs_at(root, head).values())
    # the adversary has a shell, so it records its own handoff; the driver doesn't
    assert senders == sorted(NO_SHELL_REVIEWERS)
    assert not read(root)["warnings"]
    assert read(root)["status"] == "awaiting-merge"


@pytest.mark.ac("E13-AC-13")
def test_a_reply_without_the_headings_warns_and_the_stage_carries_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    reviews = {
        "verifier": [[reply(NOTE)]],
        "standards-reviewer": [[reply("All fine, no handoff here.")]],
    }
    root, _, log = start(
        tmp_path, monkeypatch, capsys, turns(one_task_plan(), slice_turns(), reviews)
    )
    assert to_slices(root, monkeypatch, capsys) == 0
    record = read(root)
    assert record["status"] == "awaiting-merge"
    warned = [w for w in record["warnings"] if "handoff" in w]
    assert any("standards-reviewer" in w for w in warned), record["warnings"]
    assert not any("verifier" in w for w in warned)
    head = str(task_entry(root)["head"])
    senders = [front(t)["from"] for t in handoffs_at(root, head).values()]
    assert "standards-reviewer" not in senders and "verifier" in senders
    assert "docs-writer" in [c["role"] for c in calls(log)]


@pytest.mark.ac("E13-AC-13")
def test_a_second_run_never_records_a_handoff_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    reviews = {"verifier": [[reply(NOTE)]]}
    root, _, _ = start(
        tmp_path, monkeypatch, capsys, turns(one_task_plan(), slice_turns(), reviews)
    )
    assert to_slices(root, monkeypatch, capsys) == 0
    from tests._pipeline_slices import drive

    assert drive(root, monkeypatch, capsys) == 0  # awaiting the merge: nothing new
    head = str(task_entry(root)["head"])
    senders = [front(t)["from"] for t in handoffs_at(root, head).values()]
    assert senders.count("verifier") == 1
    marks = [s.get("handoff") for s in read(root)["sessions"] if s["role"] == "verifier"]
    assert marks == ["recorded"]


# --- the reply, read from a session's log ------------------------------------------------------


@pytest.mark.ac("E13-AC-13")
@pytest.mark.parametrize(
    ("log", "expected"),
    [
        (json.dumps({"type": "result", "result": NOTE, "total_cost_usd": 0.5}), NOTE),
        ("a warning on stderr\n" + json.dumps({"result": NOTE}), NOTE),
        (PLAIN_NOTE + "\n", PLAIN_NOTE),
        ("", ""),
    ],
)
def test_the_reply_is_the_json_result_or_the_plain_output(
    tmp_path: Path, log: str, expected: str
) -> None:
    path = tmp_path / "session.log"
    path.write_text(log, encoding="utf-8")
    assert pipeline.session_reply(path) == expected


@pytest.mark.ac("E13-AC-13")
def test_a_missing_log_has_no_reply(tmp_path: Path) -> None:
    assert pipeline.session_reply(tmp_path / "gone.log") == ""


# --- the cards and the skill: a branch for the driver's report ---------------------------------

KIT = REPO_ROOT / "kit" / ".factory"


@pytest.mark.ac("E13-AC-13")
@pytest.mark.parametrize(
    "rel",
    [
        "agents/core/verifier.md",
        "agents/core/spec-reviewer.md",
        "skills/verify-with-evidence/SKILL.md",
    ],
)
def test_the_cards_and_the_skill_say_what_to_do_with_the_drivers_report(rel: str) -> None:
    text = (KIT / rel).read_text(encoding="utf-8")
    assert "FACTORY_GATE_REPORT" in text, rel
    assert "final reply" in text, rel


@pytest.mark.ac("E13-AC-13")
def test_the_verify_skill_keeps_the_full_gate_for_interactive_use() -> None:
    text = (KIT / "skills" / "verify-with-evidence" / "SKILL.md").read_text(encoding="utf-8")
    assert "python .factory/gates/gate.py" in text
    assert "don't run the gate" in text
