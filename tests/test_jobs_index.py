"""E18/T2: what the index holds, refreshing it on read, and `list`.

Covers E18 AC-05, the read part of AC-06, and AC-10. Expectations come from the E18 spec and the
design note ("The index", "Readers"), not from the implementation. The runner's view is pinned
against `run.py status --json`, as the design note asks.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path

import pytest

import jobs
from tests._daemon import Clock, FakeStart, drop, make_daemon
from tests._jobs import api_repo, call, jobs_repo, new, record_path
from tests._jobs_index import (
    add_worktree,
    by_id,
    factory_repo,
    listing,
    real,
    run_py,
    runner_status,
    state,
    submit,
    worktree_entry,
    write_handoff,
)
from tests._runner import job_dir

PY = sys.executable


# --- AC-05: what the index holds ---------------------------------------------------------------


@pytest.mark.ac("E18-AC-05")
def test_list_json_has_the_five_sections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    data = listing(repo, monkeypatch, capsys)
    assert set(data) == {"jobs", "runner_jobs", "usage", "worktrees", "problems"}
    assert data["jobs"] == []
    assert data["runner_jobs"] == []
    assert [real(w["path"]) for w in data["worktrees"]] == [real(repo)]


@pytest.mark.ac("E18-AC-05")
def test_every_job_record_is_listed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    first = new(repo, monkeypatch, capsys, "First", "--task", "E31-T1", "--branch", "b1")
    second = new(repo, monkeypatch, capsys, "Second", "--track", "lite")
    found = by_id(listing(repo, monkeypatch, capsys)["jobs"])
    assert set(found) == {first, second}
    entry = found[first]
    for key, value in {
        "title": "First",
        "track": "full",
        "phase": "spec",
        "status": "open",
        "task": "E31-T1",
        "tasks": ["E31-T1"],
        "branch": "b1",
        "owner": "",
        "state": "unclaimed",
        "lease": None,
    }.items():
        assert entry[key] == value, key
    assert entry["stale"] is False
    assert found[second]["track"] == "lite"


@pytest.mark.ac("E18-AC-05")
def test_a_runner_job_is_indexed_as_run_py_status_shows_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Design note: jobs.py reads the runner's files itself, pinned to `run.py status --json`."""
    repo = jobs_repo(tmp_path)
    queued = submit(repo, monkeypatch, capsys, "--task", "E31-T1", "--", PY, "-c", "pass")
    opened = submit(repo, monkeypatch, capsys, "--open", "--", PY, "-c", "print(1)")
    assert run_py(repo, monkeypatch, capsys, "send", opened, "--", PY, "-c", "print(2)")[0] == 0
    assert run_py(repo, monkeypatch, capsys, "close", opened)[0] == 0
    ran = submit(repo, monkeypatch, capsys, "--", PY, "-c", "pass")
    assert run_py(repo, monkeypatch, capsys, "usage", ran, "--usd", "0.25")[0] == 0
    start, clock = FakeStart(), Clock()
    daemon = make_daemon(repo, start)
    clock.tick(daemon, 2)
    for call_ in start.for_job(ran):
        call_.proc.finish(0)
    clock.tick(daemon, 2)
    found = by_id(listing(repo, monkeypatch, capsys)["runner_jobs"])
    assert set(found) == {queued, opened, ran}
    for job in (queued, opened, ran):
        view = dict(found[job])
        view.pop("belongs_to")
        assert view == runner_status(repo, monkeypatch, capsys, job), job


@pytest.mark.ac("E18-AC-05")
def test_a_runner_job_belongs_to_the_live_job_holding_its_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    job = new(repo, monkeypatch, capsys, "Owner", "--task", "E31-T1")
    mine = submit(repo, monkeypatch, capsys, "--task", "E31-T1", "--", PY, "-c", "pass")
    other = submit(repo, monkeypatch, capsys, "--task", "E99-T9", "--", PY, "-c", "pass")
    found = by_id(listing(repo, monkeypatch, capsys)["runner_jobs"])
    assert found[mine]["belongs_to"] == job
    assert found[other]["belongs_to"] == ""


@pytest.mark.ac("E18-AC-05")
def test_a_runner_job_belongs_to_a_job_through_any_of_its_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = jobs_repo(tmp_path)
    repo = api_repo(root)
    job = jobs.new_job(repo, "Slices", task="E31-T1")["id"]
    jobs.claim(repo, jobs.load_config(repo), job, "s-a")
    jobs.set_job(repo, job, "s-a", task="E31-T2")
    old = submit(root, monkeypatch, capsys, "--task", "E31-T1", "--", PY, "-c", "pass")
    current = submit(root, monkeypatch, capsys, "--task", "E31-T2", "--", PY, "-c", "pass")
    found = by_id(listing(root, monkeypatch, capsys)["runner_jobs"])
    assert found[old]["belongs_to"] == job
    assert found[current]["belongs_to"] == job


@pytest.mark.ac("E18-AC-05")
def test_every_usage_report_is_indexed_with_its_amount_and_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    job = submit(repo, monkeypatch, capsys, "--", PY, "-c", "pass")
    before = time.time()
    for amount in ("0.10", "0.25", "1.5"):
        assert run_py(repo, monkeypatch, capsys, "usage", job, "--usd", amount)[0] == 0
    after = time.time()
    usage = [u for u in listing(repo, monkeypatch, capsys)["usage"] if u["runner_job"] == job]
    assert sorted(u["usd"] for u in usage) == ["0.10", "0.25", "1.5"], "exact decimals, as text"
    for report in usage:
        at = dt.datetime.fromisoformat(report["at"]).timestamp()
        assert before - 1 <= at <= after + 1


@pytest.mark.ac("E18-AC-05")
def test_each_worktrees_state_is_indexed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = factory_repo(tmp_path)
    side = add_worktree(repo, tmp_path / "side", "side")
    state(side, "task", "new", "E31-T1", "First slice")
    state(side, "task", "new", "E31-T2", "Second slice")
    state(side, "start", "E31-T1", "--phase", "build")
    state(side, "finding", "add", "E31-T1", "--severity", "major", "A real problem")
    state(side, "block", "waiting for review")
    write_handoff(side, "E31-T1", "Old next step.", tmp_path)
    time.sleep(1.1)  # handoffs are named by the second
    write_handoff(side, "E31-T1", "Fix the parser next.", tmp_path)
    data = listing(repo, monkeypatch, capsys)
    entry = worktree_entry(data, side)
    assert entry["branch"] == "side"
    assert len(entry["head"]) == 40
    assert entry["phase"] == "build"
    assert entry["active_task"] == "E31-T1"
    assert entry["blockers"] == ["waiting for review"]
    tasks = {t["id"]: t for t in entry["tasks"]}
    assert set(tasks) == {"E31-T1", "E31-T2"}
    assert tasks["E31-T1"]["status"] == "in-progress"
    assert tasks["E31-T1"]["review_round"] == 0
    assert [f["summary"] for f in tasks["E31-T1"]["open_findings"]] == ["A real problem"]
    assert tasks["E31-T1"]["next"] == "Fix the parser next."
    assert Path(tasks["E31-T1"]["handoff"]).is_file()
    assert tasks["E31-T2"]["handoff"] == ""
    assert tasks["E31-T2"]["next"] == ""
    main_entry = worktree_entry(data, repo)
    assert main_entry["branch"] == "main"
    assert main_entry["phase"] == "spec"


@pytest.mark.ac("E18-AC-05")
def test_a_worktree_with_broken_state_is_a_problem_not_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = factory_repo(tmp_path)
    side = add_worktree(repo, tmp_path / "side", "side")
    (side / ".agentic" / "STATE.md").write_text("+++\nphase = [broken\n+++\n", encoding="utf-8")
    data = listing(repo, monkeypatch, capsys)
    assert worktree_entry(data, side)["phase"] == ""
    assert any("STATE.md" in p["path"] for p in data["problems"]), data["problems"]


# --- AC-06 (reads): every read refreshes from the files ---------------------------------------


@pytest.mark.ac("E18-AC-06")
def test_list_and_show_see_a_state_py_write_with_no_jobs_py_call_between(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = factory_repo(tmp_path)
    side = add_worktree(repo, tmp_path / "side", "side")
    state(side, "task", "new", "E31-T1", "Slice")
    job = new(repo, monkeypatch, capsys, "Job", "--task", "E31-T1", "--worktree", str(side))
    shown = json.loads(call(repo, monkeypatch, capsys, "show", job, "--json")[1])
    assert real(shown["worktree_state"]["path"]) == real(side)
    assert {t["id"]: t for t in shown["worktree_state"]["tasks"]}["E31-T1"]["status"] == "todo"
    state(side, "start", "E31-T1", "--phase", "test")
    state(side, "task", "set", "E31-T1", "--status", "in-review")
    shown = json.loads(call(repo, monkeypatch, capsys, "show", job, "--json")[1])
    assert shown["worktree_state"]["phase"] == "test"
    assert {t["id"]: t for t in shown["worktree_state"]["tasks"]}["E31-T1"]["status"] == (
        "in-review"
    )
    entry = worktree_entry(listing(repo, monkeypatch, capsys), side)
    assert entry["active_task"] == "E31-T1"


@pytest.mark.ac("E18-AC-06")
def test_show_lists_the_runner_jobs_that_belong_to_the_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    job = new(repo, monkeypatch, capsys, "Job", "--task", "E31-T1")
    mine = submit(repo, monkeypatch, capsys, "--task", "E31-T1", "--", PY, "-c", "pass")
    submit(repo, monkeypatch, capsys, "--task", "E99-T9", "--", PY, "-c", "pass")
    shown = json.loads(call(repo, monkeypatch, capsys, "show", job, "--json")[1])
    assert [r["id"] for r in shown["runner_jobs"]] == [mine]
    assert shown["worktree_state"] is None, "no worktree named, and no runner job has one yet"


@pytest.mark.ac("E18-AC-06")
def test_show_takes_the_worktree_from_the_newest_runner_job_when_the_job_names_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = factory_repo(tmp_path)
    job = new(repo, monkeypatch, capsys, "Job", "--task", "E31-T1")
    ran = submit(repo, monkeypatch, capsys, "--open", "--task", "E31-T1")
    start, clock = FakeStart(), Clock()
    daemon = make_daemon(repo, start)
    clock.tick(daemon, 2)
    worktree = Path(runner_status(repo, monkeypatch, capsys, ran)["worktree"])
    assert worktree.is_dir()
    shown = json.loads(call(repo, monkeypatch, capsys, "show", job, "--json")[1])
    assert real(shown["worktree_state"]["path"]) == real(worktree)


@pytest.mark.ac("E18-AC-06")
def test_list_sees_a_record_written_behind_its_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    job = new(repo, monkeypatch, capsys, "Before")
    path = record_path(repo, job)
    path.write_text(path.read_text(encoding="utf-8").replace('"Before"', '"After"'), "utf-8")
    assert by_id(listing(repo, monkeypatch, capsys)["jobs"])[job]["title"] == "After"


# --- AC-10: list and its states ---------------------------------------------------------------


@pytest.mark.ac("E18-AC-10")
def test_list_shows_each_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path, "[jobs]\nlease_minutes = 0.02\n")  # 1.2 seconds
    unclaimed = new(repo, monkeypatch, capsys, "Unclaimed")
    crashed = new(repo, monkeypatch, capsys, "Crashed")
    done = new(repo, monkeypatch, capsys, "Done")
    cancelled = new(repo, monkeypatch, capsys, "Cancelled")
    for job in (crashed, done, cancelled):
        assert call(repo, monkeypatch, capsys, "claim", job, "--session", "s-a")[0] == 0
    for job, status in ((done, "done"), (cancelled, "cancelled")):
        args = ("set", job, "--session", "s-a", "--status", status)
        assert call(repo, monkeypatch, capsys, *args)[0] == 0
    time.sleep(1.5)
    claimed = new(repo, monkeypatch, capsys, "Claimed")
    assert call(repo, monkeypatch, capsys, "claim", claimed, "--session", "s-b")[0] == 0
    found = by_id(listing(repo, monkeypatch, capsys)["jobs"])
    assert found[unclaimed]["state"] == "unclaimed"
    assert found[claimed]["state"] == "claimed"
    assert found[crashed]["state"] == "crashed"
    assert found[done]["state"] == "done"
    assert found[cancelled]["state"] == "cancelled"
    lease = found[claimed]["lease"]
    assert lease["session"] == "s-b"
    assert dt.datetime.fromisoformat(lease["expires"]).timestamp() > time.time()
    assert found[crashed]["lease"]["session"] == "s-a"
    assert found[unclaimed]["lease"] is None


@pytest.mark.ac("E18-AC-10")
def test_list_filters_by_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    open_job = new(repo, monkeypatch, capsys, "Open")
    blocked = new(repo, monkeypatch, capsys, "Blocked")
    assert call(repo, monkeypatch, capsys, "claim", blocked, "--session", "s-a")[0] == 0
    args = ("set", blocked, "--session", "s-a", "--status", "blocked")
    assert call(repo, monkeypatch, capsys, *args)[0] == 0
    only = listing(repo, monkeypatch, capsys, "--status", "blocked")["jobs"]
    assert [j["id"] for j in only] == [blocked]
    only = listing(repo, monkeypatch, capsys, "--status", "open")["jobs"]
    assert [j["id"] for j in only] == [open_job]
    assert call(repo, monkeypatch, capsys, "list", "--status", "running")[0] == 2


@pytest.mark.ac("E18-AC-10")
def test_list_text_has_one_line_per_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    first = new(repo, monkeypatch, capsys, "First title")
    second = new(repo, monkeypatch, capsys, "Second title")
    assert call(repo, monkeypatch, capsys, "claim", second, "--session", "s-b")[0] == 0
    code, out, err = call(repo, monkeypatch, capsys, "list")
    assert code == 0, err
    lines = [line for line in out.splitlines() if line.strip()]
    rows = {line.split()[0]: line for line in lines if line.split()[0] in (first, second)}
    assert set(rows) == {first, second}
    assert "unclaimed" in rows[first]
    assert "First title" in rows[first]
    assert "claimed" in rows[second]
    assert "s-b" in rows[second]


@pytest.mark.ac("E18-AC-10")
def test_jobs_are_listed_oldest_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = api_repo(jobs_repo(tmp_path))
    for n, when in enumerate((300.0, 100.0, 200.0), start=1):
        jobs.new_job(repo, f"Job {n}", job_id=f"job-{n}", now=1_800_000_000.0 + when)
    root = repo.main
    ids = [j["id"] for j in listing(root, monkeypatch, capsys)["jobs"]]
    assert ids == ["job-2", "job-3", "job-1"]


@pytest.mark.ac("E18-AC-05")
def test_a_malformed_runner_request_is_indexed_by_its_failed_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    drop(repo, "bad-one.toml", 'version = 1\nid = "bad-one"\n')
    daemon = make_daemon(repo, FakeStart())
    Clock().tick(daemon, 2)
    found = by_id(listing(repo, monkeypatch, capsys)["runner_jobs"])
    assert found["bad-one"]["status"] == "failed"
    assert found["bad-one"]["reason"]


@pytest.mark.ac("E18-AC-05")
def test_a_usage_file_that_is_not_a_number_is_left_out_as_run_py_leaves_it_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    job = submit(repo, monkeypatch, capsys, "--", PY, "-c", "pass")
    assert run_py(repo, monkeypatch, capsys, "usage", job, "--usd", "2")[0] == 0
    folder = job_dir(repo, job) / "usage"
    (folder / "1-junk.usd").write_text("lots\n", encoding="utf-8")
    (folder / ".tmp-1.usd").write_text("9\n", encoding="utf-8")
    (folder / "2-note.txt").write_text("9\n", encoding="utf-8")
    data = listing(repo, monkeypatch, capsys)
    assert [u["usd"] for u in data["usage"]] == ["2"]
    view = by_id(data["runner_jobs"])[job]
    assert view["usd"] == runner_status(repo, monkeypatch, capsys, job)["usd"] == 2.0


@pytest.mark.ac("E18-AC-05")
def test_a_broken_task_file_is_a_problem_and_the_others_are_still_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = factory_repo(tmp_path)
    side = add_worktree(repo, tmp_path / "side", "side")
    state(side, "task", "new", "E31-T1", "Good")
    state(side, "task", "new", "E31-T2", "Broken")
    (side / ".agentic" / "tasks" / "E31-T2.md").write_text("no front matter\n", encoding="utf-8")
    data = listing(repo, monkeypatch, capsys)
    assert [t["id"] for t in worktree_entry(data, side)["tasks"]] == ["E31-T1"]
    assert any(p["path"].endswith("E31-T2.md") for p in data["problems"]), data["problems"]


@pytest.mark.ac("E18-AC-05")
def test_a_worktree_without_state_files_has_empty_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    side = add_worktree(repo, tmp_path / "side", "side")
    entry = worktree_entry(listing(repo, monkeypatch, capsys), side)
    assert (entry["phase"], entry["active_task"], entry["blockers"], entry["tasks"]) == (
        "",
        "",
        [],
        [],
    )
