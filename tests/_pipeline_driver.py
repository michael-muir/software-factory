"""Helpers for the E13 driver tests: a repo the driver can work in, a scripted fake agent, and a
fake runner that runs each command at once in a real git worktree.

The runner's contract comes from E16 (`run.py submit --open`, `send`, `close`, `usage`, `cancel`,
`status --json`: the record's `status`, `reason`, `branch`, `worktree` and `commands`, each with
its `exit_code` and `log`). The job's contract comes from E18 (`jobs.py`). The driver's
expectations come from the E13 spec (AC-02 to AC-11) and the design note ("The driver").
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

import pipeline
from tests._ac import REPO_ROOT
from tests._pipeline import (
    CHANGELOG,
    DESIGN_REL,
    EPIC,
    JOB,
    SPEC_REL,
    TASK_REL,
    design_text,
    git,
    spec_text,
    task_text,
)

FAKE_AGENT = REPO_ROOT / "tests" / "fixtures" / "pipeline" / "fake_agent.py"
KIT_AGENTS = REPO_ROOT / "kit" / ".factory" / "agents"
JOBS_PY = REPO_ROOT / "kit" / ".factory" / "control" / "jobs.py"
AGENT_COMMAND = [sys.executable, str(FAKE_AGENT), "--role", "{role}"]
AGENT_COMMAND += ["--allowed", "{allowed_tools}", "{prompt}"]
IDENTITY = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}


def config_text(checkpoints: Sequence[str] = ("spec", "design", "merge"), **extra: str) -> str:
    lines = ["[pipeline]", f"checkpoints = {json.dumps(list(checkpoints))}"]
    lines.append(f"agent_command = {json.dumps(AGENT_COMMAND)}")
    lines.append('forge = "git"')
    lines += [f"{key} = {value}" for key, value in extra.items()]
    return "\n".join(lines) + "\n"


def driver_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: str | None = None) -> Path:
    """A repo on main with the kit's role cards, a changelog and a [pipeline] config that runs
    the fake agent; git identities are set for the agent's and the approvals' commits."""
    for key, value in IDENTITY.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("FACTORY_SESSION", raising=False)
    root = tmp_path / "proj"
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    shutil.copytree(KIT_AGENTS, root / ".factory" / "agents")
    (root / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    (root / ".agentic").mkdir()
    (root / ".agentic" / "config.toml").write_text(config or config_text(), encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "fixture")
    return root


def script(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, turns: Mapping[str, Any]) -> Path:
    """Write the fake agent's script and log paths into the environment; return the log."""
    path = tmp_path / "agent-script.json"
    path.write_text(json.dumps(turns), encoding="utf-8")
    log = tmp_path / "agent-log.jsonl"
    monkeypatch.setenv("FAKE_AGENT_SCRIPT", str(path))
    monkeypatch.setenv("FAKE_AGENT_LOG", str(log))
    return log


def calls(log: Path) -> list[dict[str, Any]]:
    if not log.is_file():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]


SPEC_TURN = [{"write": {SPEC_REL: spec_text()}}, {"commit": "docs(E31): spec"}]
SPEC_REVISED = [
    {"write": {SPEC_REL: spec_text().replace("## Goal\n\nWidgets.", "## Goal\n\nSmall widgets.")}},
    {"commit": "docs(E31): spec, revised"},
]
DESIGN_TURN = [
    {"write": {DESIGN_REL: design_text(), TASK_REL: task_text()}},
    {"commit": "docs(E31): design and tasks"},
]
PLAN = {"spec-writer": [SPEC_TURN], "architect": [DESIGN_TURN]}


# --- a fake E16 runner --------------------------------------------------------------------------


class FakeRunner:
    """E16's commands, done at once: `send` runs the command to its end before returning."""

    def __init__(self, root: Path, *, halt_on: str = "", fail_send: bool = False) -> None:
        self.root = root
        self.wt_root = root.parent / "worktrees"
        self.jobs: dict[str, dict[str, Any]] = {}
        self.usd: dict[str, list[str]] = {}
        self.calls: list[tuple[str, ...]] = []
        self.halt_on = halt_on  # halt the job ("turn cap (3)") when a command holding this runs
        self.fail_send = fail_send

    def submit(self, job_id: str, base: str, task: str) -> None:
        self.calls.append(("submit", job_id, base, task))
        if job_id in self.jobs:
            raise pipeline.RunnerError(f"job {job_id} already exists")
        worktree = self.wt_root / job_id
        git(self.root, "worktree", "add", "-q", "-b", f"factory/{job_id}", str(worktree), base)
        self.jobs[job_id] = {
            "id": job_id,
            "status": "running",
            "reason": "",
            "base": base,
            "task": task,
            "branch": f"factory/{job_id}",
            "worktree": str(worktree),
            "closed": False,
            "usd": 0.0,
            "commands": [],
        }

    def send(self, job_id: str, argv: Sequence[str]) -> None:
        self.calls.append(("send", job_id, *argv))
        job = self.jobs[job_id]
        if job["closed"] or job["status"] != "running" or self.fail_send:
            raise pipeline.RunnerError(f"job {job_id} is {job['status']}")
        n = len(job["commands"]) + 1
        log = self.wt_root / f"{job_id}-{n:04d}.log"
        entry: dict[str, Any] = {"argv": list(argv), "exit_code": None, "log": str(log)}
        job["commands"].append(entry)
        if self.halt_on and any(self.halt_on in item for item in argv):
            job["status"], job["reason"] = "halted", "turn cap (3)"
            return
        env = {**os.environ, "FACTORY_JOB": job_id}
        with log.open("wb") as out:
            done = subprocess.run(
                list(argv), cwd=job["worktree"], env=env, stdout=out, stderr=subprocess.STDOUT
            )
        entry["exit_code"] = done.returncode

    def close(self, job_id: str) -> None:
        self.calls.append(("close", job_id))
        job = self.jobs[job_id]
        job["closed"] = True
        if job["status"] != "running":
            return
        codes = [c["exit_code"] for c in job["commands"]]
        if not codes or codes[-1] == 0:
            job["status"] = "succeeded"
            git(self.root, "worktree", "remove", job["worktree"])
        else:
            job["status"], job["reason"] = "failed", f"the last command exited {codes[-1]}"

    def status(self, job_id: str) -> dict[str, Any]:
        job = self.jobs[job_id]
        copy: dict[str, Any] = json.loads(
            json.dumps({**job, "usd": sum(float(u) for u in self.usd.get(job_id, []))})
        )
        return copy

    def usage(self, job_id: str, usd: str) -> None:
        self.calls.append(("usage", job_id, usd))
        self.usd.setdefault(job_id, []).append(usd)

    def cancel(self, job_id: str) -> None:
        self.calls.append(("cancel", job_id))
        job = self.jobs[job_id]
        if job["status"] == "running":
            job["status"], job["reason"] = "halted", "cancelled"


def use_runner(monkeypatch: pytest.MonkeyPatch, runner: FakeRunner) -> FakeRunner:
    monkeypatch.setattr(pipeline, "runner_for", lambda root: runner)
    return runner


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


def request_file(tmp_path: Path, text: str = "Make widgets.\n\nThey should be small.\n") -> Path:
    path = tmp_path / "request.md"
    path.write_text(text, encoding="utf-8")
    return path


def new_job(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    job: str = JOB,
) -> None:
    args = ("new", job, "--epic", EPIC, "--request-file", str(request_file(tmp_path)))
    code, _, err = call(root, monkeypatch, capsys, *args)
    assert code == 0, err


def read(root: Path, job: str = JOB) -> dict[str, Any]:
    return pipeline.read_record(root, job)


def e18(root: Path, job: str = JOB) -> dict[str, Any]:
    """E18's record of the job, read straight from its file (E18 design, "Job records")."""
    import tomllib

    common = git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    with (Path(common) / "factory" / "work" / f"{job}.toml").open("rb") as f:
        return tomllib.load(f)


def jobs_module() -> Any:
    """E18's jobs.py, loaded from the kit, for leases."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("e13_test_jobs", JOBS_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["e13_test_jobs"] = module
    spec.loader.exec_module(module)
    return module
