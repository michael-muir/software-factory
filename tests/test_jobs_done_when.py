"""E18/T4, the done-when: any session resumes any job after a crash.

Covers E18 AC-17, with real processes on Ubuntu, macOS and Windows. Session A claims a job and
beats; a real runner daemon runs an open runner job for the job's task, which writes a handoff
with state.py and then waits. Both are killed without warning. A fresh process in another
worktree of the same repo sees the job claimed until the lease runs out, then crashed and stale,
and resumes it as session B. The index is then deleted and rebuilt, and B resumes again.
Expectations come from the E18 spec (AC-17) and the design note ("Test seams", "Done-when").

Nothing outlives the test: session A and the daemon are killed with `Popen.kill()` (on Windows
a venv's python.exe is a launcher, and killing it takes the real process with it), and the
waiting command, which on POSIX leads its own session and so outlives the daemon, stops when
the test writes its stop file, or after 10 minutes at most.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from tests._daemon import start_daemon
from tests._jobs import JOBS_PY, git, index_path
from tests._jobs_index import factory_repo, real
from tests._runner import RUN_PY

PY = sys.executable
TASK = "E31-T1"
SESSION_A = "session-a"
SESSION_B = "session-b"
LEASE_MINUTES = 0.5  # 30 seconds: room for slow CI machines to look while it's still live
NEXT = "Finish the crash test, then open the pull request."
MARK = "waiting-for-the-crash"

SESSION_A_SCRIPT = """
import importlib.util, pathlib, sys, time
spec = importlib.util.spec_from_file_location("jobs_of_session_a", sys.argv[1])
jobs = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = jobs
spec.loader.exec_module(jobs)
repo = jobs.find_repo(pathlib.Path.cwd())
config = jobs.load_config(repo)
jobs.claim(repo, config, sys.argv[2], sys.argv[3])
pathlib.Path(sys.argv[4]).write_text("claimed", encoding="utf-8")
while True:
    time.sleep(0.5)
    jobs.beat(repo, config, sys.argv[2], sys.argv[3])
"""

# The runner job's second command: it waits, until the test's stop file appears.
WAITER = f"""
import os, pathlib, sys, time
# {MARK}
pathlib.Path(sys.argv[2]).write_text(str(os.getpid()), encoding="utf-8")
deadline = time.monotonic() + 600
try:
    while not pathlib.Path(sys.argv[1]).exists() and time.monotonic() < deadline:
        time.sleep(0.1)
finally:
    pathlib.Path(sys.argv[3]).write_text("exited", encoding="utf-8")
"""


def seconds(iso: str) -> float:
    return dt.datetime.fromisoformat(iso).timestamp()


def clean_env() -> dict[str, str]:
    """The environment of a fresh session: nothing of session A's, nor of the runner's."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("FACTORY_")}
    env["PYTHONUTF8"] = "1"
    return env


def jobs_py(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """A fresh `python jobs.py <args>`, in its own process."""
    return subprocess.run(
        [PY, str(JOBS_PY), *args],
        cwd=cwd,
        env=clean_env(),
        capture_output=True,
        encoding="utf-8",
        check=False,
        timeout=120,
    )


def run_py(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PY, str(RUN_PY), *args],
        cwd=cwd,
        env=clean_env(),
        capture_output=True,
        encoding="utf-8",
        check=False,
        timeout=120,
    )


def ok(result: subprocess.CompletedProcess[str]) -> str:
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def until(check: Callable[[], bool], timeout: float, step: float = 0.2) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(step)
    return check()


def read_text(path: Path) -> str:
    """A file another process may be replacing: on Windows, reading it then can fail briefly."""
    for _ in range(50):
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""
        except PermissionError:
            time.sleep(0.05)
    return path.read_text(encoding="utf-8")


def status(repo: Path, runner_job: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(ok(run_py(repo, "status", runner_job, "--json")))
    return data


def the_job(cwd: Path, job: str) -> dict[str, Any]:
    data = json.loads(ok(jobs_py(cwd, "list", "--json")))
    [found] = [j for j in data["jobs"] if j["id"] == job]
    assert isinstance(found, dict)
    return found


def kill(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.kill()
    process.wait(timeout=60)


@pytest.fixture
def stop_file(tmp_path: Path) -> Iterator[Path]:
    """The waiting command's stop file, written when the test ends, pass or fail."""
    stop = tmp_path / "stop"
    exited = tmp_path / "waiter-exited"
    yield stop
    stop.write_text("stop", encoding="utf-8")
    if sys.platform == "win32":
        return  # the daemon's Job Object took the command with it, and a pid may be reused
    pid_file = tmp_path / "waiter-pid"
    if pid_file.exists() and not until(exited.exists, 15):
        with contextlib.suppress(OSError, ValueError):
            os.kill(int(read_text(pid_file)), signal.SIGTERM)


def check_resumed(
    out: str, job: str, runner_job: str, worktree: str, branch: str, *, stale: bool
) -> None:
    """`resume --json` names the job, task, worktree, branch, the commands and the handoff."""
    data = json.loads(out)
    assert data["job"]["id"] == job
    assert data["job"]["task"] == TASK
    assert data["job"]["lease"]["session"] == SESSION_B
    where = data["where"]
    assert real(where["worktree"]) == real(worktree)
    assert where["worktree_exists"] is True
    assert where["branch"] == branch
    [entry] = data["runner_jobs"]
    assert entry["id"] == runner_job
    assert entry["stale"] is stale
    argvs = [" ".join(c["argv"]) for c in entry["commands"]]
    assert any("handoff" in a and TASK in a for a in argvs), argvs
    assert any(MARK in a for a in argvs), argvs
    assert data["state"]["source"] == "worktree"
    assert data["state"]["next"] == NEXT
    assert NEXT in data["state"]["handoff"]["body"]


@pytest.mark.ac("E18-AC-17")
@pytest.mark.slow
def test_any_session_resumes_any_job_after_a_crash(tmp_path: Path, stop_file: Path) -> None:
    config = f"[jobs]\nlease_minutes = {LEASE_MINUTES}\ndaemon_timeout_seconds = 5\n"
    repo = factory_repo(tmp_path, config)
    state_py = repo / ".factory" / "state" / "state.py"
    for args in (("task", "new", TASK, "Crash test"), ("start", TASK, "--phase", "build")):
        subprocess.run([PY, str(state_py), "--root", str(repo), *args], check=True)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "the task")
    other = tmp_path / "other-checkout"
    git(repo, "worktree", "add", "-q", "-b", "other-checkout", str(other))
    body = tmp_path / "handoff.md"
    body.write_text(
        f"## Done\n\nThe first half.\n\n## Next\n\n{NEXT}\n\n## Open questions\n\nNone.\n",
        encoding="utf-8",
    )

    # 1. A job, claimed by session A, a separate process that beats.
    job = ok(jobs_py(repo, "new", "Survive a crash", "--task", TASK)).strip()
    claimed = tmp_path / "a-claimed"
    session_a = subprocess.Popen(
        [PY, "-c", SESSION_A_SCRIPT, str(JOBS_PY), job, SESSION_A, str(claimed)],
        cwd=repo,
        env=clean_env(),
    )
    daemon: subprocess.Popen[bytes] | None = None
    try:
        assert until(claimed.exists, 60), "session A claimed the job"

        # 2. An open runner job on a real daemon: a handoff with state.py, then a wait.
        runner_job = ok(run_py(repo, "submit", "--open", "--task", TASK)).strip()
        handoff = [PY, ".factory/state/state.py", "handoff", TASK, "--from", SESSION_A]
        ok(run_py(repo, "send", runner_job, "--", *handoff, "--body-file", str(body)))
        waiter = [str(stop_file), str(tmp_path / "waiter-pid"), str(tmp_path / "waiter-exited")]
        ok(run_py(repo, "send", runner_job, "--", PY, "-c", WAITER, *waiter))
        daemon = start_daemon(repo, tmp_path / "logs")
        assert until((tmp_path / "waiter-pid").exists, 120), "the daemon ran both commands"
        ran = status(repo, runner_job)
        assert ran["status"] == "running"
        assert [c["exit_code"] for c in ran["commands"]] == [0, None]
        worktree, branch = str(ran["worktree"]), str(ran["branch"])

        # 3. Session A and the daemon are killed without warning.
    finally:
        kill(session_a)
        if daemon is not None:
            kill(daemon)

    # 4. A fresh process in another worktree sees the job claimed, and resume refuses it.
    seen = the_job(other, job)
    assert seen["state"] == "claimed", seen
    assert seen["lease"]["session"] == SESSION_A
    refused = jobs_py(other, "resume", job, "--session", SESSION_B)
    assert time.time() < seconds(seen["lease"]["expires"]), "the machine was too slow to look"
    assert refused.returncode == 1, refused.stdout + refused.stderr
    assert SESSION_A in refused.stderr

    # 5. Once the lease has expired: crashed and stale, and B resumes it.
    expires = seconds(seen["lease"]["expires"])
    time.sleep(max(0.0, expires - time.time()) + 1)
    later = the_job(other, job)
    assert (later["state"], later["stale"]) == ("crashed", True), later
    daemons = json.loads(ok(jobs_py(other, "daemons", "--json")))
    assert [d["stale_runner_jobs"] for d in daemons if d["state"] == "dead"] == [[runner_job]]
    text = ok(jobs_py(other, "resume", job, "--session", SESSION_B))
    for part in (job, TASK, branch, runner_job, "handoff", MARK, NEXT):
        assert part in text, part
    assert real(worktree) in {real(w) for w in text.split()} or worktree in text
    resumed = ok(jobs_py(other, "resume", job, "--session", SESSION_B, "--json"))
    check_resumed(resumed, job, runner_job, worktree, branch, stale=True)

    # Then the index is deleted and rebuilt, and B resumes again with the same result.
    index = index_path(repo)
    index.unlink()
    assert not index.exists()
    ok(jobs_py(other, "rebuild"))
    assert the_job(other, job)["state"] == "unclaimed", "the lease went with the index"
    again = ok(jobs_py(other, "resume", job, "--session", SESSION_B, "--json"))
    check_resumed(again, job, runner_job, worktree, branch, stale=True)
    text = ok(jobs_py(other, "resume", job, "--session", SESSION_B))
    for part in (job, TASK, branch, runner_job, MARK, NEXT):
        assert part in text, part
