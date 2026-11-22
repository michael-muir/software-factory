"""E18/T3: the runner keeps the index current, renews leases, and sends daemon heartbeats.

Covers E18 AC-06 (run.py's writes reach the index at once; a failure is only a warning), AC-13
(lease renewal while a command runs) and AC-14 (daemon heartbeats, dead daemons, stale runner
jobs). Expectations come from the E18 spec and the design note ("The runner hooks", ADRs 0052 and
0053), not from the implementation.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

import jobs
from tests._daemon import Clock, FakeStart, make_daemon, record, tick_until
from tests._jobs import JOBS_PY, api_repo, call, index_path, jobs_repo, new
from tests._jobs_index import by_id, listing, run_py, runner_status, set_user_version, submit
from tests._runner import RUN_PY

PY = sys.executable


def cached(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], job: str
) -> dict[str, Any]:
    """The runner job as the index holds it, without re-reading any file."""
    found = by_id(listing(repo, monkeypatch, capsys, "--cached")["runner_jobs"])
    assert job in found, sorted(found)
    view = dict(found[job])
    view.pop("belongs_to")
    return view


def seconds(when: dt.datetime) -> float:
    return when.timestamp()


# --- AC-06: run.py's writes reach the index at once -------------------------------------------


@pytest.mark.ac("E18-AC-06")
def test_each_run_py_command_updates_the_index_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    assert call(repo, monkeypatch, capsys, "list")[0] == 0  # the index exists, and is current
    one = submit(repo, monkeypatch, capsys, "--task", "E31-T1", "--", PY, "-c", "pass")
    assert cached(repo, monkeypatch, capsys, one) == runner_status(repo, monkeypatch, capsys, one)
    opened = submit(repo, monkeypatch, capsys, "--open")
    steps = [
        ("send", opened, "--", PY, "-c", "print(1)"),
        ("close", opened),
        ("usage", opened, "--usd", "0.40"),
        ("cancel", opened),
    ]
    for step in steps:
        code, _, err = run_py(repo, monkeypatch, capsys, *step)
        assert code == 0, err
        expected = runner_status(repo, monkeypatch, capsys, opened)
        assert cached(repo, monkeypatch, capsys, opened) == expected, step[0]
    assert cached(repo, monkeypatch, capsys, opened)["status"] == "halted"


@pytest.mark.ac("E18-AC-06")
def test_the_daemon_updates_the_index_on_every_record_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    job = submit(repo, monkeypatch, capsys, "--", PY, "-c", "pass")
    start, clock = FakeStart(), Clock()
    daemon = make_daemon(repo, start)
    clock.tick(daemon, 2)
    running = cached(repo, monkeypatch, capsys, job)
    assert running["status"] == "running"
    assert running == runner_status(repo, monkeypatch, capsys, job)
    start.for_job(job)[0].proc.finish(0)
    clock.tick(daemon, 2)
    done = cached(repo, monkeypatch, capsys, job)
    assert done["status"] == "succeeded"
    assert done == runner_status(repo, monkeypatch, capsys, job)


@pytest.mark.ac("E18-AC-06")
def test_an_index_failure_is_one_warning_and_the_job_still_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    assert call(repo, monkeypatch, capsys, "list")[0] == 0
    set_user_version(repo, 99)  # an index this kit refuses to touch
    code, out, err = run_py(repo, monkeypatch, capsys, "submit", "--", PY, "-c", "pass")
    assert code == 0
    assert "index:" in err
    job = out.strip()
    start, clock = FakeStart(), Clock()
    daemon = make_daemon(repo, start)
    clock.tick(daemon, 3)
    start.for_job(job)[0].proc.finish(0)
    clock.tick(daemon, 3)
    data = record(repo, job)
    assert data["status"] == "succeeded"
    index_warnings = [w for w in data["warnings"] if w.startswith("index:")]
    assert len(index_warnings) == 1, data["warnings"]


def kit_copy(tmp_path: Path, jobs_text: str | None) -> Path:
    """A copy of the kit's run.py, with a jobs.py beside it (or none), as another install."""
    runner_dir = tmp_path / "kit" / ".factory" / "runner"
    runner_dir.mkdir(parents=True)
    shutil.copy2(RUN_PY, runner_dir / "run.py")
    if jobs_text is not None:
        control = tmp_path / "kit" / ".factory" / "control"
        control.mkdir(parents=True)
        (control / "jobs.py").write_text(jobs_text, encoding="utf-8")
    return runner_dir / "run.py"


@pytest.mark.ac("E18-AC-06")
def test_without_jobs_py_the_runner_works_as_before_and_writes_no_index(tmp_path: Path) -> None:
    repo = jobs_repo(tmp_path)
    run = kit_copy(tmp_path, None)
    made = subprocess.run(
        [PY, str(run), "submit", "--", PY, "-c", "pass"], cwd=repo, capture_output=True, text=True
    )
    assert made.returncode == 0, made.stderr
    job = made.stdout.strip()
    used = subprocess.run(
        [PY, str(run), "usage", job, "--usd", "1"], cwd=repo, capture_output=True, text=True
    )
    assert used.returncode == 0, used.stderr
    assert made.stderr == used.stderr == ""
    assert not index_path(repo).exists()


@pytest.mark.ac("E18-AC-06")
def test_a_jobs_py_that_fails_to_load_is_a_warning_not_a_failure(tmp_path: Path) -> None:
    repo = jobs_repo(tmp_path)
    run = kit_copy(tmp_path, "raise RuntimeError('this install is broken')\n")
    made = subprocess.run(
        [PY, str(run), "submit", "--", PY, "-c", "pass"], cwd=repo, capture_output=True, text=True
    )
    assert made.returncode == 0, made.stderr
    assert "index:" in made.stderr
    assert "this install is broken" in made.stderr


# --- AC-13: the runner renews the lease while a command runs ----------------------------------


def leased_job(repo: Path, task: str, at: float, *, session: str = "s-a") -> tuple[jobs.Repo, str]:
    found = api_repo(repo)
    job = jobs.new_job(found, "Leased", task=task, now=at)["id"]
    jobs.claim(found, jobs.load_config(found), job, session, now=at)
    return found, job


@pytest.mark.ac("E18-AC-13")
def test_a_running_command_keeps_its_jobs_lease_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path, "[jobs]\nlease_minutes = 0.05\n")  # 3 seconds
    clock = Clock()
    found, job = leased_job(repo, "E31-T1", seconds(clock.now))
    runner_job = submit(repo, monkeypatch, capsys, "--task", "E31-T1", "--", PY, "-c", "pass")
    start = FakeStart()
    daemon = make_daemon(repo, start)
    clock.tick(daemon, 10)  # 10 seconds of a command that hasn't finished
    assert start.for_job(runner_job), "the command started"
    assert jobs.lease_state(found, job, now=seconds(clock.now)) == "claimed"
    start.for_job(runner_job)[0].proc.finish(0)
    clock.tick(daemon, 2)
    assert record(repo, runner_job)["status"] == "succeeded"
    assert jobs.lease_state(found, job, now=seconds(clock.now) + 4) == "crashed", (
        "with no command running, nothing renews the lease"
    )


@pytest.mark.ac("E18-AC-13")
def test_an_expired_lease_is_never_revived_by_the_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path, "[jobs]\nlease_minutes = 0.05\n")
    clock = Clock()
    found, job = leased_job(repo, "E31-T1", seconds(clock.now) - 60)
    runner_job = submit(repo, monkeypatch, capsys, "--task", "E31-T1", "--", PY, "-c", "pass")
    start = FakeStart()
    daemon = make_daemon(repo, start)
    clock.tick(daemon, 5)
    assert start.for_job(runner_job)
    assert jobs.lease_state(found, job, now=seconds(clock.now)) == "crashed"


@pytest.mark.ac("E18-AC-13")
def test_only_the_job_the_runner_job_belongs_to_is_renewed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path, "[jobs]\nlease_minutes = 0.05\n")
    clock = Clock()
    found, mine = leased_job(repo, "E31-T1", seconds(clock.now))
    _, other = leased_job(repo, "E31-T2", seconds(clock.now), session="s-b")
    submit(repo, monkeypatch, capsys, "--task", "E31-T1", "--", PY, "-c", "pass")
    daemon = make_daemon(repo, FakeStart())
    clock.tick(daemon, 8)
    assert jobs.lease_state(found, mine, now=seconds(clock.now)) == "claimed"
    assert jobs.lease_state(found, other, now=seconds(clock.now)) == "crashed"


@pytest.mark.ac("E18-AC-13")
@pytest.mark.slow
def test_a_real_command_longer_than_the_lease_keeps_it_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path, "[jobs]\nlease_minutes = 0.05\n")  # 3 seconds
    found, job = leased_job(repo, "E31-T1", time.time())
    script = "import time; time.sleep(6)"
    runner_job = submit(repo, monkeypatch, capsys, "--task", "E31-T1", "--", PY, "-c", script)
    daemon = make_daemon(repo)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        daemon.tick(dt.datetime.now(dt.UTC))
        time.sleep(0.2)
    assert jobs.lease_state(found, job) == "claimed"

    def finished() -> bool:
        return bool(record(repo, runner_job)["status"] == "succeeded")

    assert tick_until(daemon, RealClock(), finished, timeout=60)


class RealClock(Clock):
    def tick(self, daemon: Any, times: int = 1) -> None:
        for _ in range(times):
            daemon.tick(dt.datetime.now(dt.UTC))
            time.sleep(0.2)


# --- AC-14: daemon heartbeats, dead daemons and stale runner jobs ------------------------------


@pytest.mark.ac("E18-AC-14")
def test_a_daemon_beats_when_it_starts_and_every_second(tmp_path: Path) -> None:
    repo = jobs_repo(tmp_path)
    found = api_repo(repo)
    clock = Clock()
    daemon = make_daemon(repo, FakeStart())
    clock.tick(daemon)
    [entry] = jobs.daemons(found, now=seconds(clock.now))
    assert entry["id"] == daemon.name
    assert entry["host"] == socket.gethostname()
    assert entry["pid"] == os.getpid()
    assert entry["state"] == "alive"
    first = dt.datetime.fromisoformat(entry["beat"]).timestamp()
    assert first == pytest.approx(seconds(clock.now))
    clock.tick(daemon, 5)
    [entry] = jobs.daemons(found, now=seconds(clock.now))
    latest = dt.datetime.fromisoformat(entry["beat"]).timestamp()
    assert seconds(clock.now) - latest <= 2
    assert dt.datetime.fromisoformat(entry["started"]).timestamp() == pytest.approx(first)


@pytest.mark.ac("E18-AC-14")
def test_a_daemon_is_dead_after_daemon_timeout_seconds(tmp_path: Path) -> None:
    repo = jobs_repo(tmp_path, "[jobs]\ndaemon_timeout_seconds = 5\n")
    found = api_repo(repo)
    clock = Clock()
    daemon = make_daemon(repo, FakeStart())
    clock.tick(daemon)
    beat = seconds(clock.now)
    assert jobs.daemons(found, now=beat + 5)[0]["state"] == "alive"
    assert jobs.daemons(found, now=beat + 6)[0]["state"] == "dead"


@pytest.mark.ac("E18-AC-14")
def test_a_dead_daemons_running_jobs_are_stale_and_their_files_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path, "[jobs]\ndaemon_timeout_seconds = 5\n")
    found = api_repo(repo)
    job = new(repo, monkeypatch, capsys, "Owner", "--task", "E31-T1")
    runner_job = submit(repo, monkeypatch, capsys, "--task", "E31-T1", "--", PY, "-c", "pass")
    clock = Clock()
    daemon = make_daemon(repo, FakeStart())
    clock.tick(daemon, 2)
    beat = seconds(clock.now)
    record_file = record(repo, runner_job)
    assert record_file["status"] == "running"
    alive = jobs.index_listing(found, now=beat + 1)
    assert by_id(alive["jobs"])[job]["stale"] is False
    [entry] = jobs.daemons(found, now=beat + 1)
    assert entry["stale_runner_jobs"] == []
    [entry] = jobs.daemons(found, now=beat + 6)
    assert (entry["state"], entry["stale_runner_jobs"]) == ("dead", [runner_job])
    dead = jobs.index_listing(found, now=beat + 6)
    assert by_id(dead["jobs"])[job]["stale"] is True
    assert record(repo, runner_job) == record_file, "E18 never changes the runner's files"
    code, out, err = call(repo, monkeypatch, capsys, "list")
    assert code == 0, err
    assert ",stale" in next(line for line in out.splitlines() if line.startswith(job))


@pytest.mark.ac("E18-AC-14")
def test_a_running_runner_job_with_no_heartbeat_at_all_is_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    found = api_repo(repo)
    runner_job = submit(repo, monkeypatch, capsys, "--", PY, "-c", "pass")
    clock = Clock()
    daemon = make_daemon(repo, FakeStart())
    clock.tick(daemon, 2)
    index_path(repo).unlink()  # the heartbeats are lost with the index
    assert call(repo, monkeypatch, capsys, "rebuild")[0] == 0
    [entry] = jobs.daemons(found, now=seconds(clock.now))
    assert entry["id"] == daemon.name
    assert (entry["beat"], entry["state"]) == (None, "dead")
    assert entry["stale_runner_jobs"] == [runner_job]


@pytest.mark.ac("E18-AC-14")
def test_daemons_on_the_command_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    runner_job = submit(repo, monkeypatch, capsys, "--", PY, "-c", "pass")
    daemon = make_daemon(repo, FakeStart())
    Clock().tick(daemon, 2)  # the fake clock is in the past, so the daemon is long dead
    code, out, err = call(repo, monkeypatch, capsys, "daemons", "--json")
    assert code == 0, err
    [entry] = json.loads(out)
    assert (entry["id"], entry["state"], entry["stale_runner_jobs"]) == (
        daemon.name,
        "dead",
        [runner_job],
    )
    code, out, err = call(repo, monkeypatch, capsys, "daemons")
    assert code == 0, err
    assert daemon.name in out
    assert "dead" in out
    assert runner_job in out


@pytest.mark.ac("E18-AC-14")
@pytest.mark.slow
def test_a_real_daemon_is_alive_while_it_runs_and_dead_once_killed(tmp_path: Path) -> None:
    repo = jobs_repo(tmp_path, "[jobs]\ndaemon_timeout_seconds = 5\n")
    opened = subprocess.run(
        [PY, str(RUN_PY), "submit", "--open"], cwd=repo, capture_output=True, text=True
    )
    assert opened.returncode == 0, opened.stderr
    runner_job = opened.stdout.strip()
    proc = subprocess.Popen(
        [PY, str(RUN_PY), "--daemon"],
        cwd=repo,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    def listed() -> list[dict[str, Any]]:
        result = subprocess.run(
            [PY, str(JOBS_PY), "daemons", "--json"], cwd=repo, capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr
        found: list[dict[str, Any]] = json.loads(result.stdout)
        return found

    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            found = listed()
            if found and found[0]["state"] == "alive":
                break
            time.sleep(0.5)
        assert [d["state"] for d in found] == ["alive"]
        assert found[0]["pid"] == proc.pid
    finally:
        proc.kill()
        proc.wait(timeout=30)
    time.sleep(7)
    [entry] = listed()
    assert entry["state"] == "dead"
    assert entry["stale_runner_jobs"] == [runner_job]
