"""E16/T2: the daemon loop and worktrees, driven in-process through `Daemon.tick(now)`.

Covers E16 AC-03 (running commands), AC-05, AC-06 (order, parallelism, config), AC-08 (two
daemons in one process), AC-09, AC-10 and AC-11. Expectations come from the E16 spec, the design
note ("The daemon loop", "Test seams") and ADRs 0030 and 0032, not from the implementation.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

import pytest

import run as runner
from tests._daemon import (
    T0,
    Clock,
    FakeStart,
    branch_exists,
    claim_key,
    claims,
    drop,
    make_daemon,
    record,
    tick_until,
)
from tests._runner import call, factory_dir, git, job_dir, real, runner_repo, submit

PY = [sys.executable, "-c", "pass"]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return runner_repo(tmp_path)


@pytest.fixture
def one_at_a_time(tmp_path: Path) -> Path:
    return runner_repo(tmp_path, "[runner]\nmax_parallel = 1\n")


def worktree_of(repo: Path, job: str) -> Path:
    return repo.parent / f"{repo.name}.worktrees" / job


def send(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], job: str
) -> None:
    code, _, err = call(repo, monkeypatch, capsys, "send", job, "--", *PY)
    assert code == 0, err


def close(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], job: str
) -> None:
    code, _, err = call(repo, monkeypatch, capsys, "close", job)
    assert code == 0, err


# --- AC-03: commands run one at a time, in order, in the worktree ------------------------------


@pytest.mark.ac("E16-AC-03")
def test_commands_run_one_at_a_time_in_order_in_the_worktree(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job = submit(repo, monkeypatch, capsys, "--open", "--", sys.executable, "-c", "print(1)")
    call(repo, monkeypatch, capsys, "send", job, "--", sys.executable, "-c", "print(2)")
    call(repo, monkeypatch, capsys, "send", job, "--", sys.executable, "-c", "print(3)")
    start, clock = FakeStart(), Clock()
    daemon = make_daemon(repo, start)

    clock.tick(daemon, 3)
    assert len(start.calls) == 1, "the next command waits for the one running"
    for n in (1, 2, 3):
        current = start.calls[-1]
        assert current.argv[-1] == f"print({n})"
        assert real(current.cwd) == real(worktree_of(repo, job))
        assert current.env["FACTORY_JOB"] == job
        assert current.env.get("PATH") == os.environ.get("PATH"), "the environment is inherited"
        assert real(current.log) == real(job_dir(repo, job) / "logs" / f"{n:04d}.log")
        current.proc.finish(0)
        clock.tick(daemon)
    assert len(start.calls) == 3


@pytest.mark.ac("E16-AC-03")
def test_a_real_command_runs_without_a_shell_with_its_output_in_its_log(
    tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen = tmp_path / "seen.json"
    script = (
        "import json, os, sys; "
        "print('to stdout'); print('to stderr', file=sys.stderr); "
        "json.dump({'cwd': os.getcwd(), 'job': os.environ['FACTORY_JOB'], 'arg': sys.argv[2]}, "
        "open(sys.argv[1], 'w'))"
    )
    literal = "$HOME && echo `x` | more; %PATH%"
    job = submit(repo, monkeypatch, capsys, "--", sys.executable, "-c", script, str(seen), literal)
    daemon, clock = make_daemon(repo), Clock()
    assert tick_until(
        daemon,
        clock,
        lambda: (
            (job_dir(repo, job) / "job.toml").is_file()
            and record(repo, job)["status"] == "succeeded"
        ),
    )
    data = json.loads(seen.read_text(encoding="utf-8"))
    assert data["job"] == job
    assert data["arg"] == literal
    assert real(data["cwd"]) == real(worktree_of(repo, job))
    log = (job_dir(repo, job) / "logs" / "0001.log").read_text(encoding="utf-8")
    assert "to stdout" in log
    assert "to stderr" in log
    [ran] = record(repo, job)["commands"]
    assert ran["exit_code"] == 0
    assert ran["argv"][-1] == literal
    assert isinstance(ran["started"], dt.datetime)
    assert ran["duration_s"] >= 0


@pytest.mark.ac("E16-AC-03")
def test_a_command_that_cannot_start_fails_its_job(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job = submit(repo, monkeypatch, capsys, "--", "no-such-program-e16")
    daemon, clock = make_daemon(repo), Clock()
    assert tick_until(
        daemon,
        clock,
        lambda: (
            (job_dir(repo, job) / "job.toml").is_file() and record(repo, job)["status"] == "failed"
        ),
    )
    assert "no-such-program-e16" in (job_dir(repo, job) / "logs" / "0001.log").read_text(
        encoding="utf-8"
    )


# --- AC-05: malformed requests -----------------------------------------------------------------


@pytest.mark.ac("E16-AC-05")
@pytest.mark.parametrize(
    ("text", "word"),
    [
        ("this is [not toml\n", "toml"),
        (
            'version = 1\nid = "hand"\nbase = "main"\ntask = "hand"\nopen = false\n'
            "commands = [[]]\nsubmitted = 2026-11-19T21:00:00Z\n",
            "command",
        ),
        (
            'version = 1\nid = "other"\nbase = "main"\ntask = "hand"\nopen = false\n'
            'commands = [["x"]]\nsubmitted = 2026-11-19T21:00:00Z\n',
            "id",
        ),
        (
            'version = 1\nid = "hand"\nbase = "main"\ntask = "hand"\nopen = false\n'
            "commands = []\nsubmitted = 2026-11-19T21:00:00Z\n",
            "command",
        ),
        (
            'version = 2\nid = "hand"\nbase = "main"\ntask = "hand"\nopen = false\n'
            'commands = [["x"]]\nsubmitted = 2026-11-19T21:00:00Z\n',
            "version",
        ),
        ('id = "hand"\n', "base"),
    ],
)
def test_a_malformed_request_fails_with_a_reason_and_never_runs(
    repo: Path, text: str, word: str
) -> None:
    drop(repo, "hand.toml", text)
    start, clock = FakeStart(), Clock()
    daemon = make_daemon(repo, start)
    clock.tick(daemon, 2)
    data = record(repo, "hand")
    assert data["status"] == "failed"
    assert word in data["reason"].lower()
    assert start.calls == []
    assert claims(repo) == []
    assert not branch_exists(repo, "factory/hand")
    assert not (factory_dir(repo) / "queue" / "hand.toml").exists()


@pytest.mark.ac("E16-AC-05")
def test_the_daemon_carries_on_after_a_malformed_request(
    one_at_a_time: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = one_at_a_time
    drop(repo, "aaa-bad.toml", "not toml at all [\n")
    drop(repo, "Not_An_Id.toml", "version = 1\n")
    monkeypatch.setattr(runner, "_now", lambda: T0 + dt.timedelta(hours=1))
    good = submit(repo, monkeypatch, capsys, "--", *PY)
    start, clock = FakeStart(), Clock()
    daemon = make_daemon(repo, start)
    clock.tick(daemon, 2)
    assert [c.env["FACTORY_JOB"] for c in start.calls] == [good], "bad ones take no slot"
    assert record(repo, "aaa-bad")["status"] == "failed"
    queue = factory_dir(repo) / "queue"
    assert sorted(p.name for p in queue.iterdir()) == [], "bad requests leave the queue"
    rejected = factory_dir(repo) / "rejected"
    assert (rejected / "Not_An_Id.toml").is_file()
    reason = (rejected / "Not_An_Id.toml.job.toml").read_text(encoding="utf-8")
    assert 'status = "failed"' in reason


# --- AC-06: first come, first served, at most max_parallel ------------------------------------


@pytest.mark.ac("E16-AC-06")
def test_jobs_start_first_come_first_served(
    one_at_a_time: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = one_at_a_time
    order = ["zz", "mm", "aa"]
    for n, job in enumerate(order):
        monkeypatch.setattr(runner, "_now", lambda n=n: T0 + dt.timedelta(seconds=n))
        submit(repo, monkeypatch, capsys, "--id", job, "--", *PY)
    start, clock = FakeStart(), Clock()
    daemon = make_daemon(repo, start)
    started: list[str] = []
    for _ in range(3):
        clock.tick(daemon)
        assert len(daemon.running) == 1
        started.append(start.calls[-1].env["FACTORY_JOB"])
        start.calls[-1].proc.finish(0)
        clock.tick(daemon)
    assert started == order


@pytest.mark.ac("E16-AC-06")
def test_at_most_max_parallel_jobs_run_at_once(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    jobs = [submit(repo, monkeypatch, capsys, "--", *PY) for _ in range(4)]
    start, clock = FakeStart(), Clock()
    daemon = make_daemon(repo, start)
    clock.tick(daemon, 3)
    assert len(daemon.running) == 2
    assert len(start.calls) == 2
    statuses = [
        json.loads(call(repo, monkeypatch, capsys, "status", j, "--json")[1])["status"]
        for j in jobs
    ]
    assert sorted(statuses) == ["queued", "queued", "running", "running"]
    start.calls[0].proc.finish(0)
    clock.tick(daemon, 2)
    assert len(start.calls) == 3
    assert len(daemon.running) == 2


@pytest.mark.ac("E16-AC-06")
def test_the_daemon_exits_2_on_an_invalid_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = runner_repo(tmp_path, "[runner]\nmax_parallel = 0\n")
    code, _, err = call(repo, monkeypatch, capsys, "--daemon")
    assert code == 2
    assert "runner.max_parallel" in err


@pytest.mark.ac("E16-AC-06")
def test_daemon_and_a_command_together_exit_2(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, _ = call(repo, monkeypatch, capsys, "--daemon", "status", "x")
    assert code == 2


@pytest.mark.ac("E16-AC-06")
def test_a_running_record_names_its_daemon(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job = submit(repo, monkeypatch, capsys, "--", *PY)
    daemon, clock = make_daemon(repo, FakeStart()), Clock()
    clock.tick(daemon)
    data = record(repo, job)
    assert data["status"] == "running"
    assert data["started"] == clock.now
    assert data["daemon"] == daemon.name


# --- AC-08: each request is claimed once -----------------------------------------------------


@pytest.mark.ac("E16-AC-08")
def test_two_daemons_on_one_queue_never_run_a_job_twice(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    jobs = [submit(repo, monkeypatch, capsys, "--", *PY) for _ in range(6)]
    first, second = FakeStart(), FakeStart()
    one, two = make_daemon(repo, first), make_daemon(repo, second)
    assert one.name != two.name
    clock = Clock()
    for _ in range(6):
        clock.tick(one)
        clock.tick(two)
        for call_ in first.calls + second.calls:
            call_.proc.finish(0)
    ran = [c.env["FACTORY_JOB"] for c in first.calls + second.calls]
    assert sorted(ran) == sorted(jobs)
    for job in jobs:
        data = record(repo, job)
        assert data["status"] == "succeeded"
        assert data["daemon"] in (one.name, two.name)


@pytest.mark.ac("E16-AC-08")
def test_a_request_claimed_elsewhere_is_skipped(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job = submit(repo, monkeypatch, capsys, "--", *PY)
    start, clock = FakeStart(), Clock()
    daemon = make_daemon(repo, start)
    real_rename = os.rename

    def lose_the_race(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        if Path(src).parent.name == "queue":
            real_rename(src, Path(dst).with_name("taken-by-other.toml"))  # another daemon won
            raise FileNotFoundError(src)
        real_rename(src, dst)

    monkeypatch.setattr(os, "rename", lose_the_race)
    clock.tick(daemon, 2)
    assert start.calls == []
    assert daemon.running == {}
    assert not (job_dir(repo, job) / "job.toml").exists()


# --- AC-09: worktrees and their claims --------------------------------------------------------


@pytest.mark.ac("E16-AC-09")
def test_a_job_gets_a_worktree_on_its_own_branch_from_its_base(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    git(repo, "checkout", "-q", "-b", "feature")
    (repo / "extra.txt").write_text("x\n", encoding="utf-8")
    git(repo, "add", "extra.txt")
    git(repo, "commit", "-q", "-m", "extra")
    feature = git(repo, "rev-parse", "feature").strip()
    git(repo, "checkout", "-q", "main")
    job = submit(repo, monkeypatch, capsys, "--base", "feature", "--", *PY)
    daemon, clock = make_daemon(repo, FakeStart()), Clock()
    clock.tick(daemon)
    worktree = worktree_of(repo, job)
    assert (worktree / "extra.txt").is_file()
    assert git(worktree, "rev-parse", "--abbrev-ref", "HEAD").strip() == f"factory/{job}"
    assert git(worktree, "rev-parse", "HEAD").strip() == feature
    [claim] = claims(repo)
    assert claim.name == claim_key(worktree)
    assert claim.read_text(encoding="utf-8").strip() == job
    assert real(record(repo, job)["worktree"]) == real(worktree)


@pytest.mark.ac("E16-AC-09")
def test_a_claimed_path_fails_the_new_job_and_leaves_the_other_alone(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job = submit(repo, monkeypatch, capsys, "--id", "clash", "--", *PY)
    folder = factory_dir(repo) / "claims"
    folder.mkdir(parents=True)
    held = folder / claim_key(worktree_of(repo, job))
    held.write_text("someone-else\n", encoding="utf-8")
    start, clock = FakeStart(), Clock()
    daemon = make_daemon(repo, start)
    clock.tick(daemon)
    data = record(repo, job)
    assert data["status"] == "failed"
    assert str(worktree_of(repo, job).name) in data["reason"]
    assert "claim" in data["reason"].lower()
    assert held.read_text(encoding="utf-8") == "someone-else\n"
    assert start.calls == []
    assert not branch_exists(repo, "factory/clash")


@pytest.mark.ac("E16-AC-09")
def test_a_path_that_already_exists_fails_the_job_and_releases_the_claim(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job = submit(repo, monkeypatch, capsys, "--id", "exists", "--", *PY)
    squatter = worktree_of(repo, job)
    squatter.mkdir(parents=True)
    (squatter / "keep.txt").write_text("mine\n", encoding="utf-8")
    daemon, clock = make_daemon(repo, FakeStart()), Clock()
    clock.tick(daemon)
    data = record(repo, job)
    assert data["status"] == "failed"
    assert "exists" in data["reason"]
    assert (squatter / "keep.txt").read_text(encoding="utf-8") == "mine\n"
    assert claims(repo) == []


@pytest.mark.ac("E16-AC-09")
def test_a_bad_base_fails_the_job_and_leaves_nothing_behind(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job = submit(repo, monkeypatch, capsys, "--base", "no-such-ref", "--", *PY)
    start, clock = FakeStart(), Clock()
    daemon = make_daemon(repo, start)
    clock.tick(daemon)
    data = record(repo, job)
    assert data["status"] == "failed"
    assert "no-such-ref" in data["reason"]
    assert start.calls == []
    assert not worktree_of(repo, job).exists()
    assert not branch_exists(repo, f"factory/{job}")
    assert claims(repo) == []
    assert job not in git(repo, "worktree", "list")


@pytest.mark.ac("E16-AC-09")
def test_an_existing_branch_fails_the_job_and_survives(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    git(repo, "branch", "factory/taken")
    job = submit(repo, monkeypatch, capsys, "--id", "taken", "--", *PY)
    daemon, clock = make_daemon(repo, FakeStart()), Clock()
    clock.tick(daemon)
    assert record(repo, job)["status"] == "failed"
    assert branch_exists(repo, "factory/taken")
    assert claims(repo) == []
    assert not worktree_of(repo, job).exists()


# --- AC-10: success removes the worktree -----------------------------------------------------


@pytest.mark.ac("E16-AC-10")
def test_success_removes_the_worktree_and_claim_but_keeps_the_branch(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job = submit(repo, monkeypatch, capsys, "--", *PY)
    start, clock = FakeStart(), Clock()
    daemon = make_daemon(repo, start)
    clock.tick(daemon)
    start.calls[0].proc.finish(0)
    clock.tick(daemon)
    data = record(repo, job)
    assert data["status"] == "succeeded"
    assert data["reason"] == ""
    assert data["finished"] == clock.now
    assert not worktree_of(repo, job).exists()
    assert job not in git(repo, "worktree", "list")
    assert claims(repo) == []
    assert branch_exists(repo, f"factory/{job}")
    assert daemon.running == {}


@pytest.mark.ac("E16-AC-10")
def test_uncommitted_changes_keep_the_worktree_and_the_record_says_why(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job = submit(repo, monkeypatch, capsys, "--", *PY)
    start, clock = FakeStart(), Clock()
    daemon = make_daemon(repo, start)
    clock.tick(daemon)
    (worktree_of(repo, job) / "README.md").write_text("changed\n", encoding="utf-8")
    start.calls[0].proc.finish(0)
    clock.tick(daemon)
    data = record(repo, job)
    assert data["status"] == "succeeded"
    assert (worktree_of(repo, job) / "README.md").read_text(encoding="utf-8") == "changed\n"
    assert any("kept" in warning for warning in data["warnings"])
    assert len(claims(repo)) == 1, "the worktree is still there, so its claim stays"


# --- AC-11: the result rule -------------------------------------------------------------------


@pytest.mark.ac("E16-AC-11")
def test_a_one_command_job_fails_on_a_non_zero_exit_and_keeps_everything(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job = submit(repo, monkeypatch, capsys, "--", *PY)
    start, clock = FakeStart(), Clock()
    daemon = make_daemon(repo, start)
    clock.tick(daemon)
    start.calls[0].proc.finish(3)
    clock.tick(daemon)
    data = record(repo, job)
    assert data["status"] == "failed"
    assert "3" in data["reason"]
    assert data["commands"][0]["exit_code"] == 3
    assert worktree_of(repo, job).is_dir()
    assert branch_exists(repo, f"factory/{job}")
    assert len(claims(repo)) == 1


@pytest.mark.ac("E16-AC-11")
@pytest.mark.parametrize(
    ("codes", "final"),
    [([1, 0], "succeeded"), ([0, 1], "failed"), ([0, 0], "succeeded"), ([], "succeeded")],
)
def test_an_open_job_ends_by_its_last_command(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    codes: list[int],
    final: str,
) -> None:
    job = submit(repo, monkeypatch, capsys, "--open")
    start, clock = FakeStart(), Clock()
    daemon = make_daemon(repo, start)
    clock.tick(daemon)
    for code in codes:
        send(repo, monkeypatch, capsys, job)
        clock.tick(daemon)
        start.calls[-1].proc.finish(code)
        clock.tick(daemon)
        assert record(repo, job)["status"] == "running", "a failure doesn't end an open job"
    assert len(start.calls) == len(codes)
    close(repo, monkeypatch, capsys, job)
    clock.tick(daemon)
    data = record(repo, job)
    assert data["status"] == final
    assert [c["exit_code"] for c in data.get("commands", [])] == codes
    assert worktree_of(repo, job).exists() == (final == "failed")


@pytest.mark.ac("E16-AC-11")
def test_an_open_job_waits_for_commands_until_it_is_closed(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job = submit(repo, monkeypatch, capsys, "--open")
    start, clock = FakeStart(), Clock()
    daemon = make_daemon(repo, start)
    clock.tick(daemon, 5)
    assert record(repo, job)["status"] == "running"
    assert start.calls == []
    send(repo, monkeypatch, capsys, job)
    clock.tick(daemon)
    assert len(start.calls) == 1
