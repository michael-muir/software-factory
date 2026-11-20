"""E16/T3: halting jobs of a real `run.py --daemon` process, with real process trees.

Covers E16 AC-07, AC-16 and AC-17 end to end. Expectations come from the E16 spec, ADR 0031
and the design note ("Test seams"), not from the implementation. These start real daemons, so
they are marked slow. They run on every OS except the Ctrl+C test: a console Ctrl+C can't be
sent to one process on Windows, which is why `stop` exists (spec assumption 3).
"""

from __future__ import annotations

import signal
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests._daemon import record, start_daemon, stop_daemon, until
from tests._halt import (
    GONE_S,
    alive,
    all_gone,
    factory_repo,
    handoffs,
    read_pids,
    reap,
    state_py,
    tree_argv,
)
from tests._runner import call, job_dir, queue_file, submit

pytestmark = pytest.mark.slow


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


def status_is(repo: Path, job: str, *wanted: str) -> bool:
    path = job_dir(repo, job) / "job.toml"
    return path.is_file() and record(repo, job)["status"] in wanted


def tree_job(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    name: str,
    *,
    orphan: bool,
) -> tuple[str, Path]:
    pids = tmp_path / "pids" / name
    return submit(repo, monkeypatch, capsys, "--", *tree_argv(pids, orphan=orphan)), pids


@pytest.mark.ac("E16-AC-16", "E16-AC-17")
def test_cancel_kills_a_real_jobs_tree_with_an_orphan_within_10_seconds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    daemons: list[Any],
    leftovers: list[int],
) -> None:
    repo = factory_repo(tmp_path)
    job, pid_dir = tree_job(repo, tmp_path, monkeypatch, capsys, "orphan", orphan=True)
    daemons.append(start_daemon(repo, tmp_path / "logs"))
    pids = read_pids(pid_dir)
    leftovers.extend(pids.values())
    assert until(lambda: not alive(pids["child"]), timeout=30)
    assert alive(pids["grandchild"])

    code, _, err = call(repo, monkeypatch, capsys, "cancel", job)
    assert code == 0, err
    assert all_gone([pids["command"], pids["grandchild"]], timeout=GONE_S + 2), {
        role: alive(pid) for role, pid in pids.items()
    }
    assert until(lambda: status_is(repo, job, "halted"), timeout=30)
    data = record(repo, job)
    assert data["reason"] == "cancelled"
    assert data["warnings"] == [], "the tree was killed without a fallback"
    worktree = Path(data["worktree"])
    assert worktree.is_dir()
    assert len(handoffs(worktree, job)) == 1
    checked = state_py(worktree, "check")
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert daemons[0].poll() is None, "the daemon carries on"


@pytest.mark.ac("E16-AC-07", "E16-AC-17")
def test_stop_halts_a_real_daemons_jobs_and_it_exits_0(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    daemons: list[Any],
    leftovers: list[int],
) -> None:
    repo = factory_repo(tmp_path, "[runner]\nmax_parallel = 1\n")
    job, pid_dir = tree_job(repo, tmp_path, monkeypatch, capsys, "tree", orphan=False)
    queued = submit(repo, monkeypatch, capsys, "--", sys.executable, "-c", "pass")
    daemon = start_daemon(repo, tmp_path / "logs")
    daemons.append(daemon)
    pids = read_pids(pid_dir)
    leftovers.extend(pids.values())

    code, _, err = call(repo, monkeypatch, capsys, "stop")
    assert code == 0, err
    assert daemon.wait(timeout=30) == 0
    assert all_gone(pids.values()), {role: alive(pid) for role, pid in pids.items()}
    data = record(repo, job)
    assert data["status"] == "halted"
    assert data["reason"] == "daemon stopped"
    assert len(handoffs(Path(data["worktree"]), job)) == 1
    assert queue_file(repo, queued).exists(), "the queued job waits for the next daemon"


@pytest.mark.ac("E16-AC-07")
@pytest.mark.skipif(sys.platform == "win32", reason="Ctrl+C can't be sent to one process here")
def test_ctrl_c_halts_a_real_daemons_jobs_and_it_exits_0(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    daemons: list[Any],
    leftovers: list[int],
) -> None:
    repo = factory_repo(tmp_path)
    job, pid_dir = tree_job(repo, tmp_path, monkeypatch, capsys, "tree", orphan=True)
    daemon = start_daemon(repo, tmp_path / "logs")
    daemons.append(daemon)
    pids = read_pids(pid_dir)
    leftovers.extend(pids.values())
    assert until(lambda: not alive(pids["child"]), timeout=30)

    daemon.send_signal(signal.SIGINT)
    assert daemon.wait(timeout=30) == 0
    assert all_gone([pids["command"], pids["grandchild"]])
    data = record(repo, job)
    assert data["status"] == "halted"
    assert data["reason"] == "daemon stopped"
