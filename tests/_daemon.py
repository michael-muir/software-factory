"""Helpers for the E16 daemon tests: a fake process starter, a clock, and hand-dropped requests.

The seams come from the E16 design note ("Test seams"): `Daemon(repo, config, start=...)` and
`Daemon.tick(now)`, with a starter called as `start(argv, cwd, env, log)` that returns an object
with `poll()` and `kill()`.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import run as runner
from tests._runner import RUN_PY, factory_dir, job_dir, read_toml

T0 = dt.datetime(2026, 11, 19, 21, 30, 0, tzinfo=dt.UTC)


class FakeProc:
    """A command that runs until the test calls finish()."""

    def __init__(self) -> None:
        self.code: int | None = None
        self.killed = False

    def finish(self, code: int = 0) -> None:
        self.code = code

    def poll(self) -> int | None:
        return self.code

    def kill(self) -> None:
        self.killed = True
        if self.code is None:
            self.code = -9


@dataclass
class Call:
    argv: list[str]
    cwd: Path
    env: dict[str, str]
    log: Path
    proc: FakeProc


@dataclass
class FakeStart:
    calls: list[Call] = field(default_factory=list)

    def __call__(self, argv: list[str], cwd: Path, env: Mapping[str, str], log: Path) -> FakeProc:
        proc = FakeProc()
        self.calls.append(Call(list(argv), Path(cwd), dict(env), Path(log), proc))
        return proc

    def for_job(self, job: str) -> list[Call]:
        return [c for c in self.calls if c.env.get("FACTORY_JOB") == job]


class Clock:
    """Moves on a second each tick, so records get distinct, known times."""

    def __init__(self) -> None:
        self.now = T0

    def tick(self, daemon: runner.Daemon, times: int = 1) -> None:
        for _ in range(times):
            self.now += dt.timedelta(seconds=1)
            daemon.tick(self.now)


def make_daemon(repo: Path, start: Any = None) -> runner.Daemon:
    found = runner.find_repo(repo)
    config = runner.load_config(found.main)
    if start is None:
        return runner.Daemon(found, config)
    return runner.Daemon(found, config, start=start)


def record(repo: Path, job: str) -> dict[str, Any]:
    path = job_dir(repo, job) / "job.toml"
    assert path.is_file(), f"no record for {job}"
    return read_toml(path)


def drop(repo: Path, name: str, text: str) -> Path:
    """A request dropped into the queue by hand, as AC-05 allows for."""
    queue = factory_dir(repo) / "queue"
    queue.mkdir(parents=True, exist_ok=True)
    path = queue / name
    path.write_text(text, encoding="utf-8")
    return path


def claims(repo: Path) -> list[Path]:
    folder = factory_dir(repo) / "claims"
    return sorted(folder.iterdir()) if folder.is_dir() else []


def claim_key(path: str | Path) -> str:
    """ADR 0030: the SHA-256 of the case-folded, resolved absolute path."""
    return hashlib.sha256(os.path.realpath(path).casefold().encode("utf-8")).hexdigest()


def branch_exists(repo: Path, branch: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "-q", f"refs/heads/{branch}"],
        cwd=repo,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def until(check: Callable[[], bool], timeout: float, step: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(step)
    return check()


def tick_until(
    daemon: runner.Daemon, clock: Clock, check: Callable[[], bool], timeout: float = 60
) -> bool:
    """Tick with the real clock's pace until check() holds; for tests with real commands."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        clock.tick(daemon)
        if check():
            return True
        time.sleep(0.05)
    return check()


def start_daemon(repo: Path, logs: Path) -> subprocess.Popen[bytes]:
    """`run.py --daemon` as a real process, in the foreground of its own console."""
    logs.mkdir(parents=True, exist_ok=True)
    out = open(logs / f"daemon-{time.monotonic_ns()}.log", "wb")  # noqa: SIM115
    try:
        return subprocess.Popen(
            [sys.executable, str(RUN_PY), "--daemon"],
            cwd=repo,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
        )
    finally:
        out.close()


def stop_daemon(process: subprocess.Popen[bytes]) -> None:
    process.kill()
    process.wait(timeout=30)
