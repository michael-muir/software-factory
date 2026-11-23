"""E18/T4: `jobs.py resume`, from a worktree, from a branch, and from what the index still has.

Covers E18 AC-15 (resume claims the job and prints the record, the lease, where it works, its
runner jobs with their last 5 commands and cost, the total cost, and the worktree's state with
the newest handoff in full), AC-16 (a worktree that has gone, and a branch that has gone too) and
AC-19 (the glossary, CI, and every E18 AC has a test). Expectations come from the E18 spec and
the design note ("Resume (T4)"), not from the implementation.

`resume --json` prints one object with the design's five sections as keys:

- `job`: the record's fields, with `state`, the new `lease` and `sidecars`;
- `where`: `branch`, `branch_exists`, `worktree`, `worktree_exists`, `rebuild` (the commands
  that rebuild a worktree that has gone, each as an argv list, the last being
  `git worktree add <worktree> <branch>`) and `notes` (what has gone, in words);
- `runner_jobs`: each one's `id`, `status`, `stale`, `commands` (the last 5, each with `n`,
  `argv` and `exit_code`) and `usd` (an exact decimal, as text);
- `cost`: `usd`, the total across the job's runner jobs (an exact decimal, as text);
- `state`: `source` (`worktree`, `branch`, `index` or `none`), `place`, `phase`,
  `active_task`, `task` (`id`, `status`, `review_round`, `open_findings`), `handoff` (`path`,
  `from`, `to`, `created` and the whole `body`) and `next`, the handoff's `## Next` section.
"""

from __future__ import annotations

import datetime as dt
import decimal
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import jobs
from tests._ac import COLLECTED_AC_IDS, REPO_ROOT, spec_ac_ids
from tests._daemon import Clock, FakeStart, make_daemon
from tests._jobs import api_repo, call, git, new, record
from tests._jobs_index import factory_repo, real, run_py, runner_status, state, submit

PY = sys.executable
TASK = "E31-T1"
NEXT = "Wire the parser into the build step, then rerun the gate."
CODES = (0, 0, 3, 0, 0, 1)  # the exit codes of the second runner job's six commands


@dataclass
class Scene:
    repo: Path
    job: str
    first: str  # a finished runner job, with one command
    second: str  # the newest: an open runner job that ran six commands
    worktree: Path  # the second runner job's worktree
    branch: str


def body_file(tmp: Path, next_text: str, name: str = "handoff.md") -> Path:
    path = tmp / name
    path.write_text(
        f"## Done\n\nThe tokenizer.\n\n## Next\n\n{next_text}\n\n## Open questions\n\nNone.\n",
        encoding="utf-8",
    )
    return path


def resume_json(
    cwd: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    job: str,
    *args: str,
) -> dict[str, Any]:
    code, out, err = call(cwd, monkeypatch, capsys, "resume", job, "--json", *args)
    assert code == 0, err
    data: dict[str, Any] = json.loads(out)
    return data


def scene(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> Scene:
    """A job on TASK with two runner jobs, the newer one's worktree holding the task's state."""
    repo = factory_repo(tmp_path)
    state(repo, "task", "new", TASK, "The parser")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "the task")
    job = new(repo, monkeypatch, capsys, "Build the parser", "--task", TASK)
    start, clock = FakeStart(), Clock()
    daemon = make_daemon(repo, start)
    first = submit(repo, monkeypatch, capsys, "--task", TASK, "--", PY, "-c", "print('first')")
    clock.tick(daemon, 2)
    start.for_job(first)[0].proc.finish(0)
    clock.tick(daemon, 2)
    assert runner_status(repo, monkeypatch, capsys, first)["status"] == "succeeded"
    second = submit(repo, monkeypatch, capsys, "--open", "--task", TASK)
    for n in range(1, len(CODES) + 1):
        code, _, err = run_py(repo, monkeypatch, capsys, "send", second, "--", PY, "-c", f"#{n}")
        assert code == 0, err
    for n, exit_code in enumerate(CODES, start=1):
        clock.tick(daemon, 2)
        calls = start.for_job(second)
        assert len(calls) == n, "the commands run one at a time"
        calls[-1].proc.finish(exit_code)
    clock.tick(daemon, 2)
    for runner_job, usd in ((first, "0.30"), (second, "0.40"), (second, "0.05")):
        code, _, err = run_py(repo, monkeypatch, capsys, "usage", runner_job, "--usd", usd)
        assert code == 0, err
    status = runner_status(repo, monkeypatch, capsys, second)
    worktree = Path(status["worktree"])
    assert worktree.is_dir()
    state(worktree, "start", TASK, "--phase", "build")
    state(worktree, "finding", "add", TASK, "--severity", "major", "The lexer drops tabs")
    old = body_file(tmp_path, "An older next step.", "old.md")
    state(worktree, "handoff", TASK, "--from", "session A", "--body-file", str(old))
    state(
        worktree,
        "handoff",
        TASK,
        "--from",
        "session A",
        "--body-file",
        str(body_file(tmp_path, NEXT)),
    )
    return Scene(repo, job, first, second, worktree, str(status["branch"]))


def commit_state(worktree: Path) -> None:
    git(worktree, "add", "-A")
    git(worktree, "commit", "-q", "-m", "state")


# --- AC-15: resume claims the job and prints what a new session needs --------------------------


@pytest.mark.ac("E18-AC-15")
def test_resume_claims_the_job_and_gives_its_record_and_new_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    s = scene(tmp_path, monkeypatch, capsys)
    data = resume_json(s.repo, monkeypatch, capsys, s.job, "--session", "s-b")
    assert set(data) >= {"job", "where", "runner_jobs", "cost", "state"}
    shown = data["job"]
    assert (shown["id"], shown["title"], shown["task"], shown["tasks"]) == (
        s.job,
        "Build the parser",
        TASK,
        [TASK],
    )
    assert (shown["state"], shown["owner"]) == ("claimed", "s-b")
    assert shown["lease"]["session"] == "s-b"
    expires = dt.datetime.fromisoformat(shown["lease"]["expires"]).timestamp()
    assert expires > dt.datetime.now(dt.UTC).timestamp() + 9 * 60, "the default lease, 10 minutes"
    assert shown["sidecars"] == {}
    saved = record(s.repo, s.job)
    assert saved["owner"] == "s-b"
    assert [c["session"] for c in saved["claims"]] == ["s-b"]
    assert jobs.lease_state(api_repo(s.repo), s.job) == "claimed"


@pytest.mark.ac("E18-AC-15")
def test_resume_gives_the_branch_and_worktree_of_the_newest_runner_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    s = scene(tmp_path, monkeypatch, capsys)
    where = resume_json(s.repo, monkeypatch, capsys, s.job, "--session", "s-b")["where"]
    assert where["branch"] == s.branch == f"factory/{s.second}"
    assert real(where["worktree"]) == real(s.worktree)
    assert (where["branch_exists"], where["worktree_exists"]) == (True, True)
    assert where["rebuild"] == []


@pytest.mark.ac("E18-AC-15")
def test_the_jobs_own_branch_and_worktree_come_before_its_runner_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    s = scene(tmp_path, monkeypatch, capsys)
    own = tmp_path / "own-tree"
    git(s.repo, "worktree", "add", "-q", "-b", "own-branch", str(own))
    assert call(s.repo, monkeypatch, capsys, "claim", s.job, "--session", "s-a")[0] == 0
    code, _, err = call(
        s.repo,
        monkeypatch,
        capsys,
        *("set", s.job, "--session", "s-a", "--branch", "own-branch", "--worktree", str(own)),
    )
    assert code == 0, err
    data = resume_json(s.repo, monkeypatch, capsys, s.job, "--session", "s-a")
    where = data["where"]
    assert (where["branch"], real(where["worktree"])) == ("own-branch", real(own))
    assert (where["branch_exists"], where["worktree_exists"]) == (True, True)
    assert data["state"]["source"] == "worktree"
    assert real(data["state"]["place"]) == real(own)


@pytest.mark.ac("E18-AC-15")
def test_resume_gives_each_runner_jobs_last_five_commands_and_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    s = scene(tmp_path, monkeypatch, capsys)
    data = resume_json(s.repo, monkeypatch, capsys, s.job, "--session", "s-b")
    runners = {r["id"]: r for r in data["runner_jobs"]}
    assert [r["id"] for r in data["runner_jobs"]] == [s.first, s.second], "oldest first"
    first, second = runners[s.first], runners[s.second]
    assert (first["status"], first["stale"], first["usd"]) == ("succeeded", False, "0.30")
    assert [(c["n"], c["argv"], c["exit_code"]) for c in first["commands"]] == [
        (1, [PY, "-c", "print('first')"], 0)
    ]
    assert second["status"] == "running"
    assert second["usd"] == "0.45"
    assert [c["n"] for c in second["commands"]] == [2, 3, 4, 5, 6], "the last 5 of 6"
    assert [c["argv"] for c in second["commands"]] == [[PY, "-c", f"#{n}"] for n in range(2, 7)]
    assert [c["exit_code"] for c in second["commands"]] == list(CODES[1:])
    assert decimal.Decimal(data["cost"]["usd"]) == decimal.Decimal("0.75")
    assert data["cost"]["usd"] == "0.75", "an exact decimal, not a float"


@pytest.mark.ac("E18-AC-15")
def test_resume_gives_the_worktrees_state_and_the_newest_handoff_in_full(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    s = scene(tmp_path, monkeypatch, capsys)
    found = resume_json(s.repo, monkeypatch, capsys, s.job, "--session", "s-b")["state"]
    assert found["source"] == "worktree"
    assert real(found["place"]) == real(s.worktree)
    assert (found["phase"], found["active_task"]) == ("build", TASK)
    task = found["task"]
    assert (task["id"], task["status"], task["review_round"]) == (TASK, "in-progress", 0)
    assert [(f["severity"], f["summary"]) for f in task["open_findings"]] == [
        ("major", "The lexer drops tabs")
    ]
    handoff = found["handoff"]
    assert handoff["path"].startswith(".agentic/handoffs/")
    assert handoff["from"] == "session A"
    assert "## Done" in handoff["body"]
    assert NEXT in handoff["body"]
    assert "## Open questions" in handoff["body"]
    assert found["next"] == NEXT
    assert "An older next step." not in handoff["body"], "the newest handoff only"


@pytest.mark.ac("E18-AC-15")
def test_resume_reads_the_worktrees_files_again_before_it_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    s = scene(tmp_path, monkeypatch, capsys)
    resume_json(s.repo, monkeypatch, capsys, s.job, "--session", "s-b")
    later = "A step written after the last resume."
    body = body_file(tmp_path, later, "later.md")
    state(s.worktree, "handoff", TASK, "--from", "session B", "--body-file", str(body))
    found = resume_json(s.repo, monkeypatch, capsys, s.job, "--session", "s-b")["state"]
    assert found["next"] == later
    assert found["handoff"]["from"] == "session B"


@pytest.mark.ac("E18-AC-15")
def test_resume_as_text_names_every_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    s = scene(tmp_path, monkeypatch, capsys)
    code, out, err = call(s.repo, monkeypatch, capsys, "resume", s.job, "--session", "s-b")
    assert code == 0, err
    for part in (s.job, "Build the parser", TASK, "s-b", s.branch, s.first, s.second, "0.75"):
        assert part in out, part
    assert real(s.worktree) in {real(word) for word in out.split()} or str(s.worktree) in out
    assert "#6" in out and "#1" not in out, "the second runner job's last 5 commands"
    assert "The lexer drops tabs" in out
    assert NEXT in out
    assert "## Open questions" in out, "the handoff in full"


@pytest.mark.ac("E18-AC-15")
def test_resume_refuses_a_live_lease_held_by_another_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    s = scene(tmp_path, monkeypatch, capsys)
    assert call(s.repo, monkeypatch, capsys, "claim", s.job, "--session", "s-a")[0] == 0
    code, out, err = call(s.repo, monkeypatch, capsys, "resume", s.job, "--session", "s-b")
    assert code == 1
    assert "s-a" in err
    assert out == ""
    assert record(s.repo, s.job)["owner"] == "s-a"


@pytest.mark.ac("E18-AC-15")
def test_resume_with_force_takes_a_live_lease_and_the_record_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    s = scene(tmp_path, monkeypatch, capsys)
    assert call(s.repo, monkeypatch, capsys, "claim", s.job, "--session", "s-a")[0] == 0
    data = resume_json(s.repo, monkeypatch, capsys, s.job, "--session", "s-b", "--force")
    assert data["job"]["lease"]["session"] == "s-b"
    last = record(s.repo, s.job)["claims"][-1]
    assert (last["session"], last["forced"], last["from"]) == ("s-b", True, "s-a")


@pytest.mark.ac("E18-AC-15")
def test_the_holder_resuming_again_only_renews_its_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    s = scene(tmp_path, monkeypatch, capsys)
    resume_json(s.repo, monkeypatch, capsys, s.job, "--session", "s-b")
    resume_json(s.repo, monkeypatch, capsys, s.job, "--session", "s-b")
    assert len(record(s.repo, s.job)["claims"]) == 1


@pytest.mark.ac("E18-AC-15")
def test_resume_takes_the_session_from_factory_session_or_makes_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = factory_repo(tmp_path)
    one = new(repo, monkeypatch, capsys, "One")
    two = new(repo, monkeypatch, capsys, "Two")
    monkeypatch.setenv("FACTORY_SESSION", "s-from-env")
    assert resume_json(repo, monkeypatch, capsys, one)["job"]["lease"]["session"] == "s-from-env"
    monkeypatch.delenv("FACTORY_SESSION")
    made = resume_json(repo, monkeypatch, capsys, two)["job"]["lease"]["session"]
    assert made.startswith("s-")


@pytest.mark.ac("E18-AC-15")
def test_resume_refuses_an_ended_job_and_an_unknown_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = factory_repo(tmp_path)
    job = new(repo, monkeypatch, capsys, "Finished")
    assert call(repo, monkeypatch, capsys, "claim", job, "--session", "s-a")[0] == 0
    code, _, err = call(
        repo, monkeypatch, capsys, "set", job, "--session", "s-a", "--status", "done"
    )
    assert code == 0, err
    assert call(repo, monkeypatch, capsys, "resume", job, "--session", "s-a")[0] == 1
    assert call(repo, monkeypatch, capsys, "resume", "job-404", "--session", "s-a")[0] == 2


@pytest.mark.ac("E18-AC-15")
def test_a_job_with_no_runner_jobs_and_no_worktree_still_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = factory_repo(tmp_path)
    job = new(repo, monkeypatch, capsys, "Fresh", "--task", TASK)
    data = resume_json(repo, monkeypatch, capsys, job, "--session", "s-b")
    assert data["runner_jobs"] == []
    assert decimal.Decimal(data["cost"]["usd"]) == 0
    where = data["where"]
    assert (where["branch"], where["worktree"], where["rebuild"]) == ("", "", [])
    assert where["notes"], "it says there is nowhere to resume in"
    assert data["state"]["source"] == "none"
    assert data["state"]["handoff"] is None


@pytest.mark.ac("E18-AC-15")
def test_resume_runs_as_a_real_process_under_python_i_s(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    s = scene(tmp_path, monkeypatch, capsys)
    script = REPO_ROOT / "kit" / ".factory" / "control" / "jobs.py"
    done = subprocess.run(
        [PY, "-I", "-S", str(script), "resume", s.job, "--session", "s-b", "--json"],
        cwd=s.worktree,
        capture_output=True,
        encoding="utf-8",
        check=False,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr
    data = json.loads(done.stdout)
    assert data["state"]["next"] == NEXT


# --- AC-16: a worktree that has gone, and a branch that has gone too ---------------------------


@pytest.mark.ac("E18-AC-16")
def test_a_gone_worktree_gives_the_command_that_rebuilds_it_from_its_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    s = scene(tmp_path, monkeypatch, capsys)
    commit_state(s.worktree)
    git(s.repo, "worktree", "remove", "--force", str(s.worktree))
    assert not s.worktree.exists()
    data = resume_json(s.repo, monkeypatch, capsys, s.job, "--session", "s-b")
    where = data["where"]
    assert (where["branch_exists"], where["worktree_exists"]) == (True, False)
    assert where["rebuild"], "the commands that rebuild it"
    last = where["rebuild"][-1]
    assert last[:3] == ["git", "worktree", "add"]
    assert (real(last[3]), last[4]) == (real(s.worktree), s.branch)
    assert any("gone" in note for note in where["notes"])
    for argv in where["rebuild"]:
        subprocess.run(argv, cwd=s.repo, check=True, capture_output=True)
    assert s.worktree.is_dir()
    again = resume_json(s.repo, monkeypatch, capsys, s.job, "--session", "s-b")
    assert again["where"]["worktree_exists"] is True
    assert again["state"]["source"] == "worktree"
    assert again["state"]["next"] == NEXT


@pytest.mark.ac("E18-AC-16")
def test_a_worktree_folder_deleted_by_hand_is_pruned_and_rebuilt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    s = scene(tmp_path, monkeypatch, capsys)
    commit_state(s.worktree)
    shutil.rmtree(s.worktree)  # git still lists it, so `git worktree add` alone would refuse
    where = resume_json(s.repo, monkeypatch, capsys, s.job, "--session", "s-b")["where"]
    assert where["worktree_exists"] is False
    assert where["rebuild"][0] == ["git", "worktree", "prune"]
    assert where["rebuild"][-1][:3] == ["git", "worktree", "add"]
    for argv in where["rebuild"]:
        subprocess.run(argv, cwd=s.repo, check=True, capture_output=True)
    assert (s.worktree / ".agentic" / "tasks" / f"{TASK}.md").is_file()


@pytest.mark.ac("E18-AC-16")
def test_a_gone_worktrees_task_and_handoff_come_from_its_branchs_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    s = scene(tmp_path, monkeypatch, capsys)
    commit_state(s.worktree)
    uncommitted = body_file(tmp_path, "Never committed.", "uncommitted.md")
    state(s.worktree, "handoff", TASK, "--from", "session A", "--body-file", str(uncommitted))
    git(s.repo, "worktree", "remove", "--force", str(s.worktree))
    found = resume_json(s.repo, monkeypatch, capsys, s.job, "--session", "s-b")["state"]
    assert (found["source"], found["place"]) == ("branch", s.branch)
    assert (found["phase"], found["active_task"]) == ("build", TASK)
    assert found["task"]["status"] == "in-progress"
    assert [f["summary"] for f in found["task"]["open_findings"]] == ["The lexer drops tabs"]
    assert found["next"] == NEXT, "the newest committed handoff"
    assert NEXT in found["handoff"]["body"]
    assert "Never committed." not in json.dumps(found)


@pytest.mark.ac("E18-AC-16")
def test_a_gone_worktree_says_so_as_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    s = scene(tmp_path, monkeypatch, capsys)
    commit_state(s.worktree)
    git(s.repo, "worktree", "remove", "--force", str(s.worktree))
    code, out, err = call(s.repo, monkeypatch, capsys, "resume", s.job, "--session", "s-b")
    assert code == 0, err
    assert "gone" in out
    assert "git worktree add" in out
    assert s.branch in out
    assert NEXT in out


@pytest.mark.ac("E18-AC-16")
def test_a_gone_worktree_and_branch_exit_0_with_what_the_index_still_has(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    s = scene(tmp_path, monkeypatch, capsys)
    resume_json(s.repo, monkeypatch, capsys, s.job, "--session", "s-b")  # the index saw it all
    git(s.repo, "worktree", "remove", "--force", str(s.worktree))
    git(s.repo, "branch", "-D", s.branch)
    data = resume_json(s.repo, monkeypatch, capsys, s.job, "--session", "s-b")
    where = data["where"]
    assert (where["branch_exists"], where["worktree_exists"], where["rebuild"]) == (
        False,
        False,
        [],
    )
    assert any("gone" in note for note in where["notes"])
    assert data["job"]["id"] == s.job
    assert [r["id"] for r in data["runner_jobs"]] == [s.first, s.second]
    assert data["cost"]["usd"] == "0.75"
    found = data["state"]
    assert found["source"] == "index"
    assert (found["phase"], found["active_task"]) == ("build", TASK)
    assert found["task"]["status"] == "in-progress"
    assert found["next"] == NEXT
    code, out, err = call(s.repo, monkeypatch, capsys, "resume", s.job, "--session", "s-b")
    assert code == 0, err
    assert "gone" in out
    assert s.branch in out


@pytest.mark.ac("E18-AC-16")
def test_after_a_rebuild_a_gone_worktree_and_branch_still_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    s = scene(tmp_path, monkeypatch, capsys)
    git(s.repo, "worktree", "remove", "--force", str(s.worktree))
    git(s.repo, "branch", "-D", s.branch)
    assert call(s.repo, monkeypatch, capsys, "rebuild")[0] == 0
    data = resume_json(s.repo, monkeypatch, capsys, s.job, "--session", "s-b")
    assert data["state"]["source"] == "none"
    assert data["state"]["handoff"] is None
    assert [r["id"] for r in data["runner_jobs"]] == [s.first, s.second]


# --- AC-19: the glossary, CI, and every E18 AC has a test --------------------------------------


@pytest.mark.ac("E18-AC-19")
def test_the_glossary_defines_job_runner_job_and_lease() -> None:
    text = (REPO_ROOT / "docs" / "GLOSSARY.md").read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if line.startswith("| ")]
    terms = {row.split("|")[1].strip().strip("*`").lower(): row for row in rows[2:]}
    assert {"job", "runner job", "lease"} <= set(terms), sorted(terms)
    assert "jobs.py" in terms["job"]
    assert "run.py" in terms["runner job"]
    assert "heartbeat" in terms["lease"].lower()


@pytest.mark.ac("E18-AC-19")
def test_e18_spec_defines_ac_01_to_ac_19() -> None:
    assert spec_ac_ids("E18") == {f"E18-AC-{n:02d}" for n in range(1, 20)}


@pytest.mark.ac("E18-AC-19")
def test_every_e18_ac_has_a_test(request: pytest.FixtureRequest) -> None:
    missing = spec_ac_ids("E18") - request.config.stash[COLLECTED_AC_IDS]
    assert not missing, f"E18 ACs with no test: {sorted(missing)}"


@pytest.mark.ac("E18-AC-19")
def test_ci_runs_the_index_tests_on_ubuntu_macos_and_windows() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "factory-gate.yml").read_text(
        encoding="utf-8"
    )
    for os_name in ("ubuntu-latest", "macos-latest", "windows-latest"):
        assert os_name in workflow
    for line in (ln for ln in workflow.splitlines() if "--checks" in ln):
        assert "tests" in line.split("--checks", 1)[1], f"tests must run there: {line.strip()}"
    tests = sorted(p.name for p in (REPO_ROOT / "tests").glob("test_jobs_*.py"))
    assert {"test_jobs_resume.py", "test_jobs_done_when.py"} <= set(tests)
