"""E13/T2: `pipeline.py run`, `resume` and `cancel`, driving the plan stages with a fake agent.

Covers E13 AC-05, AC-06, AC-08, AC-09 and AC-10. Expectations come from the E13 spec (those ACs,
Changes of 21 Nov 2026), the design note ("The driver", "Sessions and the allow-list") and ADR
0041: one action per step, written down before it's confirmed; E18's lease held while writing;
a runner job ended at every wait.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import pipeline
from tests._ac import REPO_ROOT
from tests._pipeline import JOB, SPEC_REL, spec_text
from tests._pipeline_driver import (
    PLAN,
    SPEC_TURN,
    FakeRunner,
    call,
    calls,
    config_text,
    driver_repo,
    e18,
    jobs_module,
    new_job,
    read,
    script,
    use_runner,
)


def ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    turns: dict[str, Any] | None = None,
    config: str | None = None,
    **runner: Any,
) -> tuple[Path, FakeRunner, Path]:
    root = driver_repo(tmp_path, monkeypatch, config)
    log = script(tmp_path, monkeypatch, PLAN if turns is None else turns)
    fake = use_runner(monkeypatch, FakeRunner(root, **runner))
    new_job(root, monkeypatch, capsys, tmp_path)
    return root, fake, log


def run(root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> int:
    return call(root, monkeypatch, capsys, "run", JOB)[0]


def roles(log: Path) -> list[str]:
    return [c["role"] for c in calls(log)]


# --- AC-06: run ---------------------------------------------------------------------------------


@pytest.mark.ac("E13-AC-06")
def test_run_drives_the_spec_stage_to_its_checkpoint_through_the_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, fake, _log = ready(tmp_path, monkeypatch, capsys)
    assert run(root, monkeypatch, capsys) == 0
    kinds = [c[0] for c in fake.calls]
    assert kinds == ["submit", "send", "usage", "close"]
    assert fake.calls[0] == ("submit", f"{JOB}-p1", "main", JOB)
    record = read(root)
    assert (record["status"], record["stage"]) == ("awaiting-approval", "spec")
    assert fake.jobs[f"{JOB}-p1"]["status"] == "succeeded"


@pytest.mark.ac("E13-AC-06")
def test_each_session_runs_as_its_role_with_its_allow_list_and_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _, log = ready(tmp_path, monkeypatch, capsys)
    run(root, monkeypatch, capsys)
    [session] = calls(log)
    assert session["role"] == "spec-writer"
    assert session["factory_role"] == "spec-writer"
    assert session["allowed"] == pipeline.role_allowed_tools(root, "spec-writer")
    assert "Epic: E31. Task: e31-widgets." in session["prompt"]
    assert "Follow the skill: spec-interview." in session["prompt"]
    assert "They should be small." in session["prompt"]  # the request
    assert Path(session["cwd"]).name == f"{JOB}-p1"


@pytest.mark.ac("E13-AC-06")
def test_run_keeps_the_e18_job_current_and_releases_its_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, fake, _ = ready(tmp_path, monkeypatch, capsys)
    run(root, monkeypatch, capsys)
    job = e18(root)
    assert (job["phase"], job["status"], job["task"]) == ("spec", "blocked", JOB)
    assert job["branch"] == f"factory/{JOB}-p1"
    assert job["worktree"] == fake.jobs[f"{JOB}-p1"]["worktree"]
    assert job["claims"], "run claimed the job"
    jobs = jobs_module()
    assert jobs.lease_state(jobs.find_repo(root), JOB) == "unclaimed"


@pytest.mark.ac("E13-AC-06")
def test_run_is_refused_while_another_session_holds_the_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, fake, log = ready(tmp_path, monkeypatch, capsys)
    jobs = jobs_module()
    repo = jobs.find_repo(root)
    jobs.claim(repo, jobs.load_config(repo), JOB, "someone-else")
    before = read(root)
    code, _, err = call(root, monkeypatch, capsys, "run", JOB)
    assert code == 1
    assert "someone-else" in err
    assert fake.calls == [] and calls(log) == []
    assert read(root) == before


@pytest.mark.ac("E13-AC-06")
def test_run_keeps_its_lease_alive_through_a_long_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    slow = [{"run": [sys.executable, "-c", "import time; time.sleep(2)"]}, *SPEC_TURN]
    config = config_text() + "\n[jobs]\nlease_minutes = 0.02\n"
    root, _, _ = ready(tmp_path, monkeypatch, capsys, {"spec-writer": [slow]}, config)
    assert run(root, monkeypatch, capsys) == 0
    assert read(root)["status"] == "awaiting-approval"


class Crash(Exception):
    pass


@pytest.mark.ac("E13-AC-06")
def test_a_crash_between_recording_and_sending_never_sends_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, fake, log = ready(tmp_path, monkeypatch, capsys)
    real_send = fake.send

    def crash(job_id: str, argv: Any) -> None:
        raise Crash("the machine restarted")

    monkeypatch.setattr(fake, "send", crash)
    with pytest.raises(Crash):
        pipeline.main(["run", JOB])
    assert [s["role"] for s in read(root)["sessions"]] == ["spec-writer"]
    monkeypatch.setattr(fake, "send", real_send)
    assert run(root, monkeypatch, capsys) == 0
    assert roles(log) == ["spec-writer"]
    assert [s["role"] for s in read(root)["sessions"]] == ["spec-writer"]
    assert [c[0] for c in fake.calls].count("submit") == 1


@pytest.mark.ac("E13-AC-06")
def test_run_again_never_repeats_a_passed_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _, log = ready(tmp_path, monkeypatch, capsys)
    run(root, monkeypatch, capsys)
    call(root, monkeypatch, capsys, "approve", JOB, "spec", "--by", "po")
    assert run(root, monkeypatch, capsys) == 0
    assert run(root, monkeypatch, capsys) == 0  # waiting at the design checkpoint
    assert roles(log) == ["spec-writer", "architect"]


@pytest.mark.ac("E13-AC-06")
def test_run_on_a_finished_job_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, fake, _ = ready(tmp_path, monkeypatch, capsys)
    assert call(root, monkeypatch, capsys, "cancel", JOB)[0] == 0
    assert run(root, monkeypatch, capsys) == 1
    assert fake.calls == []


# --- AC-05: stage order -------------------------------------------------------------------------


@pytest.mark.ac("E13-AC-05")
def test_a_waiting_checkpoint_is_never_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, fake, log = ready(tmp_path, monkeypatch, capsys)
    run(root, monkeypatch, capsys)
    sent = len(fake.calls)
    assert run(root, monkeypatch, capsys) == 0
    assert len(fake.calls) == sent
    assert roles(log) == ["spec-writer"]
    assert read(root)["stage"] == "spec"


@pytest.mark.ac("E13-AC-05")
def test_a_failed_check_leaves_the_job_at_its_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _, log = ready(tmp_path, monkeypatch, capsys, {"spec-writer": [[]]})
    assert run(root, monkeypatch, capsys) == 1
    record = read(root)
    assert (record["status"], record["stage"], record["task"]) == ("needs-human", "spec", JOB)
    assert "docs/specs" in record["reason"]
    assert run(root, monkeypatch, capsys) == 1
    assert roles(log) == ["spec-writer"]


@pytest.mark.ac("E13-AC-05")
def test_without_a_design_checkpoint_the_job_moves_on_to_the_first_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = config_text(checkpoints=("spec", "merge"))
    root, fake, log = ready(tmp_path, monkeypatch, capsys, config=config)
    run(root, monkeypatch, capsys)
    call(root, monkeypatch, capsys, "approve", JOB, "spec", "--by", "po")
    run(root, monkeypatch, capsys)  # design passes, then the test stage has nothing to lock
    assert roles(log) == ["spec-writer", "architect", "test-designer"]
    record = read(root)
    assert (record["stage"], record["task"]) == ("test", "E31-T1")
    assert [t["id"] for t in record["tasks"]] == ["E31-T1"]
    assert e18(root)["task"] == "E31-T1"
    slice_submit = [c for c in fake.calls if c[0] == "submit"][-1]
    assert slice_submit == ("submit", f"{JOB}-t1-1", f"factory/{JOB}-p2", "E31-T1")


@pytest.mark.ac("E13-AC-05")
def test_the_plan_continues_from_the_approved_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, fake, _ = ready(tmp_path, monkeypatch, capsys)
    run(root, monkeypatch, capsys)
    call(root, monkeypatch, capsys, "approve", JOB, "spec", "--by", "po")
    run(root, monkeypatch, capsys)
    submits = [c for c in fake.calls if c[0] == "submit"]
    assert submits[1] == ("submit", f"{JOB}-p2", f"factory/{JOB}-p1", JOB)
    assert read(root)["stage"] == "design"


# --- AC-08: cost --------------------------------------------------------------------------------


@pytest.mark.ac("E13-AC-08")
def test_the_sessions_cost_goes_to_the_runners_ledger_and_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    turn = [{"cost": 0.42}, *SPEC_TURN]
    root, fake, _ = ready(tmp_path, monkeypatch, capsys, {"spec-writer": [turn]})
    run(root, monkeypatch, capsys)
    assert ("usage", f"{JOB}-p1", "0.42") in fake.calls
    [session] = read(root)["sessions"]
    assert session["usd"] == "0.42"


@pytest.mark.ac("E13-AC-08")
@pytest.mark.parametrize("output", [{"cost": None}, {"print": "not json at all"}])
def test_output_without_a_cost_is_a_warning_and_the_stage_carries_on(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    output: dict[str, Any],
) -> None:
    root, fake, _ = ready(tmp_path, monkeypatch, capsys, {"spec-writer": [[output, *SPEC_TURN]]})
    assert run(root, monkeypatch, capsys) == 0
    record = read(root)
    assert record["status"] == "awaiting-approval"
    assert any("cost" in w and "spec-writer" in w for w in record["warnings"])
    assert not [c for c in fake.calls if c[0] == "usage"]


@pytest.mark.ac("E13-AC-08")
def test_a_runner_cap_halt_stops_the_job_for_a_human(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _, _ = ready(tmp_path, monkeypatch, capsys, halt_on="spec-writer")
    assert run(root, monkeypatch, capsys) == 1
    record = read(root)
    assert record["status"] == "needs-human"
    assert "turn cap (3)" in record["reason"]
    assert e18(root)["status"] == "blocked"


# --- AC-09: stopping for a human ----------------------------------------------------------------


@pytest.mark.ac("E13-AC-09")
def test_a_session_that_exits_non_zero_stops_the_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, fake, _log = ready(tmp_path, monkeypatch, capsys, {"spec-writer": [[{"exit": 3}]]})
    assert run(root, monkeypatch, capsys) == 1
    record = read(root)
    assert record["status"] == "needs-human"
    assert "spec" in record["reason"] and "3" in record["reason"]
    assert fake.jobs[f"{JOB}-p1"]["closed"], "the runner job is ended at the wait"
    assert e18(root)["status"] == "blocked"


@pytest.mark.ac("E13-AC-09")
def test_the_reason_names_the_checks_problems(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = spec_text().replace("## Out of scope", "## Outside")
    turn = [{"write": {SPEC_REL: broken}}, {"commit": "docs: spec"}]
    root, _, _ = ready(tmp_path, monkeypatch, capsys, {"spec-writer": [turn]})
    assert run(root, monkeypatch, capsys) == 1
    reason = read(root)["reason"]
    assert SPEC_REL in reason and "Out of scope" in reason


@pytest.mark.ac("E13-AC-09")
def test_a_runner_that_refuses_a_command_stops_the_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _, _ = ready(tmp_path, monkeypatch, capsys, fail_send=True)
    assert run(root, monkeypatch, capsys) == 1
    assert read(root)["status"] == "needs-human"


# --- AC-10: resume and cancel -------------------------------------------------------------------


@pytest.mark.ac("E13-AC-10")
def test_resume_reruns_the_stopped_stage_with_the_note_from_the_old_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    turns = {"spec-writer": [[{"exit": 3}], SPEC_TURN]}
    root, fake, log = ready(tmp_path, monkeypatch, capsys, turns)
    run(root, monkeypatch, capsys)
    code, _, _ = call(root, monkeypatch, capsys, "resume", JOB, "--note", "try again")
    assert code == 0
    assert read(root)["status"] == "ready"
    assert run(root, monkeypatch, capsys) == 0
    second = calls(log)[1]
    assert "try again" in second["prompt"]
    submits = [c for c in fake.calls if c[0] == "submit"]
    assert submits[1] == ("submit", f"{JOB}-p2", f"factory/{JOB}-p1", JOB)
    assert read(root)["status"] == "awaiting-approval"


@pytest.mark.ac("E13-AC-10")
@pytest.mark.parametrize("command", ["resume", "cancel"])
def test_resume_and_cancel_refuse_a_cancelled_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    root, _, _ = ready(tmp_path, monkeypatch, capsys)
    call(root, monkeypatch, capsys, "cancel", JOB)
    before = read(root)
    assert call(root, monkeypatch, capsys, command, JOB)[0] == 1
    assert read(root) == before


@pytest.mark.ac("E13-AC-10")
def test_resume_refuses_a_job_that_does_not_need_a_human(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _, _ = ready(tmp_path, monkeypatch, capsys)
    assert call(root, monkeypatch, capsys, "resume", JOB)[0] == 1
    run(root, monkeypatch, capsys)
    assert call(root, monkeypatch, capsys, "resume", JOB)[0] == 1  # awaiting approval


@pytest.mark.ac("E13-AC-10")
def test_cancel_cancels_the_open_runner_job_and_the_e18_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, fake, _ = ready(tmp_path, monkeypatch, capsys)
    monkeypatch.setattr(fake, "send", lambda job_id, argv: (_ for _ in ()).throw(Crash()))
    with pytest.raises(Crash):
        pipeline.main(["run", JOB])
    assert call(root, monkeypatch, capsys, "cancel", JOB)[0] == 0
    assert ("cancel", f"{JOB}-p1") in fake.calls
    assert read(root)["status"] == "cancelled"
    assert e18(root)["status"] == "cancelled"


@pytest.mark.ac("E13-AC-10")
@pytest.mark.parametrize("command", [["resume", JOB], ["cancel", JOB]])
def test_resume_and_cancel_are_refused_while_another_session_holds_the_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: list[str],
) -> None:
    root, _, _ = ready(tmp_path, monkeypatch, capsys, {"spec-writer": [[{"exit": 3}]]})
    run(root, monkeypatch, capsys)
    jobs = jobs_module()
    repo = jobs.find_repo(root)
    jobs.claim(repo, jobs.load_config(repo), JOB, "someone-else")
    before = read(root)
    assert call(root, monkeypatch, capsys, *command)[0] == 1
    assert read(root) == before


# --- AC-06 with a real E16 daemon ---------------------------------------------------------------

RUN_PY = REPO_ROOT / "kit" / ".factory" / "runner" / "run.py"
PIPELINE_PY = REPO_ROOT / "kit" / ".factory" / "workflow" / "pipeline.py"


@pytest.mark.slow
@pytest.mark.ac("E13-AC-06")
def test_run_drives_the_spec_stage_on_a_real_daemon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = driver_repo(tmp_path, monkeypatch)
    script(tmp_path, monkeypatch, PLAN)
    new_job(root, monkeypatch, capsys, tmp_path)
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    daemon = subprocess.Popen(
        [sys.executable, str(RUN_PY), "--daemon"], cwd=root, creationflags=flags
    )
    try:
        done = subprocess.run(
            [sys.executable, str(PIPELINE_PY), "run", JOB],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=240,
            check=False,
        )
        assert done.returncode == 0, done.stdout + done.stderr
        assert read(root)["status"] == "awaiting-approval"
        status = subprocess.run(
            [sys.executable, str(RUN_PY), "status", f"{JOB}-p1", "--json"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        assert '"succeeded"' in status.stdout
    finally:
        subprocess.run([sys.executable, str(RUN_PY), "stop"], cwd=root, check=False)
        try:
            daemon.wait(timeout=30)
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                daemon.send_signal(signal.SIGKILL)
            daemon.kill()
            daemon.wait(timeout=10)
