"""E16/T3: halting a job, `cancel`, `stop` and Ctrl+C, driven in-process.

Covers E16 AC-16 and AC-07. Expectations come from the E16 spec and the design note ("The
handoff on halt", "`cancel` on a queued job", "The daemon loop"), not from the implementation.
The daemon runs with the fake starter from tests/_daemon.py, so no real command is killed here;
tests/test_runner_tree.py and tests/test_runner_halts.py do that.
"""

from __future__ import annotations

import datetime as dt
import sys
import threading
import time
from pathlib import Path

import pytest

import run as runner
from tests._daemon import Clock, FakeStart, branch_exists, claims, make_daemon, record, until
from tests._halt import factory_repo, handoffs, state_py
from tests._runner import call, git, job_dir, queue_file, read_toml, runner_repo, submit

PY = [sys.executable, "-c", "pass"]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return factory_repo(tmp_path)


def worktree_of(repo: Path, job: str) -> Path:
    return repo.parent / f"{repo.name}.worktrees" / job


def cancel(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], job: str
) -> int:
    code, _, _ = call(repo, monkeypatch, capsys, "cancel", job)
    return code


def running(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *args: str,
) -> tuple[str, FakeStart, Clock, runner.Daemon]:
    """A job whose first command has started and is still running."""
    job = submit(repo, monkeypatch, capsys, *args)
    start, clock = FakeStart(), Clock()
    daemon = make_daemon(repo, start)
    clock.tick(daemon)
    assert record(repo, job)["status"] == "running"
    assert len(start.for_job(job)) == 1
    return job, start, clock, daemon


# --- AC-16: cancel ---------------------------------------------------------------------------


@pytest.mark.ac("E16-AC-16")
def test_cancel_halts_a_running_job_kills_its_command_and_keeps_its_worktree(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job, start, clock, daemon = running(repo, monkeypatch, capsys, "--", *PY)
    assert cancel(repo, monkeypatch, capsys, job) == 0
    clock.tick(daemon)

    data = record(repo, job)
    assert data["status"] == "halted"
    assert data["reason"] == "cancelled"
    assert isinstance(data["finished"], dt.datetime)
    [call_] = start.for_job(job)
    assert call_.proc.killed, "the running command was killed"
    [ran] = data["commands"]
    assert ran["exit_code"] is not None, "the killed command's exit is recorded"
    assert worktree_of(repo, job).is_dir(), "a halted job keeps its worktree"
    assert branch_exists(repo, f"factory/{job}")
    assert claims(repo), "and its claim"
    assert job not in daemon.running


@pytest.mark.ac("E16-AC-16")
def test_cancel_halts_an_open_job_waiting_for_commands(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job = submit(repo, monkeypatch, capsys, "--open")
    daemon, clock = make_daemon(repo, FakeStart()), Clock()
    clock.tick(daemon)
    assert record(repo, job)["status"] == "running"

    assert cancel(repo, monkeypatch, capsys, job) == 0
    clock.tick(daemon)
    assert record(repo, job)["status"] == "halted"
    assert record(repo, job)["reason"] == "cancelled"


@pytest.mark.ac("E16-AC-16")
def test_a_cancelled_queued_job_never_starts(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job = submit(repo, monkeypatch, capsys, "--", *PY)
    assert cancel(repo, monkeypatch, capsys, job) == 0

    data = record(repo, job)
    assert data["status"] == "halted"
    assert data["reason"] == "cancelled"
    assert isinstance(data["finished"], dt.datetime)
    assert not queue_file(repo, job).exists(), "it has left the queue"

    start, clock = FakeStart(), Clock()
    daemon = make_daemon(repo, start)
    clock.tick(daemon, 3)
    assert start.calls == []
    assert not worktree_of(repo, job).exists()
    assert record(repo, job)["status"] == "halted"

    code, out, _ = call(repo, monkeypatch, capsys, "status", job)
    assert code == 0
    assert 'status = "halted"' in out


@pytest.mark.ac("E16-AC-16")
def test_halting_a_finished_job_exits_1_and_changes_nothing(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job, start, clock, daemon = running(repo, monkeypatch, capsys, "--", *PY)
    start.for_job(job)[0].proc.finish(0)
    clock.tick(daemon)
    assert record(repo, job)["status"] == "succeeded"
    before = sorted(p.relative_to(job_dir(repo, job)) for p in job_dir(repo, job).rglob("*"))
    text = (job_dir(repo, job) / "job.toml").read_bytes()

    assert cancel(repo, monkeypatch, capsys, job) == 1
    clock.tick(daemon)
    assert (job_dir(repo, job) / "job.toml").read_bytes() == text
    after = sorted(p.relative_to(job_dir(repo, job)) for p in job_dir(repo, job).rglob("*"))
    assert after == before, "no marker or other file was added"


@pytest.mark.ac("E16-AC-16")
def test_halting_a_halted_job_again_exits_1(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job = submit(repo, monkeypatch, capsys, "--", *PY)
    assert cancel(repo, monkeypatch, capsys, job) == 0
    text = (job_dir(repo, job) / "job.toml").read_bytes()
    assert cancel(repo, monkeypatch, capsys, job) == 1
    assert (job_dir(repo, job) / "job.toml").read_bytes() == text


@pytest.mark.ac("E16-AC-16")
def test_cancel_refuses_an_unknown_job_or_a_command_with_exit_2(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cancel(repo, monkeypatch, capsys, "no-such-job") == 2
    job = submit(repo, monkeypatch, capsys, "--", *PY)
    code, _, _ = call(repo, monkeypatch, capsys, "cancel", job, "--", *PY)
    assert code == 2
    assert queue_file(repo, job).exists(), "a refused cancel leaves the job queued"


@pytest.mark.ac("E16-AC-16")
def test_a_halt_drops_the_commands_still_queued(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job, start, clock, daemon = running(repo, monkeypatch, capsys, "--open", "--", *PY)
    for _ in range(2):
        code, _, err = call(repo, monkeypatch, capsys, "send", job, "--", *PY)
        assert code == 0, err
    assert cancel(repo, monkeypatch, capsys, job) == 0
    clock.tick(daemon, 4)

    assert len(start.for_job(job)) == 1, "no queued command runs after a halt"
    assert len(record(repo, job)["commands"]) == 1
    code, _, _ = call(repo, monkeypatch, capsys, "send", job, "--", *PY)
    assert code == 1, "a halted job takes no more commands"


# --- AC-16: the handoff ----------------------------------------------------------------------


def section(text: str, heading: str) -> str:
    rest = text.split(heading, 1)[1]
    return rest.split("\n## ", 1)[0]


@pytest.mark.ac("E16-AC-16")
def test_a_halt_writes_a_handoff_with_the_worktrees_own_state_py(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job, start, clock, daemon = running(
        repo, monkeypatch, capsys, "--open", "--", sys.executable, "-c", "print('first')"
    )
    call(repo, monkeypatch, capsys, "send", job, "--", sys.executable, "-c", "print('second')")
    start.for_job(job)[0].proc.finish(0)
    clock.tick(daemon)
    assert len(start.for_job(job)) == 2
    assert cancel(repo, monkeypatch, capsys, job) == 0
    clock.tick(daemon)

    data = record(repo, job)
    worktree = Path(data["worktree"])
    assert not [w for w in data["warnings"] if w.startswith("handoff")], data["warnings"]
    assert (worktree / ".agentic" / "tasks" / f"{job}.md").is_file(), "the task was created"
    [note] = handoffs(worktree, job)
    text = note.read_text(encoding="utf-8")
    assert 'from = "runner"' in text
    done = section(text, "## Done")
    assert "print('first')" in done and "print('second')" in done, "it says what ran"
    following = section(text, "## Next")
    assert "cancelled" in following, "it says why the job stopped"
    assert data["worktree"] in following, "it says where the worktree is"
    assert f"factory/{job}" in following, "and the branch"
    assert "## Open questions" in text

    checked = state_py(worktree, "check")
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert not handoffs(repo, job), "the handoff is in the job's worktree, not the main one"


@pytest.mark.ac("E16-AC-16")
def test_a_halt_uses_the_task_when_it_already_exists(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    made = state_py(repo, "task", "new", "E16-T99", "An existing task")
    assert made.returncode == 0, made.stderr
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "task")
    job, _, clock, daemon = running(repo, monkeypatch, capsys, "--task", "E16-T99", "--", *PY)
    assert cancel(repo, monkeypatch, capsys, job) == 0
    clock.tick(daemon)

    data = record(repo, job)
    worktree = Path(data["worktree"])
    assert not [w for w in data["warnings"] if w.startswith("handoff")], data["warnings"]
    task = (worktree / ".agentic" / "tasks" / "E16-T99.md").read_text(encoding="utf-8")
    assert "An existing task" in task, "the existing task file is kept"
    assert len(handoffs(worktree, "E16-T99")) == 1
    assert state_py(worktree, "check").returncode == 0


@pytest.mark.ac("E16-AC-16")
def test_a_halt_stands_when_the_handoff_cannot_be_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    bare = runner_repo(tmp_path, name="bare")  # no .factory/state/state.py, no .agentic
    job, start, clock, daemon = running(bare, monkeypatch, capsys, "--", *PY)
    assert cancel(bare, monkeypatch, capsys, job) == 0
    clock.tick(daemon)

    data = record(bare, job)
    assert data["status"] == "halted"
    assert data["reason"] == "cancelled"
    assert [w for w in data["warnings"] if w.startswith("handoff:")], data["warnings"]
    assert start.for_job(job)[0].proc.killed
    assert worktree_of(bare, job).is_dir()


FAKE_STATE_PY = """\
import shutil, subprocess, sys
from pathlib import Path

args = sys.argv[1:]
root = Path(args[args.index("--root") + 1])
if "handoff" in args:
    common = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=root, capture_output=True, text=True, check=True,
    ).stdout.strip()
    for found in (Path(common) / "factory" / "jobs").glob("*/job.toml"):
        shutil.copyfile(found, root / "record-at-handoff.toml")
"""


@pytest.mark.ac("E16-AC-16")
def test_a_halt_kills_and_records_before_it_writes_the_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = runner_repo(tmp_path, name="fake")
    (fake / ".factory" / "state").mkdir(parents=True)
    (fake / ".factory" / "state" / "state.py").write_text(FAKE_STATE_PY, encoding="utf-8")
    git(fake, "add", "-A")
    git(fake, "commit", "-q", "-m", "a state.py that copies the record when asked for a handoff")
    job, _, clock, daemon = running(fake, monkeypatch, capsys, "--", *PY)
    assert cancel(fake, monkeypatch, capsys, job) == 0
    clock.tick(daemon)

    seen = read_toml(worktree_of(fake, job) / "record-at-handoff.toml")
    assert seen["status"] == "halted"
    assert seen["reason"] == "cancelled"
    assert isinstance(seen["finished"], dt.datetime)
    assert seen["commands"][0]["exit_code"] is not None, "the command was killed first"


# --- AC-07: stop and Ctrl+C --------------------------------------------------------------------


@pytest.fixture
def one_at_a_time(tmp_path: Path) -> Path:
    return factory_repo(tmp_path, "[runner]\nmax_parallel = 1\n")


@pytest.mark.ac("E16-AC-07")
def test_stop_halts_the_running_jobs_and_leaves_queued_jobs_queued(
    one_at_a_time: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = one_at_a_time
    first, start, clock, daemon = running(repo, monkeypatch, capsys, "--", *PY)
    second = submit(repo, monkeypatch, capsys, "--", *PY)
    clock.tick(daemon)
    assert queue_file(repo, second).exists()

    code, _, err = call(repo, monkeypatch, capsys, "stop")
    assert code == 0, err
    assert daemon.run() == 0

    data = record(repo, first)
    assert data["status"] == "halted"
    assert data["reason"] == "daemon stopped"
    assert start.for_job(first)[0].proc.killed
    assert [c for c in start.calls if c.env.get("FACTORY_JOB") == second] == []
    assert queue_file(repo, second).exists(), "a queued job stays queued for the next daemon"
    assert not (job_dir(repo, second) / "job.toml").exists()
    assert len(handoffs(worktree_of(repo, first), first)) == 1


@pytest.mark.ac("E16-AC-07")
def test_a_stop_from_before_the_daemon_started_does_not_stop_it(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert call(repo, monkeypatch, capsys, "stop")[0] == 0
    time.sleep(0.05)
    job = submit(repo, monkeypatch, capsys, "--", *PY)
    daemon = make_daemon(repo, FakeStart())
    result: list[int] = []
    thread = threading.Thread(target=lambda: result.append(daemon.run()), daemon=True)
    thread.start()
    assert until(lambda: (job_dir(repo, job) / "job.toml").is_file(), timeout=10)
    time.sleep(1.0)
    assert thread.is_alive(), "an old stop must not stop a new daemon"

    assert call(repo, monkeypatch, capsys, "stop")[0] == 0
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert result == [0]
    assert record(repo, job)["reason"] == "daemon stopped"


@pytest.mark.ac("E16-AC-07")
def test_ctrl_c_halts_the_running_jobs_and_the_daemon_exits_0(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job, start, clock, daemon = running(repo, monkeypatch, capsys, "--", *PY)
    queued = submit(repo, monkeypatch, capsys, "--", *PY)
    real_tick = daemon.tick
    ticks: list[int] = []

    def tick(now: dt.datetime) -> None:
        ticks.append(1)
        if len(ticks) > 1:
            raise KeyboardInterrupt
        real_tick(clock.now)

    monkeypatch.setattr(daemon, "tick", tick)
    assert daemon.run() == 0

    data = record(repo, job)
    assert data["status"] == "halted"
    assert data["reason"] == "daemon stopped"
    assert start.for_job(job)[0].proc.killed
    queued_record = job_dir(repo, queued) / "job.toml"
    if queued_record.exists():  # the one real tick may have started it, within max_parallel
        assert record(repo, queued)["status"] == "halted"
    else:
        assert queue_file(repo, queued).exists()


@pytest.mark.ac("E16-AC-07")
def test_stop_takes_no_command(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, _ = call(repo, monkeypatch, capsys, "stop", "--", *PY)
    assert code == 2
