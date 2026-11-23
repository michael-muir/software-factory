"""Helpers for the E13 slice-stage tests: a repo with a local bare origin, a fake gate, scripted
turns for every slice role, merges made by the test, and a stub `gh` for the GitHub forge.

The expectations come from the E13 spec (AC-12 to AC-17), the design note ("The driver",
"Forges and approvals", "The records") and ADR 0043. The made-up epic is E31, with two tasks:
E31-T1 covers AC-01 and E31-T2 covers AC-02.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from tests._ac import REPO_ROOT
from tests._pipeline import (
    DESIGN_REL,
    JOB,
    SPEC_REL,
    TASK,
    TESTS,
    design_text,
    git,
    spec_text,
    task_text,
)
from tests._pipeline_driver import (
    FakeRunner,
    call,
    config_text,
    driver_repo,
    new_job,
    read,
    script,
    use_runner,
)

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "pipeline"
FAKE_GATE = FIXTURES / "fake_gate.py"
DRAFT_PR_BODY = FIXTURES / "draft_pr_body.py"
STATE_PY = REPO_ROOT / "kit" / ".factory" / "state" / "state.py"
AGENTS_PY = REPO_ROOT / "kit" / ".factory" / "agents" / "agents.py"
TASK2 = "E31-T2"
TASK2_REL = ".agentic/tasks/E31-T2.md"
TEST2_REL = "tests/test_widgets_two.py"
RED = "GATE-RED"
BRANCH1 = f"factory/{JOB}-t1"
BRANCH2 = f"factory/{JOB}-t2"
GITHUB_URL = "https://github.com/acme/widgets.git"

TESTS2 = """import pytest


@pytest.mark.ac("E31-AC-02")
def test_widgets_do_two_again() -> None:
    assert False
"""


def slice_config(
    checkpoints: Sequence[str] = ("spec", "merge"), *, forge: str = "git", gate_retries: int = 2
) -> str:
    """The driver's config: the fake agent, the fake gate as `gates.python_command`."""
    text = config_text(checkpoints, gate_retries=str(gate_retries))
    text = text.replace('forge = "git"', f"forge = {json.dumps(forge)}")
    gate = json.dumps([sys.executable, str(FAKE_GATE)])
    return text + f'\n[gates]\nbase_ref = "main"\npython_command = {gate}\n'


def origin_of(root: Path) -> Path:
    return root.parent / "origin.git"


def slice_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: str | None = None) -> Path:
    """driver_repo with a STATE.md (so `state.py` works in its worktrees), plus a local bare
    origin that holds main."""
    import subprocess

    root = driver_repo(tmp_path, monkeypatch, config or slice_config())
    subprocess.run(
        [sys.executable, str(STATE_PY), "--root", str(root), "init"],
        check=True,
        capture_output=True,
    )
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "state")
    bare = origin_of(root)
    git(root.parent, "init", "-q", "--bare", "-b", "main", str(bare))
    git(root, "remote", "add", "origin", str(bare))
    git(root, "push", "-q", "origin", "main")
    git(root, "fetch", "-q", "origin")
    return root


# --- the fake agent's turns -----------------------------------------------------------------


def commit(message: str) -> dict[str, Any]:
    return {"commit": message}


def run(*argv: str) -> dict[str, Any]:
    return {"run": list(argv)}


def add_entry(line: str) -> dict[str, Any]:
    """Add a line under `## [Unreleased]` in CHANGELOG.md, keeping the rest."""
    code = (
        "import sys; from pathlib import Path; p = Path('CHANGELOG.md'); "
        "t = p.read_text(encoding='utf-8'); "
        "p.write_bytes(t.replace('## [Unreleased]\\n', '## [Unreleased]\\n\\n' + sys.argv[1] "
        "+ '\\n', 1).encode('utf-8'))"
    )
    return run(sys.executable, "-c", code, line)


def finding(task: str, severity: str, summary: str) -> dict[str, Any]:
    return run(
        sys.executable, str(STATE_PY), "finding", "add", task, "--severity", severity, summary
    )


def two_task_plan() -> dict[str, Any]:
    """Spec and architect turns for a plan with two tasks."""
    files = {
        DESIGN_REL: design_text(),
        ".agentic/tasks/E31-T1.md": task_text(TASK, "E31 AC-01."),
        TASK2_REL: task_text(TASK2, "E31 AC-02."),
    }
    return {
        "spec-writer": [[{"write": {SPEC_REL: spec_text()}}, commit("docs(E31): spec")]],
        "architect": [[{"write": files}, commit("docs(E31): design and tasks")]],
    }


def one_task_plan() -> dict[str, Any]:
    files = {DESIGN_REL: design_text(), ".agentic/tasks/E31-T1.md": task_text()}
    return {
        "spec-writer": [[{"write": {SPEC_REL: spec_text()}}, commit("docs(E31): spec")]],
        "architect": [[{"write": files}, commit("docs(E31): design and tasks")]],
    }


def slice_turns(
    task: str = TASK,
    tests: Mapping[str, str] | None = None,
    *,
    red: bool = False,
    entry: bool = True,
    leave_todo: bool = False,
) -> dict[str, Any]:
    """Turns for one slice: tests locked, code, the docs-writer's entry and the PR body.
    Reviewers have no turns, so they record nothing."""
    tests = {"tests/test_widgets.py": TESTS} if tests is None else tests
    n = task.rsplit("T", 1)[1]
    code: dict[str, str] = {f"widgets_{n}.py": "WIDGETS = 1\n"}
    if red:
        code[RED] = "red\n"
    lock = run(sys.executable, str(AGENTS_PY), "lock", task, *tests)
    draft = [sys.executable, str(DRAFT_PR_BODY), task]
    if leave_todo:
        draft.append("--leave-todo")
    return {
        f"test-designer@{task}": [[{"write": dict(tests)}, lock, commit(f"test({task}): lock")]],
        f"implementer@{task}": [[{"write": code}, commit(f"feat({task}): widgets")]],
        f"docs-writer@{task}": [[add_entry(f"- Widgets for {task}.")] if entry else []],
        f"integrator@{task}": [[run(*draft)]],
    }


def turns(*parts: Mapping[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for part in parts:
        merged.update(part)
    return merged


DEBUG_FIX = [run("git", "rm", "-q", RED), commit("fix: the gate is green again")]


# --- driving a job --------------------------------------------------------------------------


def start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    script_turns: Mapping[str, Any],
    config: str | None = None,
    **runner: Any,
) -> tuple[Path, FakeRunner, Path]:
    """A repo with an origin, the scripted agent, a fake runner and a new job."""
    root = slice_repo(tmp_path, monkeypatch, config)
    log = script(tmp_path, monkeypatch, script_turns)
    monkeypatch.setenv("FAKE_GATE_LOG", str(tmp_path / "gate-log.jsonl"))
    fake = use_runner(monkeypatch, FakeRunner(root, **runner))
    new_job(root, monkeypatch, capsys, tmp_path)
    return root, fake, log


def drive(root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> int:
    return call(root, monkeypatch, capsys, "run", JOB)[0]


def to_slices(
    root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> int:
    """Run the spec stage, approve it, and run on (the config has no design checkpoint)."""
    assert drive(root, monkeypatch, capsys) == 0
    assert call(root, monkeypatch, capsys, "approve", JOB, "spec", "--by", "po")[0] == 0
    return drive(root, monkeypatch, capsys)


def gate_calls(tmp_path: Path) -> list[dict[str, Any]]:
    path = tmp_path / "gate-log.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def task_entry(root: Path, task: str = TASK) -> dict[str, Any]:
    entry: dict[str, Any] = next(t for t in read(root)["tasks"] if t["id"] == task)
    return entry


def merge(root: Path, task: str = TASK) -> str:
    """Merge the task's pushed head into the origin's main, as a human would (fast-forward)."""
    head = str(task_entry(root, task)["head"])
    git(root, "push", "-q", "origin", f"{head}:refs/heads/main")
    return head


def close_unmerged(root: Path, branch: str = BRANCH1) -> None:
    """Close the PR without merging: for the git forge, the pushed branch goes away."""
    git(root, "push", "-q", "origin", "--delete", branch)


def remote_head(root: Path, branch: str) -> str:
    """The branch's commit in the bare origin, or "" when it has none."""
    import subprocess

    done = subprocess.run(
        ["git", "rev-parse", "--verify", "-q", f"refs/heads/{branch}"],
        cwd=origin_of(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return done.stdout.strip()


# --- a stub gh for the GitHub forge -----------------------------------------------------------


def fake_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answers: Mapping[str, Any]) -> Path:
    """A `gh` on PATH. It logs each call's argv (and, for `-F body=@FILE`, the file's text) as a
    JSON line, and prints `answers["POST"]` for a call with -f/-F fields, else `answers["GET"]`.
    Change the answers with `gh_answers`. Returns the log."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "gh-calls.jsonl"
    answers_path = tmp_path / "gh-answers.json"
    answers_path.write_text(json.dumps(answers), encoding="utf-8")
    (bin_dir / "gh.py").write_text(
        "import json, sys\n"
        "argv = sys.argv[1:]\n"
        "body = ''\n"
        "for item in argv:\n"
        "    if item.startswith('body=@'):\n"
        "        body = open(item[6:], encoding='utf-8').read()\n"
        f"with open({str(log)!r}, 'a', encoding='utf-8') as f:\n"
        "    f.write(json.dumps({'argv': argv, 'body': body}) + '\\n')\n"
        f"answers = json.load(open({str(answers_path)!r}, encoding='utf-8'))\n"
        "post = any(a in ('-f', '-F') for a in argv)\n"
        "print(json.dumps(answers['POST' if post else 'GET']))\n",
        encoding="utf-8",
    )
    (bin_dir / "gh").write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "{bin_dir / "gh.py"}" "$@"\n', encoding="utf-8"
    )
    (bin_dir / "gh").chmod(0o755)
    (bin_dir / "gh.cmd").write_text(
        f'@"{sys.executable}" "{bin_dir / "gh.py"}" %*\r\n', encoding="utf-8"
    )
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return log


def gh_answers(tmp_path: Path, answers: Mapping[str, Any]) -> None:
    (tmp_path / "gh-answers.json").write_text(json.dumps(answers), encoding="utf-8")


def gh_calls(log: Path) -> list[dict[str, Any]]:
    if not log.is_file():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]


def github_origin(root: Path) -> None:
    """Make origin a GitHub URL, while git's network traffic still goes to the bare origin."""
    bare = origin_of(root)
    git(root, "remote", "set-url", "origin", GITHUB_URL)
    git(root, "config", f"url.{bare.as_posix()}.insteadOf", GITHUB_URL)
