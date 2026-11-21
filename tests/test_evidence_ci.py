"""E08/T4: `install.py ci github` renders the `pr-evidence` workflow and gives the gate jobs a JSON
artefact and a job summary; the other providers don't change (ADR 0026).

Covers E08 AC-12 to AC-15, and the parts of AC-19 a test can check. Expectations come from the E08
spec, the design note and ADR 0026, not from the implementation.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from factory_installer import cli, manifest, pipelines
from factory_installer.kit import KIT_ROOT
from factory_installer.pipelines import PipelineSpec, render
from tests._ac import REPO_ROOT
from tests._gate import git

EVIDENCE = ".github/workflows/factory-pr-evidence.yml"
GATE_WORKFLOW = ".github/workflows/factory-gate.yml"
GOLDEN = REPO_ROOT / "tests" / "fixtures" / "pipelines"
JSON_OUT = '--json-out "${{ runner.temp }}/gate-report.json"'
SUMMARY_RUN = (
    'python .factory/workflow/evidence.py --summary "$RUNNER_TEMP/gate-report.json"'
    ' >> "$GITHUB_STEP_SUMMARY"'
)
TYPES = ["opened", "edited", "synchronize", "reopened"]
OSES = ("ubuntu", "windows", "macos")
NEEDS_BASH = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None, reason="runs the step under bash"
)


def _spec(
    profiles: tuple[str, ...] = ("python",),
    *,
    uv_lock: bool = True,
    python_command: tuple[str, ...] = ("uv", "run", "python"),
    base: str = "main",
    os_list: tuple[str, ...] = ("ubuntu",),
) -> PipelineSpec:
    return PipelineSpec(
        profiles=profiles,
        has_uv_lock=uv_lock,
        python_command=python_command,
        base_branch=base,
        os=os_list,
    )


def _yaml(text: str) -> dict[Any, Any]:
    data = yaml.safe_load(text)
    assert isinstance(data, dict)
    return data


def _triggers(data: dict[Any, Any]) -> Any:
    return data.get("on", data.get(True))  # PyYAML reads a bare `on` key as True


def _evidence(spec: PipelineSpec | None = None) -> dict[Any, Any]:
    return _yaml(pipelines.render_github_evidence(spec or _spec()))


def _evidence_steps(spec: PipelineSpec | None = None) -> list[dict[str, Any]]:
    steps = _evidence(spec)["jobs"]["pr-evidence"]["steps"]
    assert isinstance(steps, list)
    return steps


def _gate_steps(spec: PipelineSpec) -> list[dict[str, Any]]:
    steps = _yaml(render("github", spec))["jobs"]["gate"]["steps"]
    assert isinstance(steps, list)
    return steps


def _named(steps: list[dict[str, Any]], name: str) -> dict[str, Any]:
    matches = [step for step in steps if step.get("name") == name]
    assert len(matches) == 1, [step.get("name") for step in steps]
    return matches[0]


# --- AC-12: the pr-evidence workflow ------------------------------------------------------------


@pytest.mark.ac("E08-AC-12")
def test_the_evidence_workflow_has_its_own_file() -> None:
    assert pipelines.EVIDENCE_PATH == EVIDENCE
    github = pipelines.PROVIDERS["github"]
    assert github.path == GATE_WORKFLOW
    assert [path for path, _ in github.extra] == [EVIDENCE]
    assert all(not p.extra for name, p in pipelines.PROVIDERS.items() if name != "github")
    assert EVIDENCE in pipelines.PIPELINE_PATHS


@pytest.mark.ac("E08-AC-12")
def test_it_runs_on_pull_requests_of_four_types_and_never_on_a_push() -> None:
    data = _evidence()
    assert data["name"] == "factory-pr-evidence"
    assert _triggers(data) == {"pull_request": {"types": TYPES}}


@pytest.mark.ac("E08-AC-12")
def test_one_job_on_ubuntu_reading_the_repo_only() -> None:
    data = _evidence()
    assert data["permissions"] == {"contents": "read"}
    assert list(data["jobs"]) == ["pr-evidence"]
    assert data["jobs"]["pr-evidence"]["runs-on"] == "ubuntu-latest"


@pytest.mark.ac("E08-AC-12")
def test_the_steps_check_out_history_read_the_body_and_check_it() -> None:
    steps = _evidence_steps()
    assert [step.get("uses") or step.get("name") for step in steps] == [
        "actions/checkout@v4",
        "actions/setup-python@v5",
        "Read the PR body",
        "Check the PR evidence",
    ]
    assert steps[0]["with"]["fetch-depth"] == 0
    assert str(steps[1]["with"]["python-version"]) == "3.12"


@pytest.mark.ac("E08-AC-12")
def test_the_body_comes_from_the_event_file_and_never_through_an_expression() -> None:
    text = pipelines.render_github_evidence(_spec())
    assert "GITHUB_EVENT_PATH" in _named(_evidence_steps(), "Read the PR body")["run"]
    for expression in re.findall(r"\$\{\{(.*?)\}\}", text):
        assert "body" not in expression and "title" not in expression, expression
    for step in _evidence_steps():
        assert "${{" not in str(step.get("run", "")), step


@pytest.mark.ac("E08-AC-12")
def test_the_check_lists_the_prs_commits_with_git_from_the_events_shas() -> None:
    check = _named(_evidence_steps(), "Check the PR evidence")
    assert check["env"] == {
        "BASE": "${{ github.event.pull_request.base.sha }}",
        "HEAD": "${{ github.event.pull_request.head.sha }}",
    }
    run = check["run"].strip()
    assert run.startswith(
        'python .factory/workflow/docs.py --root . check-pr --strict "$RUNNER_TEMP/pr-body.md"'
        " --commits "
    )
    assert '$(git rev-list "$BASE..$HEAD")' in run


@pytest.mark.ac("E08-AC-12")
@pytest.mark.parametrize(
    "spec",
    [
        _spec(),
        _spec(("ts-js",), uv_lock=False, python_command=("python",)),
        _spec(("python", "ts-js"), os_list=OSES, base="develop"),
    ],
)
def test_it_installs_nothing_whatever_the_stack(spec: PipelineSpec) -> None:
    assert pipelines.render_github_evidence(spec) == pipelines.render_github_evidence(_spec())
    for step in _evidence_steps(spec):
        assert "uv" not in str(step.get("uses", "")) and "node" not in str(step.get("uses", ""))
        assert not re.search(r"\b(pip|uv|npm)\b", str(step.get("run", ""))), step


@pytest.mark.ac("E08-AC-12")
@pytest.mark.ac("E08-AC-11")
@NEEDS_BASH
@pytest.mark.parametrize(
    ("body", "code", "shown"),
    [
        ("good", 0, ""),
        ("other commit", 1, "which is not a commit of this PR"),
        (None, 1, "## Gate evidence: missing heading"),
        ("$(touch pwned) `touch pwned`", 1, "## What changes: missing heading"),
    ],
)
def test_the_steps_run_under_bash_on_an_event_file(
    tmp_path: Path, body: str | None, code: int, shown: str
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    base = git(repo, "rev-parse", "HEAD").strip()
    (repo / "README.md").write_text("y\n", encoding="utf-8")
    git(repo, "commit", "-q", "-am", "change")
    head = git(repo, "rev-parse", "HEAD").strip()
    for rel in (".factory/workflow/docs.py", ".factory/state/state.py"):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(KIT_ROOT / rel, repo / rel)
    commit = head if body == "good" else "fedcba9876543210fedcba9876543210fedcba98"
    text = (
        f"Widgets. Refs #1.\n\n## What changes\n\n- A count.\n\n## Acceptance criteria\n\n"
        f"- **AC-01** `tests/test_widgets.py`\n\n## Tests\n\nOne.\n\n## Gate evidence\n\n"
        f"**PASS** on `{commit[:12]}`\n\n## Findings\n\nNone.\n"
        if body in ("good", "other commit")
        else body
    )
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps({"pull_request": {"body": text, "base": {"sha": base}, "head": {"sha": head}}}),
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "python").symlink_to(sys.executable)
    temp = tmp_path / "runner-temp"
    temp.mkdir()
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_EVENT_PATH": str(event),
        "RUNNER_TEMP": str(temp),
        "BASE": base,
        "HEAD": head,
    }
    steps = _evidence_steps()
    script = "\n".join(
        _named(steps, name)["run"] for name in ("Read the PR body", "Check the PR evidence")
    )
    done = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == code, done.stdout + done.stderr
    assert shown in done.stdout
    assert "Traceback" not in done.stderr
    assert not (repo / "pwned").exists()
    assert not (tmp_path / "pwned").exists()


# --- AC-13: editing a body runs only pr-evidence ------------------------------------------------


@pytest.mark.ac("E08-AC-13")
@pytest.mark.parametrize("os_list", [("ubuntu",), OSES])
def test_the_gate_workflow_does_not_run_on_edited(os_list: tuple[str, ...]) -> None:
    triggers = _triggers(_yaml(render("github", _spec(os_list=os_list))))
    pull = triggers["pull_request"]
    assert pull is None or "edited" not in pull.get("types", ["opened", "synchronize", "reopened"])
    assert list(triggers) == ["pull_request", "push"]


@pytest.mark.ac("E08-AC-13")
def test_only_the_evidence_workflow_runs_on_edited() -> None:
    assert list(_yaml(pipelines.render_github_evidence(_spec()))["jobs"]) == ["pr-evidence"]
    assert "pr-evidence" not in _yaml(render("github", _spec()))["jobs"]


# --- AC-14: the gate job's artefact and summary -------------------------------------------------


@pytest.mark.ac("E08-AC-14")
@pytest.mark.parametrize("os_list", [("ubuntu",), OSES])
def test_each_gate_step_saves_its_json_report_in_any_shell(os_list: tuple[str, ...]) -> None:
    runs = [
        str(step["run"])
        for step in _gate_steps(_spec(os_list=os_list))
        if ".factory/gates/gate.py" in str(step.get("run"))
    ]
    assert len(runs) == 2
    for run in runs:
        assert JSON_OUT in run
        assert "$RUNNER_TEMP" not in run and "$env:" not in run  # an expression, not a variable


@pytest.mark.ac("E08-AC-14")
@pytest.mark.parametrize("os_list", [("ubuntu",), OSES])
def test_the_gate_job_writes_a_summary_and_uploads_the_report_whatever_the_verdict(
    os_list: tuple[str, ...],
) -> None:
    steps = _gate_steps(_spec(os_list=os_list))
    summary, upload = steps[-2], steps[-1]
    assert summary == {
        "name": "Gate summary",
        "if": "always()",
        "shell": "bash",
        "run": SUMMARY_RUN,
    }
    assert upload == {
        "name": "Gate report",
        "if": "always()",
        "uses": "actions/upload-artifact@v4",
        "with": {
            "name": "gate-report-${{ matrix.os }}",
            "path": "${{ runner.temp }}/gate-report.json",
            "if-no-files-found": "warn",
        },
    }


@pytest.mark.ac("E08-AC-14")
@NEEDS_BASH
@pytest.mark.parametrize("report", [True, False])
def test_the_summary_step_runs_under_bash(tmp_path: Path, report: bool) -> None:
    repo = tmp_path / "repo"
    for rel in (
        ".factory/workflow/evidence.py",
        ".factory/workflow/docs.py",
        ".factory/state/state.py",
        ".factory/gates/gate.py",
    ):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(KIT_ROOT / rel, repo / rel)
    temp = tmp_path / "runner-temp"
    temp.mkdir()
    if report:
        data = {
            "verdict": "fail",
            "root": "/w",
            "base_ref": "main",
            "commit": "0123456789abcdef0123456789abcdef01234567",
            "dirty": False,
            "profiles": ["python"],
            "changed_files": [],
            "locks": {"locked": 0, "broken": []},
            "docs": {"checked": 0, "problems": []},
            "checks": [
                {
                    "profile": "python",
                    "check": "tests",
                    "status": "fail",
                    "reason": "",
                    "exit_code": 1,
                    "duration_s": 2.0,
                    "command": ["pytest"],
                    "output_tail": "",
                }
            ],
        }
        (temp / "gate-report.json").write_text(json.dumps(data), encoding="utf-8")
    page = tmp_path / "summary.md"
    page.write_text("before\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "python").symlink_to(sys.executable)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "RUNNER_TEMP": str(temp),
        "GITHUB_STEP_SUMMARY": str(page),
    }
    done = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", SUMMARY_RUN],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    written = page.read_text(encoding="utf-8")
    assert written.startswith("before\n")
    if report:
        assert "**FAIL** on `0123456789ab`" in written
        assert "| python | tests | fail | 2.00 s |" in written
    else:
        assert written == "before\nNo gate report.\n"


# --- AC-15: the other providers -----------------------------------------------------------------

VARIANTS = {
    "python-uv": _spec(("python",), uv_lock=True, python_command=("python",)),
    "python-pip": _spec(("python",), uv_lock=False, python_command=("python",)),
    "ts": _spec(("ts-js",), uv_lock=False, python_command=("python",)),
    "both-uv-develop": _spec(("python", "ts-js"), base="develop"),
}
EXTENSIONS = {"gitlab": "yml", "azure": "yml", "jenkins": "Jenkinsfile"}


@pytest.mark.ac("E08-AC-15")
@pytest.mark.parametrize("provider", list(EXTENSIONS))
@pytest.mark.parametrize("variant", list(VARIANTS))
def test_other_providers_render_byte_for_byte_as_before(provider: str, variant: str) -> None:
    golden = (GOLDEN / f"{provider}-{variant}.{EXTENSIONS[provider]}").read_bytes()
    assert render(provider, VARIANTS[variant]).encode("utf-8") == golden.replace(b"\r\n", b"\n")


# --- install.py ci github writes both files -----------------------------------------------------


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    return repo


@pytest.mark.ac("E08-AC-12")
def test_ci_github_writes_both_workflows_and_tracks_them(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    assert cli.main(["ci", "github", str(repo)]) == 0
    capsys.readouterr()
    spec = pipelines.spec_for(KIT_ROOT, repo, {"os": ["ubuntu"]})
    assert (repo / EVIDENCE).read_text(encoding="utf-8") == pipelines.render_github_evidence(spec)
    assert (repo / GATE_WORKFLOW).read_text(encoding="utf-8") == render("github", spec)
    loaded = manifest.load(repo)
    assert loaded is not None
    assert {EVIDENCE, GATE_WORKFLOW} <= set(loaded.files)
    assert loaded.pipelines == {"github": {"os": ["ubuntu"]}}
    assert cli.main(["ci", "github", str(repo)]) == 0  # a re-render changes nothing
    assert "0 created" in capsys.readouterr().out


@pytest.mark.ac("E08-AC-12")
@pytest.mark.parametrize("provider", list(EXTENSIONS))
def test_other_providers_write_no_evidence_workflow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], provider: str
) -> None:
    repo = _repo(tmp_path)
    assert cli.main(["ci", provider, str(repo)]) == 0
    assert not (repo / EVIDENCE).exists()
    assert not (repo / GATE_WORKFLOW).exists()


# --- AC-19: this repo's workflows ---------------------------------------------------------------


@pytest.mark.ac("E08-AC-19")
def test_this_repos_workflows_are_the_rendered_ones() -> None:
    spec = pipelines.spec_for(KIT_ROOT, REPO_ROOT, {"os": list(OSES)})
    for path, text in (
        (GATE_WORKFLOW, render("github", spec)),
        (EVIDENCE, pipelines.render_github_evidence(spec)),
    ):
        assert (REPO_ROOT / path).read_text(encoding="utf-8").replace("\r\n", "\n") == text
    data = json.loads((REPO_ROOT / ".factory" / "manifest.json").read_text(encoding="utf-8"))
    assert {GATE_WORKFLOW, EVIDENCE} <= set(data["files"])
