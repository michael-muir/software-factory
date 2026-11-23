"""E13/T4: the driver commits what a role without a shell leaves behind, at the plan stages too.

Covers E13 AC-20 (its fake spec-writer and architect only write files, as the real ones can).
Expectations come from the product owner's T4 decision of 23 Nov 2026, recorded in the E13
spec's Changes: the driver commits whatever a role without shell access leaves behind (the
spec-writer, the architect and the others in the same way), as it already does for the
reviewers' findings and the docs-writer's entry (AC-13, AC-14). A role with a shell commits its
own work. The role cards' tools come from E09: `run` with no `[scope].run` is a shell.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

import pipeline
from tests._pipeline import (
    DESIGN_REL,
    JOB,
    SPEC_REL,
    TASK_REL,
    design_text,
    git,
    spec_text,
    task_text,
)
from tests._pipeline_driver import (
    KIT_AGENTS,
    FakeRunner,
    call,
    calls,
    driver_repo,
    new_job,
    read,
    script,
    use_runner,
)

PLAN_BRANCH = f"factory/{JOB}-p1"
SPEC_ONLY = [{"write": {SPEC_REL: spec_text()}}]
DESIGN_ONLY = [{"write": {DESIGN_REL: design_text(), TASK_REL: task_text()}}]


class Runner(FakeRunner):
    """The fake runner, keeping a dirty worktree on close as E16 does (with a warning), and,
    with `commits=False`, running `_commit` commands as successes that commit nothing."""

    def __init__(self, root: Path, *, commits: bool = True) -> None:
        super().__init__(root)
        self.commits = commits

    def send(self, job_id: str, argv: Sequence[str]) -> None:
        if self.commits or "_commit" not in argv:
            super().send(job_id, argv)
            return
        self.calls.append(("send", job_id, *argv))
        log = self.wt_root / f"{job_id}-commit.log"
        log.write_text("", encoding="utf-8")
        self.jobs[job_id]["commands"].append({"argv": list(argv), "exit_code": 0, "log": str(log)})

    def close(self, job_id: str) -> None:
        job = self.jobs[job_id]
        if git(Path(job["worktree"]), "status", "--porcelain").strip():
            self.calls.append(("close", job_id))
            job["closed"], job["status"] = True, "succeeded"
            return
        super().close(job_id)


def ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    turns: dict[str, Any],
    commits: bool = True,
) -> tuple[Path, FakeRunner, Path]:
    root = driver_repo(tmp_path, monkeypatch)
    log = script(tmp_path, monkeypatch, turns)
    fake = use_runner(monkeypatch, Runner(root, commits=commits))
    new_job(root, monkeypatch, capsys, tmp_path)
    return root, fake, log


def run(root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> int:
    return call(root, monkeypatch, capsys, "run", JOB)[0]


def roles(root: Path, stage: str) -> list[str]:
    return [s["role"] for s in read(root)["sessions"] if s["stage"] == stage]


@pytest.mark.ac("E13-AC-20")
def test_the_driver_commits_the_spec_the_spec_writer_only_wrote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, fake, _ = ready(tmp_path, monkeypatch, capsys, {"spec-writer": [SPEC_ONLY]})
    assert run(root, monkeypatch, capsys) == 0
    record = read(root)
    assert (record["status"], record["stage"]) == ("awaiting-approval", "spec")
    assert roles(root, "spec") == ["spec-writer", "commit"]
    [commit] = [s for s in record["sessions"] if s["role"] == "commit"]
    assert commit["argv"][-4:] == ["_commit", "docs(E31): spec from the spec-writer", "--", "."]
    assert git(root, "show", f"{PLAN_BRANCH}:{SPEC_REL}") == spec_text()
    subject = git(root, "log", "-1", "--format=%s", PLAN_BRANCH).strip()
    assert subject == "docs(E31): spec from the spec-writer"
    assert fake.jobs[f"{JOB}-p1"]["status"] == "succeeded"


@pytest.mark.ac("E13-AC-20")
def test_the_driver_commits_the_design_and_tasks_the_architect_only_wrote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    turns = {"spec-writer": [SPEC_ONLY], "architect": [DESIGN_ONLY]}
    root, _, _ = ready(tmp_path, monkeypatch, capsys, turns)
    assert run(root, monkeypatch, capsys) == 0
    assert call(root, monkeypatch, capsys, "approve", JOB, "spec", "--by", "po")[0] == 0
    assert run(root, monkeypatch, capsys) == 0
    record = read(root)
    assert (record["status"], record["stage"]) == ("awaiting-approval", "design")
    assert roles(root, "design") == ["architect", "commit"]
    branch = record["runs"][-1]["branch"]
    assert git(root, "show", f"{branch}:{TASK_REL}") == task_text()
    subject = git(root, "log", "-1", "--format=%s", branch).strip()
    assert subject == "docs(E31): design from the architect"


@pytest.mark.ac("E13-AC-20")
def test_a_role_that_committed_its_own_work_gets_no_driver_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    turns = {"spec-writer": [[*SPEC_ONLY, {"commit": "docs(E31): spec"}]]}
    root, _, _ = ready(tmp_path, monkeypatch, capsys, turns)
    assert run(root, monkeypatch, capsys) == 0
    assert roles(root, "spec") == ["spec-writer"]


@pytest.mark.ac("E13-AC-20")
def test_a_failed_session_s_leftovers_are_not_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _, _ = ready(tmp_path, monkeypatch, capsys, {"spec-writer": [[*SPEC_ONLY, {"exit": 3}]]})
    assert run(root, monkeypatch, capsys) == 1
    record = read(root)
    assert (record["status"], record["stage"]) == ("needs-human", "spec")
    assert "exited 3" in record["reason"]
    assert roles(root, "spec") == ["spec-writer"]
    assert SPEC_REL not in git(root, "ls-tree", "-r", "--name-only", PLAN_BRANCH)


@pytest.mark.ac("E13-AC-20")
def test_a_role_with_a_shell_commits_for_itself_so_its_leftovers_fail_the_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _, log = ready(tmp_path, monkeypatch, capsys, {"spec-writer": [SPEC_ONLY]})
    card = root / ".factory" / "agents" / "core" / "spec-writer.md"
    text = card.read_text(encoding="utf-8")
    card.write_bytes(text.replace('"web"]', '"web", "run"]', 1).encode("utf-8"))
    git(root, "commit", "-q", "-am", "the spec-writer gets a shell")
    assert pipeline.has_shell(root, "spec-writer")
    assert run(root, monkeypatch, capsys) == 1
    assert roles(root, "spec") == ["spec-writer"]
    assert read(root)["status"] == "needs-human"
    assert [c["role"] for c in calls(log)] == ["spec-writer"]


@pytest.mark.ac("E13-AC-20")
def test_a_tree_still_dirty_after_the_driver_s_commit_stops_for_a_human(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    turns = {"spec-writer": [SPEC_ONLY]}
    root, _, _ = ready(tmp_path, monkeypatch, capsys, turns, commits=False)
    assert run(root, monkeypatch, capsys) == 1
    record = read(root)
    assert (record["status"], record["stage"]) == ("needs-human", "spec")
    assert record["reason"] == "spec: the tree is still dirty after the driver's commit"
    assert roles(root, "spec") == ["spec-writer", "commit"]


@pytest.mark.ac("E13-AC-20")
@pytest.mark.parametrize(
    ("role", "shell"),
    [
        ("spec-writer", False),
        ("architect", False),
        ("docs-writer", False),
        ("verifier", False),  # its `run` is held to its scope's prefixes
        ("adversary", True),
        ("implementer", True),
        ("integrator", True),
    ],
)
def test_a_shell_is_run_with_no_run_scope(role: str, shell: bool) -> None:
    assert pipeline.has_shell(KIT_AGENTS.parent.parent, role) is shell
