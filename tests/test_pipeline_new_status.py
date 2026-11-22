"""E13/T2: `pipeline.py new` and `pipeline.py status`.

Covers E13 AC-02 and AC-03. Expectations come from the E13 spec (AC-02, AC-03, the record in
"Where things live", Changes of 21 Nov 2026) and the E18 design ("Sidecars", "API for E13"): the
job is E18's record, and the pipeline record is its sidecar `work/<id>.pipeline.toml`.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from tests._pipeline import EPIC, JOB, SPEC_REL, git, sidecar, spec_text
from tests._pipeline_driver import (
    PLAN,
    FakeRunner,
    call,
    config_text,
    driver_repo,
    e18,
    jobs_module,
    new_job,
    read,
    request_file,
    script,
    use_runner,
)

AC2 = "E13-AC-02"
AC3 = "E13-AC-03"


# --- new ----------------------------------------------------------------------------------------


@pytest.mark.ac(AC2)
def test_new_creates_the_e18_job_and_its_pipeline_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = driver_repo(tmp_path, monkeypatch)
    new_job(root, monkeypatch, capsys, tmp_path)
    job = e18(root)
    assert (job["id"], job["track"], job["task"], job["phase"], job["status"]) == (
        JOB,
        "full",
        JOB,
        "spec",
        "open",
    )
    assert job["title"] == "Make widgets."
    record = read(root)
    assert (record["id"], record["epic"], record["issue"]) == (JOB, EPIC, 0)
    assert (record["status"], record["stage"], record["task"]) == ("ready", "spec", JOB)
    assert record["base"] == "main"
    assert record["request"] == "Make widgets.\n\nThey should be small.\n"
    assert sidecar(root, JOB, "pipeline").is_file()


@pytest.mark.ac(AC2)
def test_new_takes_a_title_and_leaves_the_job_unclaimed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = driver_repo(tmp_path, monkeypatch)
    args = ["new", JOB, "--epic", EPIC, "--request-file", str(request_file(tmp_path))]
    assert call(root, monkeypatch, capsys, *args, "--title", "Widgets")[0] == 0
    assert e18(root)["title"] == "Widgets"
    jobs = jobs_module()
    repo = jobs.find_repo(root)
    assert jobs.lease_state(repo, JOB) == "unclaimed"


@pytest.mark.ac(AC2)
@pytest.mark.parametrize(
    "args",
    [
        ["new", "Bad_Id", "--epic", EPIC, "--request-file", "{req}"],
        ["new", "a" * 31, "--epic", EPIC, "--request-file", "{req}"],  # longer than 30
        ["new", JOB, "--epic", "31", "--request-file", "{req}"],
        ["new", JOB, "--epic", EPIC],  # no request
        ["new", JOB, "--epic", EPIC, "--request-file", "{req}", "--issue", "82"],  # both
        ["new", JOB, "--epic", EPIC, "--request-file", "{missing}"],
        ["new", JOB, "--epic", EPIC, "--issue", "82"],  # forge = "git": no issues to read
        ["new", JOB, "--request-file", "{req}"],  # no epic
    ],
)
def test_new_refuses_bad_input_with_exit_2_and_creates_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    args: list[str],
) -> None:
    root = driver_repo(tmp_path, monkeypatch)
    req = request_file(tmp_path)
    filled = [a.format(req=req, missing=tmp_path / "nope.md") for a in args]
    assert call(root, monkeypatch, capsys, *filled)[0] == 2
    assert not sidecar(root, JOB, "pipeline").exists()


@pytest.mark.ac(AC2)
def test_new_refuses_an_epic_that_already_has_a_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = driver_repo(tmp_path, monkeypatch)
    (root / SPEC_REL).parent.mkdir(parents=True)
    (root / SPEC_REL).write_text(spec_text(), encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "an E31 spec")
    args = ("new", JOB, "--epic", EPIC, "--request-file", str(request_file(tmp_path)))
    code, _, err = call(root, monkeypatch, capsys, *args)
    assert code == 2
    assert "E31" in err


@pytest.mark.ac(AC2)
def test_new_refuses_an_id_already_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = driver_repo(tmp_path, monkeypatch)
    new_job(root, monkeypatch, capsys, tmp_path)
    before = sidecar(root, JOB, "pipeline").read_bytes()
    args = ("new", JOB, "--epic", "E32", "--request-file", str(request_file(tmp_path)))
    assert call(root, monkeypatch, capsys, *args)[0] == 2
    assert sidecar(root, JOB, "pipeline").read_bytes() == before


@pytest.mark.ac(AC2)
def test_new_takes_over_an_open_full_track_e18_job_without_a_pipeline_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = driver_repo(tmp_path, monkeypatch)
    jobs = jobs_module()
    jobs.new_job(jobs.find_repo(root), "Widgets, filed by hand", job_id=JOB)
    new_job(root, monkeypatch, capsys, tmp_path)
    assert read(root)["status"] == "ready"
    assert e18(root)["title"] == "Widgets, filed by hand"


@pytest.mark.ac(AC2)
def test_new_refuses_an_e18_job_on_another_track(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = driver_repo(tmp_path, monkeypatch)
    jobs = jobs_module()
    jobs.new_job(jobs.find_repo(root), "A bump", job_id=JOB, track="lite")
    args = ("new", JOB, "--epic", EPIC, "--request-file", str(request_file(tmp_path)))
    assert call(root, monkeypatch, capsys, *args)[0] == 2
    assert not sidecar(root, JOB, "pipeline").exists()


def fake_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answer: dict[str, object]) -> Path:
    """A `gh` on PATH that records its arguments and prints `answer` as JSON."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "gh-args.json"
    (bin_dir / "gh.py").write_text(
        "import json, sys\n"
        f"open({str(log)!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
        f"print(json.dumps({answer!r}))\n",
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


@pytest.mark.ac(AC2)
def test_new_reads_an_issue_through_the_rest_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = config_text().replace('forge = "git"', 'forge = "github"')
    root = driver_repo(tmp_path, monkeypatch, config)
    git(root, "remote", "add", "origin", "https://github.com/acme/widgets.git")
    log = fake_gh(tmp_path, monkeypatch, {"title": "Widgets please", "body": "Small ones."})
    assert call(root, monkeypatch, capsys, "new", JOB, "--epic", EPIC, "--issue", "82")[0] == 0
    argv = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert argv[:2] == ["api", "repos/acme/widgets/issues/82"]
    assert "graphql" not in " ".join(argv)
    record = read(root)
    assert record["issue"] == 82
    assert "Widgets please" in record["request"] and "Small ones." in record["request"]
    assert e18(root)["title"] == "Widgets please"


# --- status -------------------------------------------------------------------------------------


def run_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> Path:
    root = driver_repo(tmp_path, monkeypatch)
    script(tmp_path, monkeypatch, PLAN)
    use_runner(monkeypatch, FakeRunner(root))
    new_job(root, monkeypatch, capsys, tmp_path)
    assert call(root, monkeypatch, capsys, "run", JOB)[0] == 0
    return root


@pytest.mark.ac(AC3)
def test_status_json_shows_the_job_and_its_pipeline_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = run_spec(tmp_path, monkeypatch, capsys)
    code, out, _ = call(root, monkeypatch, capsys, "status", JOB, "--json")
    assert code == 0
    data = json.loads(out)
    assert data["job"]["id"] == JOB and data["job"]["status"] == "blocked"
    pipe = data["pipeline"]
    assert (pipe["id"], pipe["epic"], pipe["issue"]) == (JOB, EPIC, 0)
    assert (pipe["status"], pipe["reason"], pipe["stage"], pipe["task"]) == (
        "awaiting-approval",
        "",
        "spec",
        JOB,
    )
    assert pipe["runs"][0]["id"] == f"{JOB}-p1"
    assert pipe["runs"][0]["branch"] == f"factory/{JOB}-p1"


@pytest.mark.ac(AC3)
def test_status_shows_each_stage_with_its_times_commands_and_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = run_spec(tmp_path, monkeypatch, capsys)
    data = json.loads(call(root, monkeypatch, capsys, "status", JOB, "--json")[1])
    [spec] = data["stages"]
    assert (spec["stage"], spec["task"]) == ("spec", JOB)
    assert spec["started"] and spec["finished"]
    assert spec["usd"] == "0.01"
    assert spec["commands"] == [f"{JOB}-p1#1"]


@pytest.mark.ac(AC3)
def test_status_lists_decisions_with_who_when_and_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = run_spec(tmp_path, monkeypatch, capsys)
    reject = ("reject", JOB, "spec", "--by", "po", "--note", "Q1: A")
    assert call(root, monkeypatch, capsys, *reject)[0] == 0
    data = json.loads(call(root, monkeypatch, capsys, "status", JOB, "--json")[1])
    [decision] = data["pipeline"]["decisions"]
    assert (decision["checkpoint"], decision["verdict"], decision["by"], decision["note"]) == (
        "spec",
        "reject",
        "po",
        "Q1: A",
    )
    assert decision["at"].endswith("Z")


@pytest.mark.ac(AC3)
def test_status_as_text_names_the_status_stage_and_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = run_spec(tmp_path, monkeypatch, capsys)
    code, out, _ = call(root, monkeypatch, capsys, "status", JOB)
    assert code == 0
    assert "awaiting-approval" in out and "spec" in out and JOB in out


@pytest.mark.ac(AC3)
def test_status_of_an_unknown_job_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = driver_repo(tmp_path, monkeypatch)
    assert call(root, monkeypatch, capsys, "status", "no-such-job")[0] == 2
