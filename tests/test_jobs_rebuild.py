"""E18/T2: rebuilding the index, damaged and too-new indexes, migrations, and leases lost with it.

Covers E18 AC-08, AC-09 and AC-12's beat after a rebuild. Expectations come from the E18 spec and
the design note ("The index", ADR 0051), not from the implementation.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

import jobs
from tests._daemon import Clock, FakeStart, make_daemon
from tests._jobs import call, index_path, jobs_repo, new, record_path, work_dir
from tests._jobs_index import (
    FIXTURES,
    add_worktree,
    by_id,
    factory_repo,
    listing,
    run_py,
    set_user_version,
    state,
    submit,
    user_version,
    write_handoff,
)

PY = sys.executable


def busy_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> tuple[Path, list[str]]:
    """A repo with jobs (one claimed), runner jobs (one run), usage and a worktree's state."""
    repo = factory_repo(tmp_path)
    side = add_worktree(repo, tmp_path / "side", "side")
    state(side, "task", "new", "E31-T1", "Slice")
    state(side, "start", "E31-T1", "--phase", "build")
    write_handoff(side, "E31-T1", "Carry on.", tmp_path)
    first = new(repo, monkeypatch, capsys, "First", "--task", "E31-T1", "--worktree", str(side))
    second = new(repo, monkeypatch, capsys, "Second")
    assert call(repo, monkeypatch, capsys, "claim", first, "--session", "s-a")[0] == 0
    ran = submit(repo, monkeypatch, capsys, "--task", "E31-T1", "--", PY, "-c", "pass")
    submit(repo, monkeypatch, capsys, "--open", "--task", "E99-T1")
    assert run_py(repo, monkeypatch, capsys, "usage", ran, "--usd", "0.75")[0] == 0
    start, clock = FakeStart(), Clock()
    daemon = make_daemon(repo, start)
    clock.tick(daemon, 2)
    for started in start.calls:
        started.proc.finish(0)
    clock.tick(daemon, 2)
    return repo, [first, second]


def without_live(data: dict[str, Any]) -> dict[str, Any]:
    """The listing minus what a lost index may lose: leases (and so the states they give)."""
    out = dict(data)
    out["jobs"] = [
        {k: v for k, v in job.items() if k not in ("lease", "state")} for job in data["jobs"]
    ]
    return out


# --- AC-08: rebuild ---------------------------------------------------------------------------


@pytest.mark.ac("E18-AC-08")
@pytest.mark.parametrize("damage", ["delete", "junk", "truncate"])
def test_rebuild_restores_everything_but_live_leases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    damage: str,
) -> None:
    repo, (first, _) = busy_repo(tmp_path, monkeypatch, capsys)
    before = listing(repo, monkeypatch, capsys)
    assert by_id(before["jobs"])[first]["state"] == "claimed"
    assert before["runner_jobs"] and before["usage"]
    index = index_path(repo)
    if damage == "delete":
        index.unlink()
    elif damage == "junk":
        index.write_bytes(b"this is not a database at all " * 200)
    else:
        size = index.stat().st_size
        assert size > 8192
        with index.open("r+b") as f:
            f.truncate(size // 2)
    code, _, err = call(repo, monkeypatch, capsys, "rebuild")
    assert code == 0, err
    after = listing(repo, monkeypatch, capsys)
    assert without_live(after) == without_live(before)
    assert by_id(after["jobs"])[first]["state"] == "unclaimed", "the live lease is gone"


@pytest.mark.ac("E18-AC-08")
def test_a_rebuild_of_a_healthy_index_keeps_live_leases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, (first, _) = busy_repo(tmp_path, monkeypatch, capsys)
    before = listing(repo, monkeypatch, capsys)
    assert call(repo, monkeypatch, capsys, "rebuild")[0] == 0
    after = listing(repo, monkeypatch, capsys)
    assert after == before
    assert by_id(after["jobs"])[first]["lease"]["session"] == "s-a"


@pytest.mark.ac("E18-AC-08")
@pytest.mark.parametrize("damage", ["junk", "truncate"])
def test_any_command_rebuilds_a_damaged_index_and_warns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    damage: str,
) -> None:
    repo, (first, second) = busy_repo(tmp_path, monkeypatch, capsys)
    index = index_path(repo)
    if damage == "junk":
        index.write_bytes(b"\x00junk" * 4000)
    else:
        with index.open("r+b") as f:
            f.truncate(index.stat().st_size // 2)
    code, _, err = call(repo, monkeypatch, capsys, "show", second, "--json")
    assert code == 0, err
    assert "damaged" in err
    assert list(index.parent.glob("index.sqlite.damaged-*")), "the damaged file is kept aside"
    assert by_id(listing(repo, monkeypatch, capsys)["jobs"]).keys() == {first, second}
    code, _, err = call(repo, monkeypatch, capsys, "claim", second, "--session", "s-z")
    assert code == 0, err


@pytest.mark.ac("E18-AC-08")
def test_a_damaged_record_is_a_problem_and_rebuild_carries_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    good = new(repo, monkeypatch, capsys, "Good")
    bad = new(repo, monkeypatch, capsys, "Bad")
    record_path(repo, bad).write_text("not [toml\n", encoding="utf-8")
    code, _, err = call(repo, monkeypatch, capsys, "rebuild")
    assert code == 0, err
    data = listing(repo, monkeypatch, capsys)
    assert [j["id"] for j in data["jobs"]] == [good]
    assert [p["path"] for p in data["problems"]] == [str(record_path(repo, bad))]
    assert data["problems"][0]["problem"]


@pytest.mark.ac("E18-AC-08")
def test_rebuild_drops_the_lease_of_a_job_that_no_longer_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    gone = new(repo, monkeypatch, capsys, "Gone")
    assert call(repo, monkeypatch, capsys, "claim", gone, "--session", "s-a")[0] == 0
    record_path(repo, gone).unlink()
    shutil.rmtree(work_dir(repo) / ".ids" / gone)
    assert call(repo, monkeypatch, capsys, "rebuild")[0] == 0
    again = new(repo, monkeypatch, capsys, "Same id again", "--id", gone)
    assert again == gone
    code, _, err = call(repo, monkeypatch, capsys, "claim", gone, "--session", "s-b")
    assert code == 0, err


@pytest.mark.ac("E18-AC-08")
def test_rebuild_reports_what_it_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = busy_repo(tmp_path, monkeypatch, capsys)
    code, out, err = call(repo, monkeypatch, capsys, "rebuild")
    assert code == 0, err
    assert "2 jobs" in out
    assert "2 runner jobs" in out
    assert "3 worktrees" in out, "main, side, and the open runner job's"


# --- AC-09: the schema version and migrations ----------------------------------------------


@pytest.mark.ac("E18-AC-09")
def test_a_version_0_index_is_migrated_and_filled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    job = new(repo, monkeypatch, capsys, "Kept")
    shutil.copyfile(FIXTURES / "index-v0.sqlite", index_path(repo))
    assert user_version(repo) == 0
    assert [j["id"] for j in listing(repo, monkeypatch, capsys)["jobs"]] == [job]
    assert user_version(repo) == jobs.SCHEMA_VERSION
    assert jobs.SCHEMA_VERSION >= 2


@pytest.mark.ac("E18-AC-09")
def test_a_version_1_index_is_migrated_and_keeps_its_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The fixture was made by E18-T1's jobs.py: job-1 leased to s-fixture until 2096."""
    repo = jobs_repo(tmp_path)
    assert new(repo, monkeypatch, capsys, "The fixture's job") == "job-1"
    shutil.copyfile(FIXTURES / "index-v1.sqlite", index_path(repo))
    assert user_version(repo) == 1
    code, _, err = call(repo, monkeypatch, capsys, "claim", "job-1", "--session", "s-other")
    assert code == 1
    assert "s-fixture" in err
    assert user_version(repo) == jobs.SCHEMA_VERSION
    assert by_id(listing(repo, monkeypatch, capsys)["jobs"])["job-1"]["state"] == "claimed"


@pytest.mark.ac("E18-AC-09")
@pytest.mark.parametrize(
    "args",
    [
        ("list",),
        ("show", "job-1"),
        ("claim", "job-1", "--session", "s-a"),
        ("rebuild",),
        ("new", "Another"),
    ],
)
def test_a_newer_index_exits_2_names_both_versions_and_changes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    args: tuple[str, ...],
) -> None:
    repo = jobs_repo(tmp_path)
    assert new(repo, monkeypatch, capsys, "Present") == "job-1"
    set_user_version(repo, 99)
    index_before = index_path(repo).read_bytes()
    records_before = sorted(p.name for p in work_dir(repo).glob("*.toml"))
    code, _, err = call(repo, monkeypatch, capsys, *args)
    assert code == 2
    assert "99" in err
    assert str(jobs.SCHEMA_VERSION) in err
    assert index_path(repo).read_bytes() == index_before
    assert sorted(p.name for p in work_dir(repo).glob("*.toml")) == records_before


# --- AC-12: the owner takes a lease back after a rebuild -------------------------------------


@pytest.mark.ac("E18-AC-12")
def test_after_a_rebuild_from_nothing_the_owner_beats_the_lease_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    job = new(repo, monkeypatch, capsys)
    assert call(repo, monkeypatch, capsys, "claim", job, "--session", "s-a")[0] == 0
    index_path(repo).unlink()
    assert call(repo, monkeypatch, capsys, "rebuild")[0] == 0
    assert by_id(listing(repo, monkeypatch, capsys)["jobs"])[job]["state"] == "unclaimed"
    assert call(repo, monkeypatch, capsys, "beat", job, "--session", "s-b")[0] == 1
    code, _, err = call(repo, monkeypatch, capsys, "beat", job, "--session", "s-a")
    assert code == 0, err
    entry = by_id(listing(repo, monkeypatch, capsys)["jobs"])[job]
    assert (entry["state"], entry["lease"]["session"]) == ("claimed", "s-a")
