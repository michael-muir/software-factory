"""E18/T1: `jobs.py`, job records, `new`, `show` and `set`.

Covers E18 AC-01 to AC-04. Expectations come from the E18 spec (and its change note on the one
job E13 and E18 share) and the design note ("Job records", "API for E13 and the runner"), not
from the implementation.
"""

from __future__ import annotations

import ast
import datetime as dt
import inspect
import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import jobs
from tests._jobs import (
    JOBS_PY,
    MINUTE,
    T0,
    api_repo,
    call,
    git,
    index_path,
    jobs_repo,
    new,
    record,
    record_path,
    run_jobs,
    show,
    work_dir,
)

RECORD_KEYS = {
    "version",
    "id",
    "title",
    "track",
    "phase",
    "status",
    "task",
    "tasks",
    "branch",
    "worktree",
    "owner",
    "created",
    "updated",
}


def claimed(repo: Path, job: str, session: str = "s-one", now: float = T0) -> jobs.Lease:
    r = api_repo(repo)
    return jobs.claim(r, jobs.load_config(r), job, session, now=now)


# --- AC-01: the tool --------------------------------------------------------------------------


@pytest.mark.ac("E18-AC-01")
def test_jobs_imports_only_the_standard_library() -> None:
    tree = ast.parse(JOBS_PY.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    assert names, "jobs.py imports something"
    assert names <= set(sys.stdlib_module_names) | {"__future__"}, names


@pytest.mark.ac("E18-AC-01")
def test_jobs_runs_isolated_with_python_i_s(tmp_path: Path) -> None:
    repo = jobs_repo(tmp_path)
    made = run_jobs(repo, "new", "Isolated", isolated=True)
    assert made.returncode == 0, made.stderr
    job = made.stdout.strip()
    shown = run_jobs(repo, "show", job, "--json", isolated=True)
    assert shown.returncode == 0, shown.stderr
    assert json.loads(shown.stdout)["title"] == "Isolated"


@pytest.mark.ac("E18-AC-01")
def test_the_same_records_and_index_from_a_subfolder_and_a_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    job = new(repo, monkeypatch, capsys, "Seen everywhere")
    sub = repo / "a" / "b"
    sub.mkdir(parents=True)
    other = tmp_path / "other-worktree"
    git(repo, "worktree", "add", "-q", "-b", "side", str(other))
    for cwd in (sub, other):
        assert show(cwd, monkeypatch, capsys, job)["title"] == "Seen everywhere"
    second = new(other, monkeypatch, capsys, "Made in a worktree")
    assert record_path(repo, second).is_file(), "one work/ folder for every worktree"
    assert index_path(repo).is_file()
    assert not (other / "factory").exists()


@pytest.mark.ac("E18-AC-01")
def test_the_index_is_created_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    job = new(repo, monkeypatch, capsys)
    assert index_path(repo).is_file()
    index_path(repo).unlink()
    code, _, err = call(repo, monkeypatch, capsys, "claim", job, "--session", "s-a")
    assert code == 0, err
    assert index_path(repo).is_file()


@pytest.mark.ac("E18-AC-01")
def test_nothing_the_tool_writes_is_seen_by_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    job = new(repo, monkeypatch, capsys)
    assert call(repo, monkeypatch, capsys, "claim", job, "--session", "s-a")[0] == 0
    assert git(repo, "status", "--porcelain", "--ignored") == ""


@pytest.mark.ac("E18-AC-01")
def test_outside_a_git_repo_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    code, _, err = call(plain, monkeypatch, capsys, "new", "x")
    assert code == 2
    assert "git" in err


@pytest.mark.ac("E18-AC-01")
def test_a_repo_with_no_commit_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "empty"
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    code, _, err = call(root, monkeypatch, capsys, "new", "x")
    assert code == 2
    assert "commit" in err


@pytest.mark.ac("E18-AC-01")
@pytest.mark.parametrize(
    "args",
    [
        ("show", "job-99"),
        ("set", "job-99", "--session", "s-a", "--phase", "design"),
        ("claim", "job-99", "--session", "s-a"),
        ("beat", "job-99", "--session", "s-a"),
        ("release", "job-99", "--session", "s-a"),
    ],
)
def test_an_unknown_job_exits_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    args: tuple[str, ...],
) -> None:
    repo = jobs_repo(tmp_path)
    code, _, err = call(repo, monkeypatch, capsys, *args)
    assert code == 2
    assert "job-99" in err


@pytest.mark.ac("E18-AC-01")
@pytest.mark.parametrize(
    "args",
    [(), ("nonsense",), ("new",), ("show",), ("claim",), ("new", "x", "--bogus")],
)
def test_bad_arguments_exit_2_without_raising(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    args: tuple[str, ...],
) -> None:
    repo = jobs_repo(tmp_path)
    assert call(repo, monkeypatch, capsys, *args)[0] == 2


@pytest.mark.ac("E18-AC-01")
def test_an_invalid_config_exits_2_and_names_the_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path, "[jobs]\nlease_minutes = 0\n")
    code, _, err = call(repo, monkeypatch, capsys, "new", "x")
    assert code == 2
    assert "jobs.lease_minutes" in err


@pytest.mark.ac("E18-AC-01")
def test_a_python_without_sqlite3_exits_2_and_says_so(tmp_path: Path) -> None:
    """Spec assumption 11: a Python built without sqlite3 gets exit 2 and a clear message."""
    repo = jobs_repo(tmp_path)
    script = (
        "import runpy, sys\n"
        "sys.modules['sqlite3'] = None\n"
        f"sys.argv = ['jobs.py', 'new', 'x']\n"
        f"runpy.run_path({str(JOBS_PY)!r}, run_name='__main__')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=repo, capture_output=True, text=True, check=False
    )
    assert result.returncode == 2, result.stderr
    assert "sqlite3" in result.stderr
    assert not work_dir(repo).exists() or not list(work_dir(repo).glob("*.toml"))


# The API E13's driver and run.py build on (design note, "API for E13 and the runner").
API = {
    "find_repo": ["cwd"],
    "load_config": ["repo"],
    "new_job": ["repo", "title", "job_id", "track", "task", "branch", "worktree", "now"],
    "read_job": ["repo", "job_id"],
    "set_job": ["repo", "job_id", "session", "now", "fields"],
    "claim": ["repo", "config", "job_id", "session", "force", "now"],
    "beat": ["repo", "config", "job_id", "session", "now"],
    "release": ["repo", "job_id", "session"],
    "lease_state": ["repo", "job_id", "now"],
    "sidecar_path": ["repo", "job_id", "name"],
    "write_sidecar": ["repo", "job_id", "name", "text", "session", "now"],
}


@pytest.mark.ac("E18-AC-01")
@pytest.mark.parametrize("name", sorted(API))
def test_the_api_for_e13_is_pinned(name: str) -> None:
    params = list(inspect.signature(getattr(jobs, name)).parameters)
    assert params == API[name]


@pytest.mark.ac("E18-AC-01")
def test_the_api_errors_map_to_the_exit_codes() -> None:
    assert issubclass(jobs.UnknownJob, jobs.BadInput)
    assert issubclass(jobs.IndexTooNew, jobs.BadInput)
    assert issubclass(jobs.IndexUnavailable, jobs.Refused)
    assert {"job", "session", "acquired", "expires", "minutes"} <= set(
        inspect.signature(jobs.Lease).parameters
    )


# --- AC-02: new ---------------------------------------------------------------------------------


@pytest.mark.ac("E18-AC-02")
def test_generated_ids_count_up_from_job_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    ids = [new(repo, monkeypatch, capsys, f"Job {n}") for n in range(3)]
    assert ids == ["job-1", "job-2", "job-3"]
    assert [record(repo, job)["id"] for job in ids] == ids


@pytest.mark.ac("E18-AC-02")
def test_a_generated_id_skips_a_given_one_that_is_taken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    assert new(repo, monkeypatch, capsys, "Given", "--id", "job-1") == "job-1"
    assert new(repo, monkeypatch, capsys, "Generated") == "job-2"


@pytest.mark.ac("E18-AC-02")
@pytest.mark.parametrize("job_id", ["a", "e13-full-track", "x" * 30, "0-9"])
def test_a_given_id_is_used(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    job_id: str,
) -> None:
    repo = jobs_repo(tmp_path)
    assert new(repo, monkeypatch, capsys, "Given", "--id", job_id) == job_id
    assert record(repo, job_id)["id"] == job_id


@pytest.mark.ac("E18-AC-02")
@pytest.mark.parametrize("job_id", ["x" * 31, "Job-1", "-a", "a.b", "a_b", "", "a b"])
def test_a_bad_id_exits_2_and_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    job_id: str,
) -> None:
    repo = jobs_repo(tmp_path)
    code, _, err = call(repo, monkeypatch, capsys, "new", "Bad", f"--id={job_id}")
    assert code == 2
    assert "[a-z0-9]" in err
    assert not work_dir(repo).exists() or not list(work_dir(repo).glob("*.toml"))


@pytest.mark.ac("E18-AC-02")
def test_a_duplicate_id_exits_2_and_leaves_the_first_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    new(repo, monkeypatch, capsys, "First", "--id", "dup")
    before = record_path(repo, "dup").read_bytes()
    code, _, err = call(repo, monkeypatch, capsys, "new", "Second", "--id", "dup", "--task", "t2")
    assert code == 2
    assert "dup" in err
    assert record_path(repo, "dup").read_bytes() == before


@pytest.mark.ac("E18-AC-02")
def test_new_has_the_spec_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    job = new(repo, monkeypatch, capsys, "Defaults")
    data = record(repo, job)
    assert data["track"] == "full"
    assert data["phase"] == "spec"
    assert data["status"] == "open"
    assert data["task"] == job
    assert data["tasks"] == [job]
    assert data["branch"] == ""
    assert data["worktree"] == ""
    assert data["owner"] == ""
    assert data.get("claims", []) == []


@pytest.mark.ac("E18-AC-02")
def test_new_takes_the_track_task_branch_and_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    args = ("--track", "lite", "--task", "E31-T1", "--branch", "b1", "--worktree", "/w/1")
    job = new(repo, monkeypatch, capsys, "Given", *args)
    data = record(repo, job)
    assert (data["track"], data["task"], data["tasks"]) == ("lite", "E31-T1", ["E31-T1"])
    assert (data["branch"], data["worktree"]) == ("b1", "/w/1")


@pytest.mark.ac("E18-AC-02")
@pytest.mark.parametrize(
    "args",
    [
        ("--track", "fast"),
        ("--task", "bad task"),
        ("--task", "a/b"),
        ("--task", ""),
    ],
)
def test_a_bad_track_or_task_exits_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    args: tuple[str, ...],
) -> None:
    repo = jobs_repo(tmp_path)
    assert call(repo, monkeypatch, capsys, "new", "Bad", *args)[0] == 2
    assert not work_dir(repo).exists() or not list(work_dir(repo).glob("*.toml"))


@pytest.mark.ac("E18-AC-02")
def test_an_empty_title_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    assert call(repo, monkeypatch, capsys, "new", "  ")[0] == 2


@pytest.mark.ac("E18-AC-02")
def test_a_task_held_by_another_live_job_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    first = new(repo, monkeypatch, capsys, "First", "--task", "E31-T1")
    code, _, err = call(repo, monkeypatch, capsys, "new", "Second", "--task", "E31-T1")
    assert code == 1
    assert first in err
    assert [p.name for p in work_dir(repo).glob("*.toml")] == [f"{first}.toml"]


@pytest.mark.ac("E18-AC-02")
@pytest.mark.parametrize("status", ["done", "cancelled"])
def test_a_task_is_free_again_once_its_job_is_done_or_cancelled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: str,
) -> None:
    repo = jobs_repo(tmp_path)
    first = new(repo, monkeypatch, capsys, "First", "--task", "E31-T1")
    session = ("--session", "s-a")
    assert call(repo, monkeypatch, capsys, "claim", first, *session)[0] == 0
    assert call(repo, monkeypatch, capsys, "set", first, *session, "--status", status)[0] == 0
    second = new(repo, monkeypatch, capsys, "Second", "--task", "E31-T1")
    assert record(repo, second)["task"] == "E31-T1"


@pytest.mark.ac("E18-AC-02")
@pytest.mark.slow
def test_concurrent_new_commands_never_get_the_same_id(tmp_path: Path) -> None:
    repo = jobs_repo(tmp_path)
    procs = [
        subprocess.Popen(
            [sys.executable, str(JOBS_PY), "new", f"Job {n}"],
            cwd=repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for n in range(8)
    ]
    ids = []
    for proc in procs:
        out, err = proc.communicate(timeout=120)
        assert proc.returncode == 0, err
        ids.append(out.strip())
    assert sorted(ids, key=lambda i: int(i.split("-")[1])) == [f"job-{n}" for n in range(1, 9)]
    assert len({record(repo, job)["title"] for job in ids}) == 8


# --- AC-03: the record and show --------------------------------------------------------------


@pytest.mark.ac("E18-AC-03")
def test_the_record_is_one_toml_file_with_the_spec_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    job = new(repo, monkeypatch, capsys, "Fields")
    data = record(repo, job)
    assert set(data) - {"claims"} == RECORD_KEYS
    assert data["version"] == 1
    for key in ("created", "updated"):
        assert isinstance(data[key], dt.datetime)
        assert data[key].utcoffset() == dt.timedelta(0)
    assert [p.name for p in work_dir(repo).iterdir() if p.is_file()] == [f"{job}.toml"], (
        "no temp files are left beside the record"
    )


@pytest.mark.ac("E18-AC-03")
def test_the_api_sets_the_times_from_now(tmp_path: Path) -> None:
    repo = api_repo(jobs_repo(tmp_path))
    made = jobs.new_job(repo, "Timed", now=T0)
    stamp = dt.datetime.fromtimestamp(T0, dt.UTC)
    assert made["created"] == stamp
    assert made["updated"] == stamp
    assert jobs.read_job(repo, made["id"]) == made


@pytest.mark.ac("E18-AC-03")
def test_show_json_prints_the_record_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    job = new(repo, monkeypatch, capsys, "Shown", "--task", "E31-T2")
    claimed(repo, job, now=dt.datetime.now(dt.UTC).timestamp())
    data = show(repo, monkeypatch, capsys, job)
    on_disk = record(repo, job)
    for key in RECORD_KEYS:
        value = on_disk[key]
        expected = value.isoformat() if isinstance(value, dt.datetime) else value
        assert data[key] == expected, key
    assert [c["session"] for c in data["claims"]] == ["s-one"]
    assert data["sidecars"] == {}


@pytest.mark.ac("E18-AC-03")
def test_show_text_is_the_same_record_as_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    job = new(repo, monkeypatch, capsys, "Text")
    code, out, err = call(repo, monkeypatch, capsys, "show", job)
    assert code == 0, err
    data = tomllib.loads(out)
    on_disk = record(repo, job)
    assert {key: data[key] for key in RECORD_KEYS} == {key: on_disk[key] for key in RECORD_KEYS}


@pytest.mark.ac("E18-AC-03")
def test_a_damaged_record_exits_2_on_show(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    job = new(repo, monkeypatch, capsys)
    path = record_path(repo, job)
    path.write_text(path.read_text(encoding="utf-8").replace('"full"', '"fast"'), "utf-8")
    code, _, err = call(repo, monkeypatch, capsys, "show", job)
    assert code == 2
    assert "track" in err


@pytest.mark.ac("E18-AC-03")
def test_a_sidecar_sits_beside_the_record_and_show_lists_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = jobs_repo(tmp_path)
    repo = api_repo(root)
    job = jobs.new_job(repo, "Piped", job_id="e13-one", now=T0)["id"]
    jobs.claim(repo, jobs.load_config(repo), job, "s-e13", now=dt.datetime.now(dt.UTC).timestamp())
    path = jobs.write_sidecar(repo, job, "pipeline", 'stage = "spec"\n', "s-e13")
    assert path == work_dir(root) / "e13-one.pipeline.toml"
    assert path == jobs.sidecar_path(repo, job, "pipeline")
    assert path.read_text(encoding="utf-8") == 'stage = "spec"\n'
    before = record_path(root, job).read_bytes()
    data = show(root, monkeypatch, capsys, job)
    assert data["sidecars"] == {"pipeline": str(path)}
    assert record_path(root, job).read_bytes() == before, "a sidecar never changes the record"
    code, out, _ = call(root, monkeypatch, capsys, "show", job)
    assert code == 0
    assert tomllib.loads(out)["sidecars"] == {"pipeline": str(path)}


@pytest.mark.ac("E18-AC-03")
def test_jobs_py_never_writes_a_sidecar_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = jobs_repo(tmp_path)
    repo = api_repo(root)
    job = jobs.new_job(repo, "Piped", now=T0)["id"]
    session = ("--session", "s-e13")
    assert call(root, monkeypatch, capsys, "claim", job, *session)[0] == 0
    side = jobs.write_sidecar(repo, job, "pipeline", "not even toml [[[\n", "s-e13")
    for args in (("set", job, *session, "--phase", "design"), ("beat", job, *session)):
        assert call(root, monkeypatch, capsys, *args)[0] == 0
    assert show(root, monkeypatch, capsys, job)["sidecars"] == {"pipeline": str(side)}
    assert side.read_text(encoding="utf-8") == "not even toml [[[\n", "contents never read"


@pytest.mark.ac("E18-AC-03")
@pytest.mark.parametrize("name", ["", "Pipeline", "9lives", "a.b", "a-b", "x" * 21])
def test_a_bad_sidecar_name_is_bad_input(tmp_path: Path, name: str) -> None:
    repo = api_repo(jobs_repo(tmp_path))
    job = jobs.new_job(repo, "Piped", now=T0)["id"]
    jobs.claim(repo, jobs.load_config(repo), job, "s-a", now=T0)
    with pytest.raises(jobs.BadInput):
        jobs.write_sidecar(repo, job, name, "x = 1\n", "s-a", now=T0)


@pytest.mark.ac("E18-AC-03")
def test_writing_a_sidecar_needs_the_live_lease(tmp_path: Path) -> None:
    repo = api_repo(jobs_repo(tmp_path))
    job = jobs.new_job(repo, "Piped", now=T0)["id"]
    with pytest.raises(jobs.Refused):
        jobs.write_sidecar(repo, job, "pipeline", "x = 1\n", "s-a", now=T0)
    jobs.claim(repo, jobs.load_config(repo), job, "s-a", now=T0)
    with pytest.raises(jobs.Refused):
        jobs.write_sidecar(repo, job, "pipeline", "x = 1\n", "s-other", now=T0)
    with pytest.raises(jobs.Refused):
        jobs.write_sidecar(repo, job, "pipeline", "x = 1\n", "s-a", now=T0 + 11 * MINUTE)
    assert not jobs.sidecar_path(repo, job, "pipeline").exists()
    jobs.write_sidecar(repo, job, "pipeline", "x = 1\n", "s-a", now=T0 + MINUTE)
    assert jobs.sidecar_path(repo, job, "pipeline").is_file()


# --- AC-04: set -------------------------------------------------------------------------------


@pytest.mark.ac("E18-AC-04")
def test_the_lease_holder_sets_fields_and_updated(tmp_path: Path) -> None:
    repo = api_repo(jobs_repo(tmp_path))
    job = jobs.new_job(repo, "Before", now=T0)["id"]
    jobs.claim(repo, jobs.load_config(repo), job, "s-a", now=T0)
    after = jobs.set_job(
        repo,
        job,
        "s-a",
        now=T0 + MINUTE,
        title="After",
        track="lite",
        phase="build",
        status="blocked",
        branch="factory/x",
        worktree="/w/x",
    )
    on_disk = jobs.read_job(repo, job)
    assert after == on_disk
    assert (on_disk["title"], on_disk["track"], on_disk["phase"]) == ("After", "lite", "build")
    assert (on_disk["status"], on_disk["branch"], on_disk["worktree"]) == (
        "blocked",
        "factory/x",
        "/w/x",
    )
    assert on_disk["updated"] == dt.datetime.fromtimestamp(T0 + MINUTE, dt.UTC)
    assert on_disk["created"] == dt.datetime.fromtimestamp(T0, dt.UTC)


@pytest.mark.ac("E18-AC-04")
def test_set_on_the_command_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    job = new(repo, monkeypatch, capsys)
    session = ("--session", "s-a")
    assert call(repo, monkeypatch, capsys, "claim", job, *session)[0] == 0
    args = ("--phase", "design", "--status", "blocked", "--branch", "b", "--worktree", "w")
    code, _, err = call(repo, monkeypatch, capsys, "set", job, *session, *args)
    assert code == 0, err
    data = record(repo, job)
    assert (data["phase"], data["status"], data["branch"], data["worktree"]) == (
        "design",
        "blocked",
        "b",
        "w",
    )


@pytest.mark.ac("E18-AC-04")
def test_only_the_live_lease_holder_may_set(tmp_path: Path) -> None:
    repo = api_repo(jobs_repo(tmp_path))
    job = jobs.new_job(repo, "Guarded", now=T0)["id"]
    before = jobs.read_job(repo, job)
    with pytest.raises(jobs.Refused):
        jobs.set_job(repo, job, "s-a", now=T0, phase="design")  # no lease at all
    jobs.claim(repo, jobs.load_config(repo), job, "s-a", now=T0)
    claimed_record = jobs.read_job(repo, job)
    with pytest.raises(jobs.Refused):
        jobs.set_job(repo, job, "s-other", now=T0, phase="design")
    with pytest.raises(jobs.Refused):
        jobs.set_job(repo, job, "s-a", now=T0 + 10 * MINUTE, phase="design")  # expired
    assert jobs.read_job(repo, job) == claimed_record
    assert claimed_record["phase"] == before["phase"]


@pytest.mark.ac("E18-AC-04")
def test_set_by_another_session_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    job = new(repo, monkeypatch, capsys)
    assert call(repo, monkeypatch, capsys, "claim", job, "--session", "s-a")[0] == 0
    before = record_path(repo, job).read_bytes()
    code, _, err = call(
        repo, monkeypatch, capsys, "set", job, "--session", "s-b", "--phase", "gate"
    )
    assert code == 1
    assert "s-a" in err or "lease" in err
    assert record_path(repo, job).read_bytes() == before


@pytest.mark.ac("E18-AC-04")
@pytest.mark.parametrize(
    "args",
    [
        ("--phase", "deploy"),
        ("--track", "fast"),
        ("--status", "running"),
        ("--task", "bad task"),
        ("--title", " "),
    ],
)
def test_an_invalid_value_exits_2_and_changes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    args: tuple[str, ...],
) -> None:
    repo = jobs_repo(tmp_path)
    job = new(repo, monkeypatch, capsys)
    assert call(repo, monkeypatch, capsys, "claim", job, "--session", "s-a")[0] == 0
    before = record_path(repo, job).read_bytes()
    assert call(repo, monkeypatch, capsys, "set", job, "--session", "s-a", *args)[0] == 2
    assert record_path(repo, job).read_bytes() == before


@pytest.mark.ac("E18-AC-04")
def test_a_new_task_is_appended_to_tasks(tmp_path: Path) -> None:
    repo = api_repo(jobs_repo(tmp_path))
    job = jobs.new_job(repo, "Slices", task="E31-T1", now=T0)["id"]
    jobs.claim(repo, jobs.load_config(repo), job, "s-a", now=T0)
    jobs.set_job(repo, job, "s-a", now=T0, task="E31-T2")
    jobs.set_job(repo, job, "s-a", now=T0, task="E31-T2")
    data = jobs.read_job(repo, job)
    assert data["task"] == "E31-T2"
    assert data["tasks"] == ["E31-T1", "E31-T2"]


@pytest.mark.ac("E18-AC-04")
def test_a_new_task_held_by_another_live_job_is_refused(tmp_path: Path) -> None:
    repo = api_repo(jobs_repo(tmp_path))
    jobs.new_job(repo, "Holder", task="E31-T9", now=T0)
    job = jobs.new_job(repo, "Mover", task="E31-T1", now=T0)["id"]
    jobs.claim(repo, jobs.load_config(repo), job, "s-a", now=T0)
    before = jobs.read_job(repo, job)
    with pytest.raises(jobs.Refused):
        jobs.set_job(repo, job, "s-a", now=T0, task="E31-T9")
    assert jobs.read_job(repo, job) == before


@pytest.mark.ac("E18-AC-04")
def test_an_unknown_field_is_bad_input(tmp_path: Path) -> None:
    repo = api_repo(jobs_repo(tmp_path))
    job = jobs.new_job(repo, "Strict", now=T0)["id"]
    jobs.claim(repo, jobs.load_config(repo), job, "s-a", now=T0)
    for field in ("owner", "id", "created", "colour"):
        with pytest.raises(jobs.BadInput):
            jobs.set_job(repo, job, "s-a", now=T0, **{field: "x"})


DAMAGE = [
    ("version = 1", "version = 2", "version"),
    ('phase = "spec"', 'phase = "deploy"', "phase"),
    ('status = "open"', 'status = "running"', "status"),
    ('title = "A job"', 'title = " "', "title"),
    ('owner = ""', "owner = 3", "owner"),
    ("tasks = [", "extra = 1\ntasks = [", "extra"),
    ('id = "job-1"', 'id = "job-2"', "id"),
    ('tasks = ["job-1"]', "tasks = []", "tasks"),
    ('tasks = ["job-1"]', 'tasks = ["other"]', "tasks"),
    ("created = ", 'created = "yesterday"\nx_created = ', "created"),
]


@pytest.mark.ac("E18-AC-03")
@pytest.mark.parametrize(("old", "new_text", "key"), DAMAGE)
def test_read_job_names_what_is_wrong_with_a_damaged_record(
    tmp_path: Path, old: str, new_text: str, key: str
) -> None:
    repo = api_repo(jobs_repo(tmp_path))
    job = jobs.new_job(repo, "A job", now=T0)["id"]
    path = repo.work / f"{job}.toml"
    text = path.read_text(encoding="utf-8")
    assert old in text, text
    path.write_text(text.replace(old, new_text, 1), encoding="utf-8")
    with pytest.raises(jobs.BadInput) as caught:
        jobs.read_job(repo, job)
    assert f"{key}:" in str(caught.value)


@pytest.mark.ac("E18-AC-03")
def test_a_record_with_a_bad_claim_entry_is_damaged(tmp_path: Path) -> None:
    repo = api_repo(jobs_repo(tmp_path))
    job = jobs.new_job(repo, "A job", now=T0)["id"]
    jobs.claim(repo, jobs.load_config(repo), job, "s-a", now=T0)
    path = repo.work / f"{job}.toml"
    path.write_text(path.read_text(encoding="utf-8").replace("forced = false", 'forced = "no"'))
    with pytest.raises(jobs.BadInput) as caught:
        jobs.read_job(repo, job)
    assert "claims:" in str(caught.value)


@pytest.mark.ac("E18-AC-03")
def test_a_record_that_is_not_toml_is_bad_input(tmp_path: Path) -> None:
    repo = api_repo(jobs_repo(tmp_path))
    job = jobs.new_job(repo, "A job", now=T0)["id"]
    (repo.work / f"{job}.toml").write_text("not [toml", encoding="utf-8")
    with pytest.raises(jobs.BadInput):
        jobs.read_job(repo, job)
    with pytest.raises(jobs.UnknownJob):
        jobs.read_job(repo, "Not-An-Id")


@pytest.mark.ac("E18-AC-03")
def test_only_well_named_sidecars_are_listed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = jobs_repo(tmp_path)
    job = new(root, monkeypatch, capsys)
    other = new(root, monkeypatch, capsys, "Other")
    for name in (f"{job}.pipeline.toml", f"{job}.Bad.toml", f"{job}.x.y.toml", f"{other}.e.toml"):
        (work_dir(root) / name).write_text("x = 1\n", encoding="utf-8")
    (work_dir(root) / f"{job}.notes.txt").write_text("x\n", encoding="utf-8")
    shown = show(root, monkeypatch, capsys, job)["sidecars"]
    assert shown == {"pipeline": str(work_dir(root) / f"{job}.pipeline.toml")}


@pytest.mark.ac("E18-AC-02")
def test_a_task_reservation_left_by_a_vanished_job_is_taken_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    first = new(repo, monkeypatch, capsys, "First", "--task", "E31-T1")
    record_path(repo, first).unlink()  # its record is gone, its reservation is not
    second = new(repo, monkeypatch, capsys, "Second", "--task", "E31-T1")
    assert record(repo, second)["task"] == "E31-T1"
    code, _, err = call(repo, monkeypatch, capsys, "new", "Third", "--task", "E31-T1")
    assert code == 1
    assert second in err


@pytest.mark.ac("E18-AC-02")
def test_a_refused_task_does_not_use_up_the_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    new(repo, monkeypatch, capsys, "Holder", "--id", "holder", "--task", "E31-T1")
    code, _, _ = call(repo, monkeypatch, capsys, "new", "X", "--id", "wanted", "--task", "E31-T1")
    assert code == 1
    assert new(repo, monkeypatch, capsys, "X", "--id", "wanted", "--task", "E31-T2") == "wanted"


@pytest.mark.ac("E18-AC-04")
def test_set_with_nothing_to_change_or_no_session_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    job = new(repo, monkeypatch, capsys)
    assert call(repo, monkeypatch, capsys, "claim", job, "--session", "s-a")[0] == 0
    assert call(repo, monkeypatch, capsys, "set", job, "--session", "s-a")[0] == 2
    monkeypatch.delenv("FACTORY_SESSION", raising=False)
    assert call(repo, monkeypatch, capsys, "set", job, "--phase", "design")[0] == 2
    assert record(repo, job)["phase"] == "spec"


@pytest.mark.ac("E18-AC-04")
def test_reopening_an_ended_job_takes_its_tasks_back(tmp_path: Path) -> None:
    repo = api_repo(jobs_repo(tmp_path))
    job = jobs.new_job(repo, "Reopened", task="E31-T1", now=T0)["id"]
    jobs.claim(repo, jobs.load_config(repo), job, "s-a", now=T0)
    jobs.set_job(repo, job, "s-a", now=T0, status="done")
    jobs.set_job(repo, job, "s-a", now=T0, status="open")
    with pytest.raises(jobs.Refused):
        jobs.new_job(repo, "Rival", task="E31-T1", now=T0)
    jobs.set_job(repo, job, "s-a", now=T0, status="cancelled")
    rival = jobs.new_job(repo, "Rival", task="E31-T1", now=T0)
    jobs.claim(repo, jobs.load_config(repo), rival["id"], "s-b", now=T0)
    with pytest.raises(jobs.Refused):
        jobs.set_job(repo, job, "s-a", now=T0, status="open")
    assert jobs.read_job(repo, job)["status"] == "cancelled"
