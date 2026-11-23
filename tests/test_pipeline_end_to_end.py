"""E13/T4: the done-when. A job goes from `new` to `done` on a real E16 daemon, end to end.

Covers E13 AC-20. Expectations come from the E13 spec (AC-20, and AC-09, AC-11, AC-12, AC-13 and
AC-16 for the further runs), the design note ("Test seams": the done-when) and the product
owner's T4 decision of 23 Nov 2026: the driver commits what a role without a shell leaves behind,
so the fake spec-writer and architect here only write their files, as the real ones can.

Each test builds a temp repo with the kit installed by `install.py`, a local bare origin, and a
real `run.py --daemon`. The installed `pipeline.py` runs as a command, with the real `jobs.py`
and the plain-git forge. `fake_agent.py` plays every role, scripted per role, and `fake_gate.py`
stands in for the full gate. The config sets `forge = "git"` and all three checkpoints. The test
approves by command and merges each slice into the origin's main itself, as a human would.
"""

from __future__ import annotations

import decimal
import json
import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from tests._ac import REPO_ROOT
from tests._pipeline import (
    CHANGELOG,
    DESIGN_REL,
    JOB,
    SPEC_REL,
    TASK,
    design_text,
    git,
    sidecar,
    spec_text,
    task_text,
)
from tests._pipeline_driver import AGENT_COMMAND, IDENTITY
from tests._pipeline_slices import (
    BRANCH1,
    BRANCH2,
    DEBUG_FIX,
    FAKE_GATE,
    TASK2,
    TEST2_REL,
    TESTS2,
    finding,
    slice_turns,
    turns,
)

pytestmark = pytest.mark.slow

INSTALL_PY = REPO_ROOT / "install.py"
PIPELINE = ".factory/workflow/pipeline.py"
RUN = ".factory/runner/run.py"
DOCS = ".factory/workflow/docs.py"
TIMEOUT = 600  # seconds for one command; a whole run of the line takes far less
PLAN_ORDER = ["spec", "design"]
SLICE_ORDER = ["test", "build", "gate", "review", "docs", "ship"]
ONE = {TASK: "E31 AC-01, AC-02."}
TWO = {TASK: "E31 AC-01.", TASK2: "E31 AC-02."}
NOTE = "Say that the widgets are small."


def plan_turns(tasks: Mapping[str, str], *, revised: bool = False) -> dict[str, Any]:
    """The spec-writer's and the architect's turns. Neither commits: they have no shell."""
    files = {DESIGN_REL: design_text()}
    files.update({f".agentic/tasks/{task}.md": task_text(task, acs) for task, acs in tasks.items()})
    spec = [[{"write": {SPEC_REL: spec_text()}}]]
    if revised:
        small = spec_text().replace("## Goal\n\nWidgets.", "## Goal\n\nSmall widgets.")
        spec.append([{"write": {SPEC_REL: small}}])
    return {"spec-writer": spec, "architect": [[{"write": files}]]}


def _set_key(text: str, key: str, value: object) -> str:
    """Set one `key = value` line of the installed config, keeping its section."""
    new, count = re.subn(
        rf"(?m)^{re.escape(key)} = .*$", f"{key} = {json.dumps(value)}", text, count=1
    )
    assert count == 1, f"the installed config has no {key} line"
    return new


class Line:
    """The production line in a temp repo: the installed kit, a bare origin and a daemon."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        for key, value in IDENTITY.items():
            monkeypatch.setenv(key, value)
        for key in ("FACTORY_SESSION", "FACTORY_ROLE", "FACTORY_JOB"):
            monkeypatch.delenv(key, raising=False)
        self.tmp = tmp_path
        self.script_path = tmp_path / "agent-script.json"
        self.agent_log = tmp_path / "agent-log.jsonl"
        monkeypatch.setenv("FAKE_AGENT_SCRIPT", str(self.script_path))
        monkeypatch.setenv("FAKE_AGENT_LOG", str(self.agent_log))
        monkeypatch.setenv("FAKE_GATE_LOG", str(tmp_path / "gate-log.jsonl"))
        self.root = tmp_path / "proj"
        self.root.mkdir()
        git(self.root, "init", "-q", "-b", "main")
        subprocess.run(
            [sys.executable, str(INSTALL_PY), str(self.root)],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        config = self.root / ".agentic" / "config.toml"
        text = config.read_text(encoding="utf-8")
        text = _set_key(text, "checkpoints", ["spec", "design", "merge"])
        text = _set_key(text, "agent_command", AGENT_COMMAND)
        text = _set_key(text, "forge", "git")
        text = _set_key(text, "python_command", [sys.executable, str(FAKE_GATE)])
        config.write_bytes(text.encode("utf-8"))
        (self.root / "CHANGELOG.md").write_bytes(CHANGELOG.encode("utf-8"))
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "the kit, installed")
        self.start = git(self.root, "rev-parse", "HEAD").strip()
        self.origin = tmp_path / "origin.git"
        git(tmp_path, "init", "-q", "--bare", "-b", "main", str(self.origin))
        git(self.root, "remote", "add", "origin", str(self.origin))
        git(self.root, "push", "-q", "origin", "main")
        git(self.root, "fetch", "-q", "origin")
        self.daemon: subprocess.Popen[bytes] | None = None

    # -- the daemon

    def start_daemon(self) -> None:
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
        with (self.tmp / "daemon.log").open("wb") as log:
            self.daemon = subprocess.Popen(
                [sys.executable, RUN, "--daemon"],
                cwd=self.root,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=flags,
            )

    def stop_daemon(self) -> None:
        if self.daemon is None:
            return
        self.command(RUN, "stop")
        try:
            self.daemon.wait(timeout=60)
        except subprocess.TimeoutExpired:
            self.daemon.kill()
            self.daemon.wait(timeout=30)

    # -- commands

    def command(self, tool: str, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, tool, *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT,
            check=False,
        )

    def pipeline(self, *args: str) -> subprocess.CompletedProcess[str]:
        return self.command(PIPELINE, *args)

    def ok(self, *args: str) -> str:
        done = self.pipeline(*args)
        assert done.returncode == 0, done.stdout + done.stderr
        return done.stdout

    def run(self) -> int:
        return self.pipeline("run", JOB).returncode

    def script(self, script_turns: Mapping[str, Any]) -> None:
        self.script_path.write_text(json.dumps(script_turns), encoding="utf-8")

    def new(self) -> None:
        request = self.tmp / "request.md"
        request.write_text("Make widgets.\n", encoding="utf-8")
        self.ok("new", JOB, "--epic", "E31", "--request-file", str(request), "--title", "Widgets")

    def to_ship(self) -> int:
        """Run the plan, approving the spec and the design, then run the first slice."""
        assert self.run() == 0
        self.ok("approve", JOB, "spec", "--by", "po")
        assert self.run() == 0
        self.ok("approve", JOB, "design", "--by", "po")
        return self.run()

    # -- what the line left

    def record(self) -> dict[str, Any]:
        with sidecar(self.root, JOB, "pipeline").open("rb") as f:
            return tomllib.load(f)

    def summary(self) -> dict[str, Any]:
        with sidecar(self.root, JOB, "summary").open("rb") as f:
            return tomllib.load(f)

    def e18(self) -> dict[str, Any]:
        with (sidecar(self.root, JOB, "pipeline").parent / f"{JOB}.toml").open("rb") as f:
            return tomllib.load(f)

    def entry(self, task: str) -> dict[str, Any]:
        found: dict[str, Any] = next(t for t in self.record()["tasks"] if t["id"] == task)
        return found

    def merge(self, task: str) -> str:
        """Merge the task's pushed head into the origin's main, as a human would."""
        head = str(self.entry(task)["head"])
        git(self.root, "push", "-q", "origin", f"{head}:refs/heads/main")
        return head

    def calls(self) -> list[dict[str, Any]]:
        if not self.agent_log.is_file():
            return []
        text = self.agent_log.read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines() if line]

    def runner_usd(self, run_id: str) -> decimal.Decimal:
        done = self.command(RUN, "status", run_id, "--json")
        assert done.returncode == 0, done.stdout + done.stderr
        return decimal.Decimal(str(json.loads(done.stdout)["usd"]))


@pytest.fixture
def line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Line]:
    built = Line(tmp_path, monkeypatch)
    built.start_daemon()
    try:
        yield built
    finally:
        built.stop_daemon()


def stages_of(record: Mapping[str, Any], task: str) -> list[str]:
    """The stages the task's sessions ran in, in the order they first ran."""
    seen: list[str] = []
    for session in record["sessions"]:
        if session["task"] == task and session["stage"] not in seen:
            seen.append(session["stage"])
    return seen


def roles_in(record: Mapping[str, Any], name: str, task: str) -> list[str]:
    return [s["role"] for s in record["sessions"] if s["stage"] == name and s["task"] == task]


def rev_list(root: Path, base: str, head: str) -> list[str]:
    return git(root, "rev-list", f"{base}..{head}").split()


# --- the done-when: two tasks from new to done -------------------------------------------------


@pytest.mark.ac("E13-AC-20")
def test_a_two_task_job_goes_from_new_to_done_on_a_real_daemon(line: Line) -> None:
    second = slice_turns(TASK2, {TEST2_REL: TESTS2})
    line.script(turns(plan_turns(TWO), slice_turns(), second))
    line.new()

    assert line.run() == 0
    assert (line.record()["status"], line.record()["stage"]) == ("awaiting-approval", "spec")
    line.ok("approve", JOB, "spec", "--by", "po")
    assert line.run() == 0
    assert (line.record()["status"], line.record()["stage"]) == ("awaiting-approval", "design")
    line.ok("approve", JOB, "design", "--by", "po")
    assert line.run() == 0
    first = line.record()
    assert (first["status"], first["stage"], first["task"]) == ("awaiting-merge", "ship", TASK)
    assert line.e18()["status"] == "blocked"
    assert stages_of(first, TASK2) == [], "the second task started before the first merged"
    assert line.run() == 0
    assert line.record() == first, "run changed the job before the PR merged"

    head1 = line.merge(TASK)
    assert line.run() == 0
    assert (line.record()["status"], line.record()["task"]) == ("awaiting-merge", TASK2)
    head2 = line.merge(TASK2)
    assert line.run() == 0

    record = line.record()
    assert (record["status"], record["stage"], record["reason"]) == ("done", "learn", "")
    assert (line.e18()["status"], line.e18()["phase"]) == ("done", "learn")

    # every stage ran in order for each task, and the driver committed the plan roles' work
    assert stages_of(record, JOB) == PLAN_ORDER
    assert roles_in(record, "spec", JOB) == ["spec-writer", "commit"]
    assert roles_in(record, "design", JOB) == ["architect", "commit"]
    for task in (TASK, TASK2):
        assert stages_of(record, task) == SLICE_ORDER, task
        assert roles_in(record, "ship", task) == ["integrator", "push"], task
    tasks = [s["task"] for s in record["sessions"]]
    assert tasks.index(TASK2) > max(i for i, t in enumerate(tasks) if t == TASK)

    # the second task started from the fetched origin, after the first had merged
    t2_runs = [r for r in record["runs"] if r["task"] == TASK2]
    assert t2_runs[0]["base"] == "origin/main"
    git(line.root, "merge-base", "--is-ancestor", head1, head2)

    # every PR body passes check-pr --strict for its branch's commits, on the merged main
    git(line.root, "merge", "-q", "--ff-only", "origin/main")
    for task, base, head in ((TASK, line.start, head1), (TASK2, head1, head2)):
        body = line.tmp / f"{task}-body.md"
        body.write_bytes(str(line.entry(task)["pr_body"]).encode("utf-8"))
        commits = rev_list(line.root, base, head)
        assert commits, task
        args = ("--root", ".", "check-pr", "--strict", str(body), "--commits", *commits)
        done = line.command(DOCS, *args)
        assert done.returncode == 0, f"{task}: {done.stdout}{done.stderr}"

    # the fake agent's cost reached the record and the runner's ledger
    role_sessions = [
        s for s in record["sessions"] if s["role"] not in ("gate", "commit", "round", "push")
    ]
    assert role_sessions and all(s.get("usd") == "0.01" for s in role_sessions)
    for run in record["runs"]:
        recorded = sum(
            (
                decimal.Decimal(str(s.get("usd", "0")))
                for s in record["sessions"]
                if s["run"] == run["id"]
            ),
            start=decimal.Decimal(0),
        )
        assert line.runner_usd(run["id"]) == recorded, run["id"]
    assert not record["warnings"]

    # the summary lists both PRs
    summary = line.summary()
    prs = [(p["task"], p["pr"], p["merged"]) for p in summary["prs"]]
    assert prs == [(TASK, BRANCH1, True), (TASK2, BRANCH2, True)]
    total = sum(
        (decimal.Decimal(str(s.get("usd", "0"))) for s in record["sessions"]),
        start=decimal.Decimal(0),
    )
    assert decimal.Decimal(str(summary["total_usd"])) == total > 0
    assert line.pipeline("run", JOB).returncode == 1  # a done job is refused


# --- the further runs ---------------------------------------------------------------------------


@pytest.mark.ac("E13-AC-20")
def test_a_red_gate_that_the_debugger_fixes_carries_on_to_the_merge(line: Line) -> None:
    line.script(turns(plan_turns(ONE), slice_turns(red=True), {f"debugger@{TASK}": [DEBUG_FIX]}))
    line.new()
    assert line.to_ship() == 0
    record = line.record()
    assert (record["status"], record["stage"]) == ("awaiting-merge", "ship")
    assert roles_in(record, "gate", TASK) == ["gate", "debugger", "gate"]
    verdicts = [g["verdict"] for g in record["gates"] if g["task"] == TASK]
    assert verdicts[:2] == ["fail", "pass"]
    [debugger] = [c for c in line.calls() if c["role"] == "debugger"]
    assert "The full gate failed" in debugger["prompt"]
    line.merge(TASK)
    assert line.run() == 0
    assert line.record()["status"] == "done"


@pytest.mark.ac("E13-AC-20")
def test_a_blocker_finding_stops_the_job_for_a_human_before_docs(line: Line) -> None:
    blocker = {f"spec-reviewer@{TASK}": [[finding(TASK, "blocker", "Widgets lose data")]]}
    line.script(turns(plan_turns(ONE), slice_turns(), blocker))
    line.new()
    assert line.to_ship() == 1
    record = line.record()
    assert (record["status"], record["stage"]) == ("needs-human", "review")
    assert "Widgets lose data" in record["reason"]
    assert stages_of(record, TASK)[-1] == "review"
    assert line.e18()["status"] == "blocked"
    committed = git(line.root, "show", f"{record['runs'][-1]['branch']}:.agentic/tasks/{TASK}.md")
    assert "Widgets lose data" in committed
    assert line.run() == 1  # it stays stopped until a human resumes it
    assert line.record()["status"] == "needs-human"


@pytest.mark.ac("E13-AC-20")
def test_a_rejected_spec_sends_the_spec_writer_again_with_the_note(line: Line) -> None:
    line.script(plan_turns(ONE, revised=True))
    line.new()
    assert line.run() == 0
    line.ok("reject", JOB, "spec", "--by", "po", "--note", NOTE)
    assert line.run() == 0
    record = line.record()
    assert (record["status"], record["stage"]) == ("awaiting-approval", "spec")
    writers = [c for c in line.calls() if c["role"] == "spec-writer"]
    assert len(writers) == 2
    assert NOTE not in writers[0]["prompt"] and NOTE in writers[1]["prompt"]
    branch = record["runs"][-1]["branch"]
    assert "Small widgets." in git(line.root, "show", f"{branch}:{SPEC_REL}")
    line.ok("approve", JOB, "spec", "--by", "po")
    assert line.run() == 0
    record = line.record()
    assert (record["status"], record["stage"]) == ("awaiting-approval", "design")
    assert [d["verdict"] for d in record["decisions"]] == ["reject", "approve"]


@pytest.mark.ac("E13-AC-20")
def test_a_slice_pr_closed_without_merging_stops_the_job_for_a_human(line: Line) -> None:
    line.script(turns(plan_turns(ONE), slice_turns()))
    line.new()
    assert line.to_ship() == 0
    git(line.root, "push", "-q", "origin", "--delete", BRANCH1)
    assert line.run() == 1
    record = line.record()
    assert (record["status"], record["stage"]) == ("needs-human", "ship")
    assert "closed without merging" in record["reason"]
    assert line.entry(TASK)["merged"] is False
    assert line.e18()["status"] == "blocked"
