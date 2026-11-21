"""E16/T4: the caps (turns, cost and time) and the usage ledger, driven in-process.

Covers E16 AC-13, AC-14 and AC-15. Expectations come from the E16 spec and the design note ("The
daemon loop", "Test seams"), not from the implementation. The daemon runs with the fake starter
and a fake clock from tests/_daemon.py, so every cap's boundary is tested without waiting.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests._daemon import T0, Clock, FakeStart, make_daemon, record
from tests._halt import factory_repo, handoffs
from tests._runner import RUN_PY, call, submit

PY = [sys.executable, "-c", "pass"]


def config(**keys: object) -> str:
    """A config with [runner] and [budgets] keys, given as section_key=value."""
    sections: dict[str, list[str]] = {"runner": [], "budgets": []}
    for name, value in keys.items():
        section, key = name.split("_", 1)
        sections[section].append(f"{key} = {value}")
    return "".join(f"[{s}]\n" + "\n".join(lines) + "\n" for s, lines in sections.items() if lines)


def send(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], job: str
) -> None:
    code, _, err = call(repo, monkeypatch, capsys, "send", job, "--", *PY)
    assert code == 0, err


def usage(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    job: str,
    usd: str,
) -> int:
    code, _, _ = call(repo, monkeypatch, capsys, "usage", job, "--usd", usd)
    return code


def status_json(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], job: str
) -> dict[str, object]:
    code, out, err = call(repo, monkeypatch, capsys, "status", job, "--json")
    assert code == 0, err
    data: dict[str, object] = json.loads(out)
    return data


def finish_current(start: FakeStart, job: str, code: int = 0) -> None:
    current = start.for_job(job)[-1]
    assert current.proc.code is None, "the latest command should still be running"
    current.proc.finish(code)


# --- AC-13: turns ------------------------------------------------------------------------------


@pytest.mark.ac("E16-AC-13")
def test_a_command_counts_as_a_turn_when_it_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = factory_repo(tmp_path)
    job = submit(repo, monkeypatch, capsys, "--open", "--", *PY)
    start, clock = FakeStart(), Clock()
    daemon = make_daemon(repo, start)
    clock.tick(daemon)
    assert len(start.for_job(job)) == 1
    assert record(repo, job)["turns"] == 1, "a running command has already used its turn"
    finish_current(start, job)
    clock.tick(daemon)
    assert record(repo, job)["turns"] == 1, "finishing it doesn't count again"


@pytest.mark.ac("E16-AC-13")
def test_the_turn_cap_halts_a_job_with_another_command_queued(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = factory_repo(tmp_path, config(runner_max_turns=3))
    job = submit(repo, monkeypatch, capsys, "--open", "--", *PY)
    for _ in range(3):
        send(repo, monkeypatch, capsys, job)
    call(repo, monkeypatch, capsys, "close", job)
    start, clock = FakeStart(), Clock()
    daemon = make_daemon(repo, start)

    for _ in range(3):
        clock.tick(daemon)
        clock.tick(daemon)
        assert not start.for_job(job)[-1].proc.killed, "the cap never kills a turn in progress"
        assert record(repo, job)["status"] == "running"
        finish_current(start, job)
    clock.tick(daemon, 3)

    data = record(repo, job)
    assert data["status"] == "halted"
    assert data["reason"] == "turn cap (3)"
    assert data["turns"] == 3
    assert len(start.for_job(job)) == 3, "the fourth command never runs"
    assert Path(data["worktree"]).is_dir()
    assert len(handoffs(Path(data["worktree"]), job)) == 1


@pytest.mark.ac("E16-AC-13")
def test_the_turn_cap_halts_a_job_that_is_still_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = factory_repo(tmp_path, config(runner_max_turns=2))
    job = submit(repo, monkeypatch, capsys, "--open", "--", *PY)
    send(repo, monkeypatch, capsys, job)
    start, clock = FakeStart(), Clock()
    daemon = make_daemon(repo, start)
    clock.tick(daemon)
    finish_current(start, job)
    clock.tick(daemon)
    finish_current(start, job)
    clock.tick(daemon, 2)

    data = record(repo, job)
    assert data["status"] == "halted"
    assert data["reason"] == "turn cap (2)"


@pytest.mark.ac("E16-AC-13")
def test_a_closed_job_that_ends_exactly_on_the_cap_is_not_halted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = factory_repo(tmp_path, config(runner_max_turns=3))
    job = submit(repo, monkeypatch, capsys, "--open", "--", *PY)
    send(repo, monkeypatch, capsys, job)
    send(repo, monkeypatch, capsys, job)
    call(repo, monkeypatch, capsys, "close", job)
    start, clock = FakeStart(), Clock()
    daemon = make_daemon(repo, start)
    for _ in range(3):
        clock.tick(daemon)
        finish_current(start, job)
    clock.tick(daemon, 2)

    data = record(repo, job)
    assert data["status"] == "succeeded", data["reason"]
    assert data["turns"] == 3


@pytest.mark.ac("E16-AC-13")
def test_a_one_command_job_with_one_turn_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = factory_repo(tmp_path, config(runner_max_turns=1))
    job = submit(repo, monkeypatch, capsys, "--", *PY)
    start, clock = FakeStart(), Clock()
    daemon = make_daemon(repo, start)
    clock.tick(daemon)
    finish_current(start, job)
    clock.tick(daemon, 2)
    assert record(repo, job)["status"] == "succeeded"


@pytest.mark.ac("E16-AC-13")
def test_usage_reports_use_no_turns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = factory_repo(tmp_path, config(runner_max_turns=1))
    job = submit(repo, monkeypatch, capsys, "--open", "--", *PY)
    start, clock = FakeStart(), Clock()
    daemon = make_daemon(repo, start)
    clock.tick(daemon)
    for _ in range(3):
        assert usage(repo, monkeypatch, capsys, job, "0.01") == 0
        clock.tick(daemon)
    assert record(repo, job)["turns"] == 1
    assert record(repo, job)["status"] == "running", "the one turn is still in progress"


# --- AC-14: the usage ledger -----------------------------------------------------------------


@pytest.mark.ac("E16-AC-14")
def test_usage_adds_to_the_jobs_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = factory_repo(tmp_path)
    job = submit(repo, monkeypatch, capsys, "--", *PY)
    assert status_json(repo, monkeypatch, capsys, job)["usd"] == 0
    for amount in ("0.10", "0.20", "0", "1e-1"):
        assert usage(repo, monkeypatch, capsys, job, amount) == 0
    assert status_json(repo, monkeypatch, capsys, job)["usd"] == pytest.approx(0.4, abs=1e-12)


@pytest.mark.ac("E16-AC-14")
@pytest.mark.parametrize("amount", ["-0.01", "abc", "nan", "inf", "-inf", "", "1,5"])
def test_usage_refuses_an_amount_that_is_not_a_number_0_or_more(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    amount: str,
) -> None:
    repo = factory_repo(tmp_path)
    job = submit(repo, monkeypatch, capsys, "--", *PY)
    assert usage(repo, monkeypatch, capsys, job, amount) == 2
    assert status_json(repo, monkeypatch, capsys, job)["usd"] == 0


@pytest.mark.ac("E16-AC-14")
def test_usage_refuses_an_unknown_job_a_missing_amount_or_a_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = factory_repo(tmp_path)
    assert usage(repo, monkeypatch, capsys, "no-such-job", "1") == 2
    job = submit(repo, monkeypatch, capsys, "--", *PY)
    assert call(repo, monkeypatch, capsys, "usage", job)[0] == 2
    assert call(repo, monkeypatch, capsys, "usage", job, "--usd", "1", "--", *PY)[0] == 2
    assert status_json(repo, monkeypatch, capsys, job)["usd"] == 0


@pytest.mark.ac("E16-AC-14")
def test_a_late_report_on_a_finished_job_is_still_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = factory_repo(tmp_path)
    job = submit(repo, monkeypatch, capsys, "--", *PY)
    start, clock = FakeStart(), Clock()
    daemon = make_daemon(repo, start)
    clock.tick(daemon)
    finish_current(start, job)
    clock.tick(daemon, 2)
    assert record(repo, job)["status"] == "succeeded"

    assert usage(repo, monkeypatch, capsys, job, "1.25") == 0
    data = status_json(repo, monkeypatch, capsys, job)
    assert data["usd"] == 1.25
    assert data["status"] == "succeeded", "a late report never changes how the job ended"


@pytest.mark.ac("E16-AC-14")
def test_20_concurrent_reports_of_25_cents_add_up_to_exactly_5_dollars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = factory_repo(tmp_path)
    job = submit(repo, monkeypatch, capsys, "--", *PY)
    reports = [
        subprocess.Popen(
            [sys.executable, str(RUN_PY), "usage", job, "--usd", "0.25"],
            cwd=repo,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        for _ in range(20)
    ]
    for report in reports:
        _, err = report.communicate(timeout=120)
        assert report.returncode == 0, err
    assert status_json(repo, monkeypatch, capsys, job)["usd"] == 5.0


# --- AC-14: the warning and the cost cap -------------------------------------------------------

BUDGET = config(budgets_per_job_usd=10, budgets_warn_at=0.5, budgets_halt_at=0.9)


def warnings_naming(data: dict[str, object], *words: str) -> list[str]:
    found = data["warnings"]
    assert isinstance(found, list)
    return [w for w in found if all(word in w for word in words)]


@pytest.mark.ac("E16-AC-14")
def test_one_warning_goes_into_the_record_at_warn_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = factory_repo(tmp_path, BUDGET)
    job = submit(repo, monkeypatch, capsys, "--", *PY)
    start, clock = FakeStart(), Clock()
    daemon = make_daemon(repo, start)
    clock.tick(daemon)

    assert usage(repo, monkeypatch, capsys, job, "4.99") == 0
    clock.tick(daemon)
    assert record(repo, job)["warnings"] == [], "below warn_at: no warning"
    assert usage(repo, monkeypatch, capsys, job, "0.01") == 0
    clock.tick(daemon)
    [warning] = record(repo, job)["warnings"]
    assert "$5.00" in warning, "it names the total"
    assert "$10.00" in warning, "and the cap"
    assert usage(repo, monkeypatch, capsys, job, "1") == 0
    clock.tick(daemon, 2)
    data = record(repo, job)
    assert len(data["warnings"]) == 1, "only the first time"
    assert data["status"] == "running"
    assert data["usd"] == 6.0


@pytest.mark.ac("E16-AC-14")
def test_reports_made_while_queued_warn_once_the_job_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = factory_repo(tmp_path, BUDGET)
    job = submit(repo, monkeypatch, capsys, "--", *PY)
    assert usage(repo, monkeypatch, capsys, job, "6") == 0
    daemon, clock = make_daemon(repo, FakeStart()), Clock()
    clock.tick(daemon, 2)
    data = record(repo, job)
    assert len(warnings_naming(data, "$6.00", "$10.00")) == 1
    assert data["status"] == "running"


@pytest.mark.ac("E16-AC-14")
def test_the_cost_cap_halts_a_running_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = factory_repo(tmp_path, BUDGET)
    job = submit(repo, monkeypatch, capsys, "--", *PY)
    start, clock = FakeStart(), Clock()
    daemon = make_daemon(repo, start)
    clock.tick(daemon)

    assert usage(repo, monkeypatch, capsys, job, "8.99") == 0
    clock.tick(daemon)
    assert record(repo, job)["status"] == "running", "just below the cap"
    assert usage(repo, monkeypatch, capsys, job, "0.01") == 0
    clock.tick(daemon)

    data = record(repo, job)
    assert data["status"] == "halted"
    assert data["reason"] == "cost cap ($9.00)"
    assert data["usd"] == 9.0
    assert start.for_job(job)[0].proc.killed, "the running command is killed"
    assert Path(data["worktree"]).is_dir()
    assert len(handoffs(Path(data["worktree"]), job)) == 1


@pytest.mark.ac("E16-AC-14")
def test_a_queued_job_over_the_cost_cap_runs_no_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = factory_repo(tmp_path, BUDGET)
    job = submit(repo, monkeypatch, capsys, "--", *PY)
    assert usage(repo, monkeypatch, capsys, job, "9") == 0
    start, clock = FakeStart(), Clock()
    daemon = make_daemon(repo, start)
    clock.tick(daemon, 2)
    data = record(repo, job)
    assert data["status"] == "halted"
    assert data["reason"] == "cost cap ($9.00)"
    assert start.for_job(job) == []


# --- AC-15: time -------------------------------------------------------------------------------


def started_at(repo: Path, job: str) -> dt.datetime:
    value = record(repo, job)["started"]
    assert isinstance(value, dt.datetime)
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


@pytest.mark.ac("E16-AC-15")
def test_the_time_cap_halts_a_running_command_at_job_timeout_minutes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = factory_repo(tmp_path, config(runner_job_timeout_minutes=1))
    job = submit(repo, monkeypatch, capsys, "--", *PY)
    start = FakeStart()
    daemon = make_daemon(repo, start)
    daemon.tick(T0)
    began = started_at(repo, job)

    daemon.tick(began + dt.timedelta(seconds=59.9))
    assert record(repo, job)["status"] == "running"
    daemon.tick(began + dt.timedelta(seconds=60))
    data = record(repo, job)
    assert data["status"] == "halted"
    assert data["reason"] == "time cap (1 min)"
    assert start.for_job(job)[0].proc.killed
    assert len(handoffs(Path(data["worktree"]), job)) == 1


@pytest.mark.ac("E16-AC-15")
def test_time_spent_waiting_for_commands_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = factory_repo(tmp_path, config(runner_job_timeout_minutes=0.5))
    job = submit(repo, monkeypatch, capsys, "--open")
    daemon = make_daemon(repo, FakeStart())
    daemon.tick(T0)
    began = started_at(repo, job)
    daemon.tick(began + dt.timedelta(seconds=29))
    assert record(repo, job)["status"] == "running"
    daemon.tick(began + dt.timedelta(seconds=30))
    data = record(repo, job)
    assert data["status"] == "halted"
    assert data["reason"] == "time cap (0.5 min)"


@pytest.mark.ac("E16-AC-15")
def test_the_time_cap_counts_from_the_start_not_the_submit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = factory_repo(tmp_path, config(runner_job_timeout_minutes=1, runner_max_parallel=1))
    first = submit(repo, monkeypatch, capsys, "--", *PY)
    second = submit(repo, monkeypatch, capsys, "--", *PY)
    start = FakeStart()
    daemon = make_daemon(repo, start)
    daemon.tick(T0)
    start.for_job(first)[0].proc.finish(0)
    later = T0 + dt.timedelta(seconds=50)
    daemon.tick(later)
    daemon.tick(later + dt.timedelta(seconds=1))
    assert record(repo, second)["status"] == "running"
    began = started_at(repo, second)
    daemon.tick(began + dt.timedelta(seconds=59))
    assert record(repo, second)["status"] == "running", "time queued doesn't count"
    daemon.tick(began + dt.timedelta(seconds=60))
    assert record(repo, second)["reason"] == "time cap (1 min)"
