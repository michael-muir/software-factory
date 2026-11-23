"""E13/T3: the ship stage with both forges, merge detection, the next slice and the learn stage.

Covers E13 AC-15, AC-16 and AC-17. Expectations come from the E13 spec (those ACs, "Where things
live"), the design note ("Forges and approvals", "The records") and ADR 0043: the driver checks
the Integrator's body with `check-pr --strict` before anything is pushed, pushes the branch,
opens the PR through the forge (GitHub REST through `gh api`, never GraphQL, or the plain-git
forge), sees the merge a human makes, starts the next task from the fetched base, and at the end
writes the summary sidecar with its closing handoff.
"""

from __future__ import annotations

import decimal
import json
import tomllib
from pathlib import Path
from typing import Any

import pytest

import pipeline
from tests._pipeline import JOB, TASK, commit, git, repo, sidecar
from tests._pipeline_driver import call, calls, e18, read
from tests._pipeline_slices import (
    BRANCH1,
    BRANCH2,
    GITHUB_URL,
    TASK2,
    TEST2_REL,
    TESTS2,
    close_unmerged,
    drive,
    fake_gh,
    finding,
    gh_answers,
    gh_calls,
    github_origin,
    merge,
    one_task_plan,
    origin_of,
    remote_head,
    slice_config,
    slice_turns,
    start,
    task_entry,
    to_slices,
    turns,
    two_task_plan,
)

OPEN = {"number": 17, "state": "open", "merged": False}


def roles(log: Path) -> list[str]:
    return [c["role"] for c in calls(log)]


def summary_of(root: Path) -> dict[str, Any]:
    with sidecar(root, JOB, "summary").open("rb") as f:
        return tomllib.load(f)


# --- AC-15: ship --------------------------------------------------------------------------------


@pytest.mark.ac("E13-AC-15")
def test_ship_checks_the_body_then_pushes_the_branch_and_opens_the_pr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, fake, _ = start(tmp_path, monkeypatch, capsys, turns(one_task_plan(), slice_turns()))
    assert to_slices(root, monkeypatch, capsys) == 0
    record = read(root)
    assert (record["status"], record["stage"]) == ("awaiting-merge", "ship")
    ship = [s for s in record["sessions"] if s["stage"] == "ship"]
    assert [s["role"] for s in ship] == ["integrator", "push"]
    assert ship[1]["argv"] == ["git", "push", "origin", f"HEAD:refs/heads/{BRANCH1}"]
    entry = task_entry(root)
    assert (entry["pr"], entry["branch"]) == (BRANCH1, BRANCH1)
    assert entry["head"] == remote_head(root, BRANCH1) != ""
    assert str(entry["pr_body"]).startswith("E31/T1: ")
    assert fake.jobs[f"{JOB}-t1-1"]["closed"]
    assert e18(root)["status"] == "blocked"


@pytest.mark.ac("E13-AC-15")
def test_a_body_that_fails_check_pr_strict_stops_before_anything_is_pushed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = turns(one_task_plan(), slice_turns(leave_todo=True))
    root, _, _ = start(tmp_path, monkeypatch, capsys, script)
    assert to_slices(root, monkeypatch, capsys) == 1
    record = read(root)
    assert (record["status"], record["stage"]) == ("needs-human", "ship")
    assert "TODO(author)" in record["reason"]
    assert remote_head(root, BRANCH1) == ""
    assert "push" not in [s["role"] for s in record["sessions"]]
    assert task_entry(root)["pr"] == ""


@pytest.mark.ac("E13-AC-15")
def test_an_integrator_that_writes_no_body_stops_the_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = turns(one_task_plan(), slice_turns(), {f"integrator@{TASK}": [[]]})
    root, _, _ = start(tmp_path, monkeypatch, capsys, script)
    assert to_slices(root, monkeypatch, capsys) == 1
    record = read(root)
    assert (record["status"], record["stage"]) == ("needs-human", "ship")
    assert "PR body" in record["reason"]
    assert remote_head(root, BRANCH1) == ""


@pytest.mark.ac("E13-AC-15")
def test_the_github_forge_opens_the_pr_through_the_rest_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = slice_config(forge="github")
    root, _, _ = start(tmp_path, monkeypatch, capsys, turns(one_task_plan(), slice_turns()), config)
    github_origin(root)
    log = fake_gh(tmp_path, monkeypatch, {"POST": OPEN, "GET": OPEN})
    assert to_slices(root, monkeypatch, capsys) == 0
    [opened] = gh_calls(log)
    argv = opened["argv"]
    assert argv[:2] == ["api", "repos/acme/widgets/pulls"]
    fields = [argv[i + 1] for i, item in enumerate(argv) if item in ("-f", "-F")]
    assert f"head={BRANCH1}" in fields and "base=main" in fields
    assert any(f.startswith("title=E31/T1: ") for f in fields)
    assert any(f.startswith("body=@") for f in fields)
    entry = task_entry(root)
    assert opened["body"] == entry["pr_body"]
    assert entry["pr"] == "17"
    assert remote_head(root, BRANCH1) == entry["head"]
    assert read(root)["status"] == "awaiting-merge"


@pytest.mark.ac("E13-AC-15")
@pytest.mark.parametrize("url", [GITHUB_URL, "git@github.com:acme/widgets.git"])
def test_the_github_forge_opens_on_the_origin_s_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    root = repo(tmp_path)
    git(root, "remote", "add", "origin", url)
    log = fake_gh(tmp_path, monkeypatch, {"POST": OPEN, "GET": OPEN})
    forge = pipeline.GitHubForge(root)
    assert forge.open("factory/x-t1", "main", "A title", "The body.\n") == "17"
    [opened] = gh_calls(log)
    assert opened["argv"][:2] == ["api", "repos/acme/widgets/pulls"]
    assert opened["body"] == "The body.\n"
    assert not any("graphql" in item for item in opened["argv"])


# --- AC-16: merge -------------------------------------------------------------------------------


@pytest.mark.ac("E13-AC-16")
def test_run_on_an_awaiting_merge_job_changes_nothing_until_the_pr_merges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, fake, log = start(tmp_path, monkeypatch, capsys, turns(one_task_plan(), slice_turns()))
    assert to_slices(root, monkeypatch, capsys) == 0
    before, sent, agents = read(root), len(fake.calls), len(calls(log))
    assert drive(root, monkeypatch, capsys) == 0
    assert read(root) == before
    assert len(fake.calls) == sent and len(calls(log)) == agents
    assert not sidecar(root, JOB, "summary").exists()


@pytest.mark.ac("E13-AC-16")
def test_a_merged_pr_starts_the_next_task_from_the_newly_fetched_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    second = slice_turns(TASK2, {TEST2_REL: TESTS2})
    root, fake, log = start(
        tmp_path, monkeypatch, capsys, turns(two_task_plan(), slice_turns(), second)
    )
    assert to_slices(root, monkeypatch, capsys) == 0
    assert not [c for c in fake.calls if c[0] == "submit" and c[1] == f"{JOB}-t2-1"]
    merged = merge(root)
    assert drive(root, monkeypatch, capsys) == 0
    submit = next(c for c in fake.calls if c[0] == "submit" and c[1] == f"{JOB}-t2-1")
    assert submit == ("submit", f"{JOB}-t2-1", "origin/main", TASK2)
    git(root, "merge-base", "--is-ancestor", merged, f"factory/{JOB}-t2-1")
    record = read(root)
    assert (record["status"], record["stage"], record["task"]) == ("awaiting-merge", "ship", TASK2)
    assert task_entry(root)["merged"] is True
    assert task_entry(root, TASK2)["pr"] == BRANCH2
    second_roles = roles(log)[roles(log).index("integrator") + 1 :]
    assert second_roles[:2] == ["test-designer", "implementer"]
    assert second_roles[-1] == "integrator"
    assert not sidecar(root, JOB, "summary").exists()


@pytest.mark.ac("E13-AC-16")
def test_a_pr_closed_without_merging_stops_the_job_for_a_human(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _, _ = start(tmp_path, monkeypatch, capsys, turns(one_task_plan(), slice_turns()))
    assert to_slices(root, monkeypatch, capsys) == 0
    close_unmerged(root)
    assert drive(root, monkeypatch, capsys) == 1
    record = read(root)
    assert (record["status"], record["stage"]) == ("needs-human", "ship")
    assert "closed" in record["reason"]
    assert task_entry(root)["merged"] is False
    assert e18(root)["status"] == "blocked"


@pytest.mark.ac("E13-AC-16")
def test_the_github_forge_sees_the_merge_through_the_rest_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = slice_config(forge="github")
    root, _, _ = start(tmp_path, monkeypatch, capsys, turns(one_task_plan(), slice_turns()), config)
    github_origin(root)
    log = fake_gh(tmp_path, monkeypatch, {"POST": OPEN, "GET": OPEN})
    assert to_slices(root, monkeypatch, capsys) == 0
    assert drive(root, monkeypatch, capsys) == 0
    assert read(root)["status"] == "awaiting-merge"
    merge(root)
    gh_answers(tmp_path, {"POST": OPEN, "GET": {**OPEN, "state": "closed", "merged": True}})
    assert drive(root, monkeypatch, capsys) == 0
    reads = [c["argv"] for c in gh_calls(log)[1:]]
    assert reads and all(argv == ["api", "repos/acme/widgets/pulls/17"] for argv in reads)
    assert read(root)["status"] == "done"


@pytest.mark.ac("E13-AC-16")
@pytest.mark.parametrize(
    ("answer", "state"),
    [
        ({"state": "open", "merged": False}, "open"),
        ({"state": "closed", "merged": True}, "merged"),
        ({"state": "closed", "merged": False}, "closed"),
    ],
)
def test_the_github_forge_reads_a_pr_s_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answer: dict[str, object], state: str
) -> None:
    root = repo(tmp_path)
    git(root, "remote", "add", "origin", GITHUB_URL)
    log = fake_gh(tmp_path, monkeypatch, {"POST": OPEN, "GET": {"number": 17, **answer}})
    assert pipeline.GitHubForge(root).state("17", "factory/x-t1", "main", "0" * 40) == state
    assert [c["argv"] for c in gh_calls(log)] == [["api", "repos/acme/widgets/pulls/17"]]


@pytest.mark.ac("E13-AC-16")
def test_the_git_forge_sees_a_branch_merged_closed_or_open(tmp_path: Path) -> None:
    root = repo(tmp_path)
    bare = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    git(root, "remote", "add", "origin", str(bare))
    git(root, "push", "-q", "origin", "main")
    forge = pipeline.GitForge(root)
    heads = {}
    for name in ("one", "two", "three"):
        git(root, "switch", "-q", "-c", name, "main")
        heads[name] = commit(root, {f"{name}.txt": name}, name)
        assert forge.open(name, "main", name, "body") == name
        git(root, "push", "-q", "origin", f"{name}:refs/heads/{name}")
    git(root, "push", "-q", "origin", f"{heads['one']}:refs/heads/main")
    git(root, "push", "-q", "origin", "--delete", "two")
    assert forge.state("one", "one", "main", heads["one"]) == "merged"
    assert forge.state("two", "two", "main", heads["two"]) == "closed"
    assert forge.state("three", "three", "main", heads["three"]) == "open"
    assert origin_of(root) == bare


# --- AC-17: learn -------------------------------------------------------------------------------


def finished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> Path:
    """A one-task job driven to done, with a minor finding left open."""
    reviews = {"verifier": [[finding(TASK, "minor", "Name the widget sizes")]]}
    root, _, _ = start(
        tmp_path, monkeypatch, capsys, turns(one_task_plan(), slice_turns(), reviews)
    )
    assert to_slices(root, monkeypatch, capsys) == 0
    merge(root)
    assert drive(root, monkeypatch, capsys) == 0
    return root


@pytest.mark.ac("E13-AC-17")
def test_after_the_last_merge_learn_writes_the_summary_and_marks_the_job_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = finished(tmp_path, monkeypatch, capsys)
    record = read(root)
    assert (record["status"], record["stage"]) == ("done", "learn")
    job = e18(root)
    assert (job["status"], job["phase"]) == ("done", "learn")
    summary = summary_of(root)
    assert (summary["job"], summary["epic"]) == (JOB, "E31")
    stages = summary["stages"]
    assert isinstance(stages, list)
    names = [s["stage"] for s in stages]
    order = ["spec", "design", "test", "build", "gate", "review", "docs", "ship"]
    assert [n for n in order if n in names] == order
    assert all({"task", "started", "finished", "usd"} <= set(s) for s in stages)
    assert [g["verdict"] for g in summary["gates"]] == ["pass", "pass"]
    [found] = summary["findings"]
    assert (found["task"], found["severity"], found["summary"]) == (
        TASK,
        "minor",
        "Name the widget sizes",
    )
    [pr] = summary["prs"]
    assert (pr["task"], pr["pr"], pr["merged"]) == (TASK, BRANCH1, True)
    total = sum(decimal.Decimal(str(s.get("usd", "0"))) for s in record["sessions"])
    assert decimal.Decimal(str(summary["total_usd"])) == total > 0


@pytest.mark.ac("E13-AC-17")
def test_the_closing_handoff_says_what_shipped_and_what_is_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = finished(tmp_path, monkeypatch, capsys)
    handoff = str(summary_of(root)["handoff"])
    lines = handoff.splitlines()
    for heading in ("## Done", "## Next", "## Open questions"):
        assert heading in lines
    done = handoff.split("## Done")[1].split("## Next")[0]
    left = handoff.split("## Next")[1].split("## Open questions")[0]
    assert TASK in done and BRANCH1 in done
    assert "Name the widget sizes" in left
    assert call(root, monkeypatch, capsys, "check", JOB, "learn")[0] == 0


@pytest.mark.ac("E13-AC-17")
def test_status_shows_the_summary_and_its_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = finished(tmp_path, monkeypatch, capsys)
    code, out, _ = call(root, monkeypatch, capsys, "status", JOB, "--json")
    assert code == 0
    data = json.loads(out)
    assert data["summary"]["job"] == JOB
    assert "## Done" in data["summary"]["handoff"]
    code, out, _ = call(root, monkeypatch, capsys, "status", JOB)
    assert code == 0 and "## Done" in out and "## Open questions" in out


@pytest.mark.ac("E13-AC-17")
def test_the_summary_lists_every_pr_once_every_task_has_merged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    second = slice_turns(TASK2, {TEST2_REL: TESTS2})
    root, _, _ = start(tmp_path, monkeypatch, capsys, turns(two_task_plan(), slice_turns(), second))
    assert to_slices(root, monkeypatch, capsys) == 0
    merge(root)
    assert drive(root, monkeypatch, capsys) == 0
    merge(root, TASK2)
    assert drive(root, monkeypatch, capsys) == 0
    assert read(root)["status"] == "done"
    prs = summary_of(root)["prs"]
    assert [(p["task"], p["pr"]) for p in prs] == [(TASK, BRANCH1), (TASK2, BRANCH2)]
    assert drive(root, monkeypatch, capsys) == 1  # a done job is refused
