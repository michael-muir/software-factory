"""E16/T1: the runner's store and CLI: submit, send, close and status.

Covers E16 AC-01 to AC-04 (the parts with no daemon: the running half of AC-03 is tested with
the daemon in T2). Expectations come from the E16 spec, the design note ("The store") and
ADR 0030, not from the implementation.
"""

from __future__ import annotations

import ast
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

import run as runner
from tests._runner import (
    RUN_PY,
    call,
    factory_dir,
    git,
    job_dir,
    queue_file,
    read_toml,
    real,
    runner_repo,
    submit,
)

ID = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
PY = [sys.executable, "-c", "pass"]
T0 = dt.datetime(2026, 11, 19, 21, 30, 5, tzinfo=dt.UTC)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return runner_repo(tmp_path)


def request(repo: Path, job: str) -> dict[str, Any]:
    return read_toml(queue_file(repo, job))


def status_json(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], job: str
) -> dict[str, Any]:
    code, out, err = call(repo, monkeypatch, capsys, "status", job, "--json")
    assert code == 0, err
    data = json.loads(out)
    assert isinstance(data, dict)
    return data


def write_record(repo: Path, job: str, text: str) -> None:
    """Stand in for the daemon: the record it writes into jobs/<id>/job.toml (design note)."""
    (job_dir(repo, job) / "job.toml").write_text(text, encoding="utf-8")


def finished_record(job: str, status: str) -> str:
    return "\n".join(
        [
            f'id = "{job}"',
            f'status = "{status}"',
            'reason = ""',
            'base = "main"',
            f'branch = "factory/{job}"',
            'worktree = "wt"',
            f'task = "{job}"',
            "open = true",
            "created = 2026-11-19T21:30:05Z",
            "started = 2026-11-19T21:30:06Z",
            "finished = 2026-11-19T21:31:00Z",
            "turns = 0",
            "usd = 0.0",
            "warnings = []",
            "",
        ]
    )


# --- AC-01: the runner, its home and its exit codes ---------------------------------------------


@pytest.mark.ac("E16-AC-01")
def test_runner_imports_only_the_standard_library() -> None:
    tree = ast.parse(RUN_PY.read_text(encoding="utf-8"))
    foreign: list[str] = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        foreign += [n for n in names if n.split(".")[0] not in sys.stdlib_module_names]
    assert not foreign, f"non-stdlib imports in run.py: {foreign}"


@pytest.mark.ac("E16-AC-01")
def test_runner_runs_isolated_with_python_i_s(repo: Path) -> None:
    def cli(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-I", "-S", str(RUN_PY), *args],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )

    submitted = cli("submit", "--", *PY)
    assert submitted.returncode == 0, submitted.stderr
    job = submitted.stdout.strip()
    assert ID.fullmatch(job), job
    shown = cli("status", job, "--json")
    assert shown.returncode == 0, shown.stderr
    assert json.loads(shown.stdout)["id"] == job


@pytest.mark.ac("E16-AC-01")
def test_store_is_in_the_git_common_dir_from_a_subfolder_and_a_worktree(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sub = repo / "src" / "deep"
    sub.mkdir(parents=True)
    from_sub = submit(sub, monkeypatch, capsys, "--", *PY)
    assert queue_file(repo, from_sub).is_file()

    linked = repo.parent / "linked"
    git(repo, "worktree", "add", "-q", "-b", "other", str(linked))
    from_linked = submit(linked, monkeypatch, capsys, "--", *PY)
    assert queue_file(repo, from_linked).is_file()
    assert real(factory_dir(linked)) == real(factory_dir(repo))
    assert real(factory_dir(repo).parent) == real(repo / ".git")

    assert status_json(repo, monkeypatch, capsys, from_linked)["id"] == from_linked
    assert status_json(linked, monkeypatch, capsys, from_sub)["id"] == from_sub


@pytest.mark.ac("E16-AC-01")
def test_nothing_in_the_store_is_seen_by_git(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    submit(repo, monkeypatch, capsys, "--open")
    assert git(repo, "status", "--porcelain", "--ignored") == ""


@pytest.mark.ac("E16-AC-01")
def test_outside_a_git_repo_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    code, _, err = call(plain, monkeypatch, capsys, "submit", "--", *PY)
    assert code == 2
    assert "git" in err.lower()


@pytest.mark.ac("E16-AC-01")
def test_a_repo_with_no_commit_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "empty"
    subprocess.run(["git", "init", "-q", str(empty)], check=True)
    code, _, err = call(empty, monkeypatch, capsys, "submit", "--", *PY)
    assert code == 2
    assert "commit" in err.lower()


@pytest.mark.ac("E16-AC-01")
@pytest.mark.parametrize("command", ["status", "send", "close"])
def test_an_unknown_job_exits_2(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    extra = ["--", *PY] if command == "send" else []
    code, _, err = call(repo, monkeypatch, capsys, command, "no-such-job", *extra)
    assert code == 2
    assert "no-such-job" in err


@pytest.mark.ac("E16-AC-01")
def test_an_invalid_config_exits_2_and_names_the_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = runner_repo(tmp_path, "[runner]\nmax_turns = 0\n")
    code, _, err = call(repo, monkeypatch, capsys, "submit", "--", *PY)
    assert code == 2
    assert "runner.max_turns" in err
    assert not (factory_dir(repo) / "queue").exists() or not any(
        (factory_dir(repo) / "queue").iterdir()
    )


@pytest.mark.ac("E16-AC-01")
def test_config_that_is_not_toml_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = runner_repo(tmp_path, "[runner\n")
    code, _, err = call(repo, monkeypatch, capsys, "submit", "--", *PY)
    assert code == 2
    assert "config.toml" in err


@pytest.mark.ac("E16-AC-01")
@pytest.mark.parametrize("args", [[], ["frobnicate"], ["status"], ["submit", "--bogus"]])
def test_bad_arguments_exit_2_without_raising(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    args: list[str],
) -> None:
    code, _, _ = call(repo, monkeypatch, capsys, *args)
    assert code == 2


@pytest.mark.ac("E16-AC-01")
def test_the_kit_runner_is_installed_in_this_repo() -> None:
    installed = RUN_PY.parents[3] / ".factory" / "runner" / "run.py"
    assert installed.read_bytes().replace(b"\r\n", b"\n") == RUN_PY.read_bytes().replace(
        b"\r\n", b"\n"
    )


# --- AC-02: submit ----------------------------------------------------------------------------


@pytest.mark.ac("E16-AC-02")
def test_submit_queues_a_one_command_request_and_prints_its_id(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = [sys.executable, "-c", "print('-x')", "--flag", "two words"]
    job = submit(repo, monkeypatch, capsys, "--", *argv)
    assert ID.fullmatch(job), job
    data = request(repo, job)
    assert data["version"] == 1
    assert data["id"] == job
    assert data["base"] == "main"
    assert data["task"] == job
    assert data["open"] is False
    assert data["commands"] == [argv]
    assert isinstance(data["submitted"], dt.datetime)
    assert job_dir(repo, job).is_dir(), "the id is reserved by its jobs/<id>/ folder"


@pytest.mark.ac("E16-AC-02")
def test_generated_ids_follow_the_design_and_differ(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(runner, "_now", lambda: T0)
    first = submit(repo, monkeypatch, capsys, "--", *PY)
    second = submit(repo, monkeypatch, capsys, "--", *PY)
    for job in (first, second):
        assert re.fullmatch(r"j261119-213005-[0-9a-f]{4}", job), job
    assert first != second
    assert request(repo, first)["submitted"] == T0


@pytest.mark.ac("E16-AC-02")
@pytest.mark.parametrize("given", ["a", "0", "fix-login-7", "a" * 40])
def test_a_given_id_is_used(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], given: str
) -> None:
    assert submit(repo, monkeypatch, capsys, "--id", given, "--", *PY) == given
    assert request(repo, given)["id"] == given


@pytest.mark.ac("E16-AC-02")
@pytest.mark.parametrize("bad", ["", "Upper", "-lead", "a_b", "a.b", "a/b", "a" * 41, "é"])
def test_a_bad_id_exits_2_and_queues_nothing(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], bad: str
) -> None:
    code, out, _ = call(repo, monkeypatch, capsys, "submit", "--id", bad, "--", *PY)
    assert code == 2
    assert out == ""
    queue = factory_dir(repo) / "queue"
    assert not queue.exists() or not any(queue.iterdir())


@pytest.mark.ac("E16-AC-02")
def test_a_duplicate_id_exits_2_and_leaves_the_first_alone(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    submit(repo, monkeypatch, capsys, "--id", "twice", "--", *PY)
    before = queue_file(repo, "twice").read_bytes()
    code, _, err = call(
        repo, monkeypatch, capsys, "submit", "--id", "twice", "--", sys.executable, "-V"
    )
    assert code == 2
    assert "twice" in err
    assert queue_file(repo, "twice").read_bytes() == before


@pytest.mark.ac("E16-AC-02")
def test_an_id_is_never_reused_even_after_its_request_leaves_the_queue(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    submit(repo, monkeypatch, capsys, "--id", "gone", "--", *PY)
    queue_file(repo, "gone").rename(job_dir(repo, "gone") / "request.toml")  # a daemon claims it
    code, _, _ = call(repo, monkeypatch, capsys, "submit", "--id", "gone", "--", *PY)
    assert code == 2


@pytest.mark.ac("E16-AC-02")
def test_base_defaults_to_gates_base_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = runner_repo(tmp_path, '[gates]\nbase_ref = "develop"\n')
    job = submit(repo, monkeypatch, capsys, "--", *PY)
    assert request(repo, job)["base"] == "develop"


@pytest.mark.ac("E16-AC-02")
def test_base_and_task_can_be_given(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job = submit(repo, monkeypatch, capsys, "--base", "factory/j1", "--task", "E16-T1", "--", *PY)
    data = request(repo, job)
    assert data["base"] == "factory/j1"
    assert data["task"] == "E16-T1"


@pytest.mark.ac("E16-AC-02")
@pytest.mark.parametrize("bad", ["", "two words", "a/b"])
def test_a_bad_task_id_exits_2(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], bad: str
) -> None:
    code, _, _ = call(repo, monkeypatch, capsys, "submit", "--task", bad, "--", *PY)
    assert code == 2


@pytest.mark.ac("E16-AC-02")
def test_an_empty_base_exits_2(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, _ = call(repo, monkeypatch, capsys, "submit", "--base", "", "--", *PY)
    assert code == 2


@pytest.mark.ac("E16-AC-02")
def test_a_job_without_open_needs_exactly_one_command(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = call(repo, monkeypatch, capsys, "submit", "--id", "bare")
    assert code == 2
    assert out == ""
    assert "--open" in err
    assert not job_dir(repo, "bare").exists(), "a refused request reserves no id"
    assert submit(repo, monkeypatch, capsys, "--id", "bare", "--", *PY) == "bare"


@pytest.mark.ac("E16-AC-02")
def test_an_open_job_may_have_no_command_or_one(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = submit(repo, monkeypatch, capsys, "--open")
    assert request(repo, empty)["open"] is True
    assert request(repo, empty)["commands"] == []
    first = submit(repo, monkeypatch, capsys, "--open", "--", *PY)
    assert request(repo, first)["commands"] == [PY]


@pytest.mark.ac("E16-AC-02")
def test_submit_writes_the_queue_file_by_one_atomic_rename(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[tuple[str, str]] = []
    real_rename = os.rename

    def spy(src: Any, dst: Any) -> None:
        dst_path = Path(dst)
        if dst_path.parent.name == "queue":
            assert not dst_path.exists(), "the queue file must appear only by the rename"
            with open(src, "rb") as f:
                tomllib.load(f)  # the source is already complete TOML
            seen.append((Path(src).name, dst_path.name))
        real_rename(src, dst)

    monkeypatch.setattr(os, "rename", spy)
    job = submit(repo, monkeypatch, capsys, "--", *PY)
    assert len(seen) == 1
    assert seen[0][1] == f"{job}.toml"
    assert sorted(p.name for p in (factory_dir(repo) / "queue").iterdir()) == [f"{job}.toml"]


# --- AC-03: send and close --------------------------------------------------------------------


@pytest.mark.ac("E16-AC-03")
def test_send_adds_commands_in_order(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job = submit(repo, monkeypatch, capsys, "--open", "--", sys.executable, "-c", "print(0)")
    for n in (1, 2):
        code, _, err = call(
            repo, monkeypatch, capsys, "send", job, "--", sys.executable, "-c", f"print({n})"
        )
        assert code == 0, err
    files = sorted(p.name for p in (job_dir(repo, job) / "commands").iterdir())
    assert files == ["0001.toml", "0002.toml"]
    assert read_toml(job_dir(repo, job) / "commands" / "0002.toml")["argv"] == [
        sys.executable,
        "-c",
        "print(2)",
    ]
    argvs = [c["argv"][-1] for c in status_json(repo, monkeypatch, capsys, job)["commands"]]
    assert argvs == ["print(0)", "print(1)", "print(2)"]


@pytest.mark.ac("E16-AC-03")
def test_send_with_no_command_exits_2(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job = submit(repo, monkeypatch, capsys, "--open")
    code, _, _ = call(repo, monkeypatch, capsys, "send", job)
    assert code == 2


@pytest.mark.ac("E16-AC-03")
def test_send_and_close_refuse_a_one_command_job(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job = submit(repo, monkeypatch, capsys, "--", *PY)
    assert call(repo, monkeypatch, capsys, "send", job, "--", *PY)[0] == 1
    assert call(repo, monkeypatch, capsys, "close", job)[0] == 1
    assert not (job_dir(repo, job) / "commands").exists() or not any(
        (job_dir(repo, job) / "commands").iterdir()
    )


@pytest.mark.ac("E16-AC-03")
def test_close_ends_sending_and_cannot_be_repeated(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job = submit(repo, monkeypatch, capsys, "--open")
    code, _, err = call(repo, monkeypatch, capsys, "close", job)
    assert code == 0, err
    assert status_json(repo, monkeypatch, capsys, job)["closed"] is True
    assert call(repo, monkeypatch, capsys, "send", job, "--", *PY)[0] == 1
    assert call(repo, monkeypatch, capsys, "close", job)[0] == 1


@pytest.mark.ac("E16-AC-03")
def test_send_works_after_a_daemon_claims_the_request(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job = submit(repo, monkeypatch, capsys, "--open")
    queue_file(repo, job).rename(job_dir(repo, job) / "request.toml")
    assert call(repo, monkeypatch, capsys, "send", job, "--", *PY)[0] == 0
    assert call(repo, monkeypatch, capsys, "close", job)[0] == 0


@pytest.mark.ac("E16-AC-03")
@pytest.mark.parametrize("final", ["succeeded", "failed", "halted"])
def test_send_and_close_refuse_a_finished_job(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    final: str,
) -> None:
    job = submit(repo, monkeypatch, capsys, "--open")
    queue_file(repo, job).rename(job_dir(repo, job) / "request.toml")
    write_record(repo, job, finished_record(job, final))
    assert call(repo, monkeypatch, capsys, "send", job, "--", *PY)[0] == 1
    assert call(repo, monkeypatch, capsys, "close", job)[0] == 1


# --- AC-04: status ----------------------------------------------------------------------------

FIELDS = {
    "id",
    "status",
    "reason",
    "base",
    "branch",
    "worktree",
    "task",
    "created",
    "started",
    "finished",
    "turns",
    "usd",
    "warnings",
    "commands",
}


@pytest.mark.ac("E16-AC-04")
def test_status_of_a_queued_job_shows_every_field(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(runner, "_now", lambda: T0)
    job = submit(repo, monkeypatch, capsys, "--task", "E16-T1", "--", *PY)
    data = status_json(repo, monkeypatch, capsys, job)
    assert set(data) >= FIELDS
    assert data["id"] == job
    assert data["status"] == "queued"
    assert data["reason"] == ""
    assert data["base"] == "main"
    assert data["branch"] == f"factory/{job}"
    assert data["task"] == "E16-T1"
    assert data["turns"] == 0
    assert data["usd"] == 0
    assert data["warnings"] == []
    assert dt.datetime.fromisoformat(data["created"]) == T0
    assert data["started"] is None
    assert data["finished"] is None
    [command] = data["commands"]
    assert command["argv"] == PY
    assert command["exit_code"] is None
    assert command["duration_s"] is None
    assert Path(command["log"]).name == "0001.log"
    assert real(Path(command["log"]).parent) == real(job_dir(repo, job) / "logs")


@pytest.mark.ac("E16-AC-04")
def test_status_text_is_the_same_record_as_toml(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job = submit(repo, monkeypatch, capsys, "--open", "--", *PY)
    call(repo, monkeypatch, capsys, "send", job, "--", sys.executable, "-V")
    code, out, err = call(repo, monkeypatch, capsys, "status", job)
    assert code == 0, err
    text = tomllib.loads(out)
    data = status_json(repo, monkeypatch, capsys, job)
    assert text["id"] == data["id"]
    assert text["status"] == data["status"]
    assert text["worktree"] == data["worktree"]
    assert text["created"].isoformat() == dt.datetime.fromisoformat(data["created"]).isoformat()
    assert [c["argv"] for c in text["commands"]] == [c["argv"] for c in data["commands"]]
    assert {k for k, v in data.items() if v is not None} == set(text)


@pytest.mark.ac("E16-AC-04")
def test_the_default_worktree_is_a_sibling_folder(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job = submit(repo, monkeypatch, capsys, "--", *PY)
    worktree = status_json(repo, monkeypatch, capsys, job)["worktree"]
    assert real(worktree) == real(repo.parent / "proj.worktrees" / job)


@pytest.mark.ac("E16-AC-04")
def test_a_relative_worktree_root_is_taken_from_the_main_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = runner_repo(tmp_path, '[runner]\nworktree_root = "../jobs-here"\n')
    sub = repo / "pkg"
    sub.mkdir()
    job = submit(sub, monkeypatch, capsys, "--", *PY)
    worktree = status_json(sub, monkeypatch, capsys, job)["worktree"]
    assert real(worktree) == real(tmp_path / "jobs-here" / job)


@pytest.mark.ac("E16-AC-04")
def test_an_absolute_worktree_root_is_used_as_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = (tmp_path / "abs root").resolve()
    repo = runner_repo(tmp_path, f"[runner]\nworktree_root = {json.dumps(str(root))}\n")
    job = submit(repo, monkeypatch, capsys, "--", *PY)
    assert real(status_json(repo, monkeypatch, capsys, job)["worktree"]) == real(root / job)


@pytest.mark.ac("E16-AC-04")
def test_status_shows_the_record_once_the_job_has_one(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job = submit(repo, monkeypatch, capsys, "--open")
    queue_file(repo, job).rename(job_dir(repo, job) / "request.toml")
    record = finished_record(job, "halted").replace('reason = ""', 'reason = "cancelled"')
    write_record(repo, job, record)
    data = status_json(repo, monkeypatch, capsys, job)
    assert data["status"] == "halted"
    assert data["reason"] == "cancelled"
    assert dt.datetime.fromisoformat(data["finished"]) == dt.datetime(
        2026, 11, 19, 21, 31, 0, tzinfo=dt.UTC
    )
