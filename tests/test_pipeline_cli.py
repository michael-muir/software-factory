"""E13/T1: `pipeline.py` as a program, and `pipeline.py check` in both of its forms.

Covers E13 AC-01 and AC-04 (the command line). Expectations come from the E13 spec (AC-01: the
exit codes; AC-04: `check <job> [<stage>]` and `check <stage> --worktree ...`) and the design
note ("The checks", "The records"): the job's record is E18's sidecar `work/<id>.pipeline.toml`.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

import pipeline
from tests._pipeline import (
    EPIC,
    JOB,
    PIPELINE_PY,
    SPEC_REL,
    TASK,
    commit,
    gate_entry,
    gate_report,
    git,
    head,
    lock_tests,
    plan_and_slice_base,
    record,
    repo,
    sidecar,
    spec_text,
    write,
)


def call(
    cwd: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *args: str,
) -> tuple[int, str, str]:
    monkeypatch.chdir(cwd)
    capsys.readouterr()
    code = pipeline.main(list(args))
    out = capsys.readouterr()
    return code, out.out, out.err


def spec_repo(tmp_path: Path) -> tuple[Path, str]:
    """A repo whose spec stage passes, from the returned base."""
    root = repo(tmp_path)
    base = head(root)
    commit(root, {SPEC_REL: spec_text()})
    return root, base


def save_record(root: Path, **fields: object) -> Path:
    path = sidecar(root, JOB, "pipeline")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(pipeline.dump_record(record(**fields)), encoding="utf-8")
    return path


def run_entry(task: str, base: str, branch: str, worktree: Path | str) -> dict[str, object]:
    return {
        "id": f"{JOB}-p1",
        "task": task,
        "base": base,
        "stages": ["spec"],
        "branch": branch,
        "worktree": str(worktree),
    }


# --- AC-01: the program -------------------------------------------------------------------------


@pytest.mark.ac("E13-AC-01")
def test_pipeline_py_imports_only_the_standard_library() -> None:
    tree = ast.parse(PIPELINE_PY.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    assert names, "pipeline.py imports something"
    assert names <= set(sys.stdlib_module_names), names - set(sys.stdlib_module_names)


@pytest.mark.ac("E13-AC-01")
def test_it_runs_isolated_without_site_and_a_passing_check_exits_0(tmp_path: Path) -> None:
    root, base = spec_repo(tmp_path)
    argv = [sys.executable, "-I", "-S", str(PIPELINE_PY), "check", "spec"]
    argv += ["--worktree", str(root), "--epic", EPIC, "--base", base]
    result = subprocess.run(argv, cwd=root, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.ac("E13-AC-01")
def test_a_failing_check_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(tmp_path)
    code, out, _ = call(
        root, monkeypatch, capsys, "check", "spec", "--worktree", str(root), "--epic", EPIC
    )
    assert code == 1
    assert ": spec: " in out


@pytest.mark.ac("E13-AC-01")
@pytest.mark.parametrize(
    "args",
    [
        ["check", "deploy", "--worktree", ".", "--epic", EPIC],  # unknown stage
        ["check", "spec", "--worktree", ".", "--epic", "31"],  # bad epic
        ["check", "test", "--worktree", ".", "--epic", EPIC],  # a slice stage needs --task
        ["check", "review", "--worktree", ".", "--epic", EPIC, "--task", TASK],  # needs --job
        ["check", "ship", "--worktree", ".", "--epic", EPIC, "--task", TASK],  # needs --job
        ["check", "learn", "--worktree", ".", "--epic", EPIC],  # needs --job
        ["check", "spec", "--worktree", ".", "--epic", EPIC, "--base", "no-such-ref"],
        ["check", "no-such-job"],  # unknown job
        ["check", "Bad_Id!"],  # not a job id
        ["frobnicate"],  # unknown command
        [],
    ],
)
def test_bad_input_exits_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    args: list[str],
) -> None:
    root = repo(tmp_path)
    code, _, _ = call(root, monkeypatch, capsys, *args)
    assert code == 2


@pytest.mark.ac("E13-AC-01")
def test_a_worktree_outside_any_git_repo_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    root = repo(tmp_path)
    code, _, _ = call(
        root, monkeypatch, capsys, "check", "spec", "--worktree", str(plain), "--epic", EPIC
    )
    assert code == 2


@pytest.mark.ac("E13-AC-01")
def test_an_invalid_pipeline_config_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, base = spec_repo(tmp_path)
    write(root, {".agentic/config.toml": '[pipeline]\nforge = "svn"\n'})
    code, _, err = call(
        root,
        monkeypatch,
        capsys,
        *("check", "spec", "--worktree", str(root), "--epic", EPIC, "--base", base),
    )
    assert code == 2
    assert "pipeline.forge" in err


# --- AC-04: check <stage> --worktree ------------------------------------------------------------


@pytest.mark.ac("E13-AC-04")
def test_check_stage_worktree_passes_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, base = spec_repo(tmp_path)
    args = ("check", "spec", "--worktree", str(root), "--epic", EPIC, "--base", base)
    code, out, _ = call(tmp_path, monkeypatch, capsys, *args)
    assert code == 0
    assert "spec" in out and "pass" in out


@pytest.mark.ac("E13-AC-04")
def test_check_prints_one_problem_per_line_naming_stage_and_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(tmp_path)
    base = head(root)
    commit(root, {SPEC_REL: spec_text().replace("## In scope", "## Inside")})
    args = ("check", "spec", "--worktree", str(root), "--epic", EPIC, "--base", base)
    code, out, _ = call(root, monkeypatch, capsys, *args)
    assert code == 1
    lines = out.strip().splitlines()
    assert lines and all(line.startswith(f"{SPEC_REL}: spec: ") for line in lines), lines


@pytest.mark.ac("E13-AC-04")
def test_the_base_defaults_to_gates_base_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(tmp_path)
    git(root, "branch", "trunk")
    commit(root, {SPEC_REL: spec_text()})
    write(root, {".agentic/config.toml": '[gates]\nbase_ref = "trunk"\n'})
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "config")
    args = ("check", "spec", "--worktree", str(root), "--epic", EPIC)
    assert call(root, monkeypatch, capsys, *args)[0] == 0


@pytest.mark.ac("E13-AC-04")
def test_check_gate_takes_a_gate_report_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    root = repo(tmp_path)
    report = tmp_path / "gate.json"
    report.write_text(json.dumps(gate_report(head(root))), encoding="utf-8")
    args = ["check", "gate", "--worktree", str(root), "--epic", EPIC, "--task", TASK]
    assert call(root, monkeypatch, capsys, *args, "--gate-report", str(report))[0] == 0
    report.write_text(json.dumps(gate_report(head(root), verdict="fail")), encoding="utf-8")
    assert call(root, monkeypatch, capsys, *args, "--gate-report", str(report))[0] == 1


# --- AC-04: check <job> [<stage>] ---------------------------------------------------------------


@pytest.mark.ac("E13-AC-04")
def test_check_job_runs_the_current_stage_in_the_jobs_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, base = spec_repo(tmp_path)
    save_record(root, stage="spec", runs=[run_entry(JOB, base, "main", root)])
    code, out, _ = call(root, monkeypatch, capsys, "check", JOB)
    assert code == 0, out
    save_record(root, stage="spec", runs=[run_entry(JOB, head(root), "main", root)])
    assert call(root, monkeypatch, capsys, "check", JOB)[0] == 1


@pytest.mark.ac("E13-AC-04")
def test_check_job_takes_a_named_stage_and_the_records_gate_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, base = plan_and_slice_base(tmp_path)
    lock_tests(root)
    runs = [{**run_entry(TASK, base, "main", root), "id": f"{JOB}-t1-1"}]
    green = gate_entry(TASK, gate_report(head(root)))
    save_record(root, stage="gate", task=TASK, runs=runs, gates=[green])
    assert call(root, monkeypatch, capsys, "check", JOB)[0] == 0
    assert call(root, monkeypatch, capsys, "check", JOB, "test")[0] == 0
    assert call(root, monkeypatch, capsys, "check", JOB, "build")[0] == 1  # no commit after lock


@pytest.mark.ac("E13-AC-04")
def test_check_job_uses_a_temporary_worktree_when_the_jobs_has_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(tmp_path)
    base = head(root)
    git(root, "checkout", "-q", "-b", "factory/e31-widgets-p1")
    commit(root, {SPEC_REL: spec_text()})
    git(root, "checkout", "-q", "main")
    gone = tmp_path / "gone"
    save_record(root, runs=[run_entry(JOB, base, "factory/e31-widgets-p1", gone)])
    code, out, _ = call(root, monkeypatch, capsys, "check", JOB, "spec")
    assert code == 0, out
    assert not gone.exists()
    assert len(git(root, "worktree", "list", "--porcelain").split("worktree ")) == 2  # main only


@pytest.mark.ac("E13-AC-04")
def test_check_job_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, base = spec_repo(tmp_path)
    path = save_record(root, runs=[run_entry(JOB, base, "main", root)])
    before = (path.read_bytes(), head(root), git(root, "status", "--porcelain"))
    for stage in ("spec", "design", "gate"):
        call(root, monkeypatch, capsys, "check", JOB, stage)
    assert (path.read_bytes(), head(root), git(root, "status", "--porcelain")) == before


@pytest.mark.ac("E13-AC-04")
def test_check_job_with_no_runner_job_for_its_task_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _ = spec_repo(tmp_path)
    save_record(root, runs=[])
    code, out, _ = call(root, monkeypatch, capsys, "check", JOB)
    assert code == 1
    assert "spec" in out


@pytest.mark.ac("E13-AC-04")
def test_a_damaged_record_is_bad_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _ = spec_repo(tmp_path)
    path = save_record(root)
    path.write_text('version = 1\nstatus = "flying"\n', encoding="utf-8")
    assert call(root, monkeypatch, capsys, "check", JOB)[0] == 2


@pytest.mark.ac("E13-AC-04")
def test_a_record_round_trips() -> None:
    data = record(
        runs=[run_entry(JOB, "abc1234", "main", "/w")],
        gates=[gate_entry(TASK, gate_report("abc1234"))],
        tasks=[{"id": TASK, "branch": "factory/x", "pr": "17", "merged": False, "pr_body": "b"}],
        decisions=[
            {
                "checkpoint": "spec",
                "verdict": "reject",
                "by": "po",
                "at": "2026-11-21T11:00:00Z",
                "note": 'quote " and\nnewline',
            }
        ],
        sessions=[
            {
                "run": f"{JOB}-p1",
                "index": 1,
                "stage": "spec",
                "task": JOB,
                "role": "spec-writer",
                "sent": "2026-11-21T10:00:00Z",
                "exit_code": 0,
                "usd": "0.42",
            }
        ],
    )
    assert pipeline.load_record(pipeline.dump_record(data)) == data
