"""E16/T4: the caps done-when test, with a real `run.py --daemon` and real commands.

Covers E16 AC-18 (and AC-14's and AC-15's "within 2 seconds, even while a command is running").
Expectations come from the E16 spec and the design note ("Test seams"), not from the
implementation. One job is halted by each cap. Each must end `halted` with its reason, leave no
process running, keep its worktree, and have a handoff there that `state.py check` accepts.
These start real daemons, so they are marked slow.
"""

from __future__ import annotations

import datetime as dt
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests._daemon import record, start_daemon, stop_daemon, until
from tests._halt import (
    alive,
    all_gone,
    factory_repo,
    handoffs,
    read_pids,
    reap,
    state_py,
    tree_argv,
)
from tests._runner import call, job_dir, submit

pytestmark = pytest.mark.slow

PY = [sys.executable, "-c", "pass"]


@pytest.fixture
def daemons() -> Iterator[list[subprocess.Popen[bytes]]]:
    started: list[subprocess.Popen[bytes]] = []
    yield started
    for process in started:
        if process.poll() is None:
            stop_daemon(process)


@pytest.fixture
def leftovers() -> Iterator[list[int]]:
    pids: list[int] = []
    yield pids
    reap(pids)


def halted(repo: Path, job: str) -> bool:
    path = job_dir(repo, job) / "job.toml"
    return path.is_file() and record(repo, job)["status"] == "halted"


def check_halt(repo: Path, job: str, reason: str) -> dict[str, Any]:
    """Halted with its reason, its worktree kept, and a handoff there that state.py accepts."""
    data = record(repo, job)
    assert data["status"] == "halted"
    assert data["reason"] == reason
    worktree = Path(data["worktree"])
    assert worktree.is_dir(), "the worktree is kept"
    assert until(lambda: len(handoffs(worktree, job)) == 1, timeout=30)
    checked = state_py(worktree, "check")
    assert checked.returncode == 0, checked.stdout + checked.stderr
    return data


def aware(value: object) -> dt.datetime:
    assert isinstance(value, dt.datetime)
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


@pytest.mark.ac("E16-AC-18", "E16-AC-13")
def test_the_turn_cap_halts_a_real_job_after_3_of_its_4_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    daemons: list[Any],
) -> None:
    repo = factory_repo(tmp_path, "[runner]\nmax_turns = 3\n")
    marks = tmp_path / "marks"
    marks.mkdir()
    script = "import os, sys; open(os.path.join(sys.argv[1], sys.argv[2]), 'w').close()"
    job = submit(repo, monkeypatch, capsys, "--open")
    for n in range(1, 5):
        code, _, err = call(
            repo,
            monkeypatch,
            capsys,
            "send",
            job,
            "--",
            sys.executable,
            "-c",
            script,
            str(marks),
            str(n),
        )
        assert code == 0, err
    daemons.append(start_daemon(repo, tmp_path / "logs"))

    assert until(lambda: halted(repo, job), timeout=60)
    data = check_halt(repo, job, "turn cap (3)")
    assert data["turns"] == 3
    assert sorted(p.name for p in marks.iterdir()) == ["1", "2", "3"], "the fourth never ran"


@pytest.mark.ac("E16-AC-18", "E16-AC-14")
def test_the_cost_cap_halts_a_real_running_command_within_2_seconds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    daemons: list[Any],
    leftovers: list[int],
) -> None:
    repo = factory_repo(tmp_path, "[budgets]\nper_job_usd = 2\nwarn_at = 0.5\nhalt_at = 1.0\n")
    pid_dir = tmp_path / "pids"
    job = submit(repo, monkeypatch, capsys, "--", *tree_argv(pid_dir, orphan=True))
    daemons.append(start_daemon(repo, tmp_path / "logs"))
    pids = read_pids(pid_dir)
    leftovers.extend(pids.values())
    assert until(lambda: not alive(pids["child"]), timeout=30)

    assert call(repo, monkeypatch, capsys, "usage", job, "--usd", "1")[0] == 0
    time.sleep(1.0)
    assert not halted(repo, job), "half the budget only warns"
    assert call(repo, monkeypatch, capsys, "usage", job, "--usd", "1")[0] == 0
    reported = time.monotonic()
    assert until(lambda: halted(repo, job), timeout=30)
    assert time.monotonic() - reported < 2.0

    assert all_gone([pids["command"], pids["grandchild"]])
    data = check_halt(repo, job, "cost cap ($2.00)")
    assert [w for w in data["warnings"] if "$1.00" in w and "$2.00" in w], data["warnings"]


@pytest.mark.ac("E16-AC-18", "E16-AC-15")
def test_the_time_cap_halts_a_real_running_command_within_2_seconds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    daemons: list[Any],
    leftovers: list[int],
) -> None:
    repo = factory_repo(tmp_path, "[runner]\njob_timeout_minutes = 0.05\n")  # 3 seconds
    pid_dir = tmp_path / "pids"
    job = submit(repo, monkeypatch, capsys, "--", *tree_argv(pid_dir, orphan=True))
    daemons.append(start_daemon(repo, tmp_path / "logs"))
    pids = read_pids(pid_dir)
    leftovers.extend(pids.values())

    assert until(lambda: halted(repo, job), timeout=60)
    assert all_gone(pids.values())
    data = check_halt(repo, job, "time cap (0.05 min)")
    ran_for = (aware(data["finished"]) - aware(data["started"])).total_seconds()
    assert 3.0 <= ran_for < 5.0, ran_for
