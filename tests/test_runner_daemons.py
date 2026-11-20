"""E16/T2: `run.py --daemon` as real processes, and the worktree done-when test.

Covers E16 AC-06 (pickup within 2 seconds), AC-08 (two daemon processes on one queue) and
AC-12. Expectations come from the E16 spec and the design note ("Test seams"), not from the
implementation. These start real daemons, so they are marked slow.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests._daemon import branch_exists, record, start_daemon, stop_daemon, until
from tests._runner import call, factory_dir, job_dir, real, runner_repo, submit

pytestmark = pytest.mark.slow

# Appends one JSON line per run to <out>/<job>.txt, so a job that ran twice shows two lines.
SCRIPT = (
    "import json, os, sys, time; s = time.time(); time.sleep(float(sys.argv[2])); "
    "f = open(os.path.join(sys.argv[1], os.environ['FACTORY_JOB'] + '.txt'), 'a'); "
    "f.write(json.dumps({'cwd': os.getcwd(), 'start': s, 'end': time.time()}) + '\\n'); "
    "f.close()"
)


@pytest.fixture
def daemons(tmp_path: Path) -> Iterator[list[Any]]:
    started: list[Any] = []
    yield started
    for process in started:
        stop_daemon(process)


def finished(repo: Path, job: str) -> bool:
    path = job_dir(repo, job) / "job.toml"
    return path.is_file() and record(repo, job)["status"] in ("succeeded", "failed", "halted")


def most_at_once(spans: list[tuple[float, float]]) -> int:
    events = sorted([(s, 1) for s, _ in spans] + [(e, -1) for _, e in spans])
    now = peak = 0
    for _, step in events:
        now += step
        peak = max(peak, now)
    return peak


@pytest.mark.ac("E16-AC-06")
def test_the_daemon_picks_up_a_request_and_a_command_within_2_seconds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    daemons: list[Any],
) -> None:
    repo = runner_repo(tmp_path)
    daemons.append(start_daemon(repo, tmp_path / "logs"))
    time.sleep(1.0)  # let the interpreter start, so only the pickup is timed
    job = submit(repo, monkeypatch, capsys, "--open")
    written = time.monotonic()
    queued = factory_dir(repo) / "queue" / f"{job}.toml"
    assert until(lambda: not queued.exists(), timeout=10)
    assert time.monotonic() - written < 2.0
    assert until(lambda: (job_dir(repo, job) / "job.toml").is_file(), timeout=20)

    code, _, err = call(repo, monkeypatch, capsys, "send", job, "--", sys.executable, "-V")
    assert code == 0, err
    sent = time.monotonic()
    log = job_dir(repo, job) / "logs" / "0001.log"
    assert until(log.exists, timeout=10)
    assert time.monotonic() - sent < 2.0


@pytest.mark.ac("E16-AC-08")
@pytest.mark.ac("E16-AC-12")
def test_parallel_jobs_never_share_a_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    daemons: list[Any],
) -> None:
    """Done-when: 8 jobs, two daemons with max_parallel = 2 on one queue."""
    repo = runner_repo(tmp_path, "[runner]\nmax_parallel = 2\n")
    out = tmp_path / "out"
    out.mkdir()
    daemons.append(start_daemon(repo, tmp_path / "logs"))
    jobs = [
        submit(repo, monkeypatch, capsys, "--", sys.executable, "-c", SCRIPT, str(out), "1.0")
        for _ in range(6)
    ]
    daemons.append(start_daemon(repo, tmp_path / "logs"))
    jobs += [
        submit(repo, monkeypatch, capsys, "--", sys.executable, "-c", SCRIPT, str(out), "1.0")
        for _ in range(2)
    ]
    assert until(lambda: all(finished(repo, j) for j in jobs), timeout=180, step=0.2)

    records = {job: record(repo, job) for job in jobs}
    assert {r["status"] for r in records.values()} == {"succeeded"}
    worktrees = [real(r["worktree"]) for r in records.values()]
    assert len(set(worktrees)) == len(jobs), "no two jobs share a worktree path"
    spans: dict[str, list[tuple[float, float]]] = {}
    for job, data in records.items():
        lines = (out / f"{job}.txt").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1, f"{job} ran {len(lines)} times"
        ran = json.loads(lines[0])
        assert real(ran["cwd"]) == real(data["worktree"])
        assert branch_exists(repo, f"factory/{job}")
        spans.setdefault(data["daemon"], []).append((ran["start"], ran["end"]))
    assert len(spans) <= 2
    for daemon, ran_here in spans.items():
        assert most_at_once(ran_here) <= 2, f"daemon {daemon} ran more than max_parallel"
