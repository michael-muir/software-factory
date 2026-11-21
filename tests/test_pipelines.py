"""E07/T3: pipeline files. `install.py ci <provider>`, renderers, manifest tracking.

Covers E07 AC-09 to AC-14. Expectations come from the E07 spec, the design note's "Pipelines"
section and ADR 0013, not from the implementation.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from factory_installer import cli, manifest, pipelines
from factory_installer.pipelines import PipelineSpec, render

PATHS = {
    "github": ".github/workflows/factory-gate.yml",
    "gitlab": ".gitlab/factory-gate.yml",
    "azure": ".azure-pipelines/factory-gate.yml",
    "jenkins": "jenkins/factory-gate.Jenkinsfile",
}
YAML_PROVIDERS = ("github", "gitlab", "azure")
GATE = ".factory/gates/gate.py"

# The three repos AC-14 names: Python only, TS/JS only, both.
STACKS: dict[str, tuple[str, ...]] = {
    "python": ("python",),
    "ts": ("ts-js",),
    "both": ("python", "ts-js"),
}


def _spec(
    stack: str,
    *,
    uv_lock: bool = True,
    python_command: tuple[str, ...] = ("python",),
    base: str = "main",
    os_list: tuple[str, ...] = ("ubuntu",),
) -> PipelineSpec:
    return PipelineSpec(
        profiles=STACKS[stack],
        has_uv_lock=uv_lock,
        python_command=python_command,
        base_branch=base,
        os=os_list,
    )


def _yaml(text: str) -> dict[Any, Any]:
    data = yaml.safe_load(text)
    assert isinstance(data, dict)
    return data


# --- AC-14: GitHub ------------------------------------------------------------------------------


def _github_steps(data: dict[Any, Any]) -> list[dict[str, Any]]:
    steps = data["jobs"]["gate"]["steps"]
    assert isinstance(steps, list)
    return steps


def _signature(step: dict[str, Any]) -> str:
    return str(step.get("uses") or step.get("run"))


GITHUB_SETUP = {
    ("python", True): ["astral-sh/setup-uv@v6", "uv sync --locked"],
    ("python", False): ["python -m pip install -e ."],
    ("ts", True): ["actions/setup-node@v4", "npm ci"],
    ("both", True): [
        "astral-sh/setup-uv@v6",
        "uv sync --locked",
        "actions/setup-node@v4",
        "npm ci",
    ],
}


@pytest.mark.ac("E07-AC-14")
@pytest.mark.ac("E07-AC-10")
@pytest.mark.parametrize(("stack", "uv_lock"), list(GITHUB_SETUP))
def test_github_workflow_has_exactly_the_expected_steps(stack: str, uv_lock: bool) -> None:
    data = _yaml(render("github", _spec(stack, uv_lock=uv_lock)))
    steps = _github_steps(data)
    signatures = [_signature(s) for s in steps]
    # Change, 20 Nov 2026 (E08 AC-14): each gate step saves its JSON report, and two steps
    # after them write the job summary and upload the report (tests/test_evidence_ci.py).
    json_out = '--json-out "${{ runner.temp }}/gate-report.json"'
    gate_pr = f"python {GATE} --base-ref origin/${{{{ github.base_ref }}}} {json_out}"
    gate_push = f"python {GATE} {json_out}"
    assert signatures == [
        "actions/checkout@v4",
        "actions/setup-python@v5",
        *GITHUB_SETUP[(stack, uv_lock)],
        gate_pr,
        gate_push,
        'python .factory/workflow/evidence.py --summary "$RUNNER_TEMP/gate-report.json"'
        ' >> "$GITHUB_STEP_SUMMARY"',
        "actions/upload-artifact@v4",
    ]
    assert steps[0]["with"]["fetch-depth"] == 0
    assert str(steps[1]["with"]["python-version"]) == "3.12"
    node = [s for s in steps if s.get("uses") == "actions/setup-node@v4"]
    for step in node:
        assert step["with"]["node-version"] == "lts/*"
    assert steps[-4]["if"] == "github.event_name == 'pull_request'"
    assert steps[-3]["if"] == "github.event_name != 'pull_request'"


@pytest.mark.ac("E07-AC-10")
def test_github_workflow_triggers_on_pull_requests_and_pushes_to_the_base() -> None:
    data = _yaml(render("github", _spec("python", base="develop")))
    triggers = data.get("on", data.get(True))  # PyYAML reads a bare `on` key as True
    assert isinstance(triggers, dict)
    assert "pull_request" in triggers
    assert triggers["push"]["branches"] == ["develop"]


@pytest.mark.ac("E07-AC-10")
def test_github_workflow_runs_the_gate_with_python_command() -> None:
    text = render("github", _spec("python", python_command=("uv", "run", "python")))
    signatures = [_signature(s) for s in _github_steps(_yaml(text))]
    # Change, 20 Nov 2026 (E08 AC-14): the gate steps come before the summary and upload steps.
    assert (
        signatures[-3]
        == f'uv run python {GATE} --json-out "${{{{ runner.temp }}}}/gate-report.json"'
    )
    assert signatures[-4].startswith(f"uv run python {GATE} --base-ref origin/")


@pytest.mark.ac("E07-AC-12")
@pytest.mark.parametrize(
    ("os_list", "runners"),
    [
        (("ubuntu",), ["ubuntu-latest"]),
        (("ubuntu", "windows", "macos"), ["ubuntu-latest", "windows-latest", "macos-latest"]),
        (("macos",), ["macos-latest"]),
    ],
)
def test_github_job_runs_on_each_listed_os(os_list: tuple[str, ...], runners: list[str]) -> None:
    job = _yaml(render("github", _spec("python", os_list=os_list)))["jobs"]["gate"]
    assert job["runs-on"] == "${{ matrix.os }}"
    assert job["strategy"]["matrix"]["os"] == runners
    assert job["strategy"]["fail-fast"] is False


# --- AC-14: GitLab ------------------------------------------------------------------------------

MR_TARGET = "$CI_MERGE_REQUEST_TARGET_BRANCH_NAME"

GITLAB_SETUP: dict[tuple[str, bool], tuple[str, list[str]]] = {
    ("python", True): ("python:3.12", ["pip install uv", "uv sync --locked"]),
    ("python", False): ("python:3.12", ["pip install -e ."]),
    ("ts", True): (
        "node:lts",
        ["apt-get update && apt-get install -y python3 python-is-python3", "npm ci"],
    ),
    ("both", True): (
        "node:lts",
        [
            "apt-get update && apt-get install -y python3 python3-pip python3-venv "
            "python-is-python3",
            "pip install --break-system-packages uv",
            "uv sync --locked",
            "npm ci",
        ],
    ),
}


@pytest.mark.ac("E07-AC-14")
@pytest.mark.ac("E07-AC-10")
@pytest.mark.parametrize(("stack", "uv_lock"), list(GITLAB_SETUP))
def test_gitlab_job_has_exactly_the_expected_steps(stack: str, uv_lock: bool) -> None:
    data = _yaml(render("gitlab", _spec(stack, uv_lock=uv_lock)))
    assert list(data) == ["factory-gate"]
    job = data["factory-gate"]
    image, setup = GITLAB_SETUP[(stack, uv_lock)]
    assert job["image"] == image
    assert str(job["variables"]["GIT_DEPTH"]) == "0"
    assert job["before_script"] == setup
    assert job["script"] == [
        f'if [ -n "{MR_TARGET}" ]; then '
        f'git fetch origin "{MR_TARGET}" && python {GATE} --base-ref "origin/{MR_TARGET}"; '
        f"else python {GATE}; fi"
    ]


@pytest.mark.ac("E07-AC-10")
def test_gitlab_job_runs_on_merge_requests_and_pushes_to_the_base() -> None:
    rules = _yaml(render("gitlab", _spec("python", base="develop")))["factory-gate"]["rules"]
    conditions = [rule["if"] for rule in rules]
    assert conditions == [
        '$CI_PIPELINE_SOURCE == "merge_request_event"',
        '$CI_COMMIT_BRANCH == "develop"',
    ]


# --- AC-14: Azure -------------------------------------------------------------------------------

AZURE_PR = "eq(variables['Build.Reason'], 'PullRequest')"
AZURE_PUSH = "ne(variables['Build.Reason'], 'PullRequest')"
AZURE_TARGET = "$(System.PullRequest.TargetBranchName)"

AZURE_SETUP = {
    ("python", True): ["pip install uv", "uv sync --locked"],
    ("python", False): ["python -m pip install -e ."],
    ("ts", True): ["NodeTool@0", "npm ci"],
    ("both", True): ["pip install uv", "uv sync --locked", "NodeTool@0", "npm ci"],
}


def _azure_signature(step: dict[str, Any]) -> str:
    if "checkout" in step:
        return f"checkout:{step['checkout']}"
    return str(step.get("task") or step.get("script"))


@pytest.mark.ac("E07-AC-14")
@pytest.mark.ac("E07-AC-10")
@pytest.mark.parametrize(("stack", "uv_lock"), list(AZURE_SETUP))
def test_azure_pipeline_has_exactly_the_expected_steps(stack: str, uv_lock: bool) -> None:
    data = _yaml(render("azure", _spec(stack, uv_lock=uv_lock)))
    steps = data["steps"]
    assert [_azure_signature(s) for s in steps] == [
        "checkout:self",
        "UsePythonVersion@0",
        *AZURE_SETUP[(stack, uv_lock)],
        f"git fetch origin {AZURE_TARGET} && python {GATE} --base-ref origin/{AZURE_TARGET}",
        f"python {GATE}",
    ]
    assert steps[0]["fetchDepth"] == 0
    assert str(steps[1]["inputs"]["versionSpec"]) == "3.12"
    assert steps[-2]["condition"] == AZURE_PR
    assert steps[-1]["condition"] == AZURE_PUSH
    assert data["pool"]["vmImage"] == "ubuntu-latest"


@pytest.mark.ac("E07-AC-10")
def test_azure_pipeline_triggers_on_pull_requests_and_pushes_to_the_base() -> None:
    data = _yaml(render("azure", _spec("python", base="develop")))
    assert data["trigger"]["branches"]["include"] == ["develop"]
    assert data["pr"]["branches"]["include"] == ["*"]


# --- AC-14: Jenkins -----------------------------------------------------------------------------


def _balanced(text: str) -> bool:
    depth = 0
    for char in re.sub(r"'[^'\n]*'|\"[^\"\n]*\"", "", text):
        depth += {"{": 1, "}": -1}.get(char, 0)
        if depth < 0:
            return False
    return depth == 0


def _sh_steps(text: str) -> list[str]:
    return re.findall(r"^\s*sh ['\"](.*)['\"]\s*$", text, flags=re.MULTILINE)


JENKINS_SETUP = {
    ("python", True): ["uv sync --locked"],
    ("python", False): ["python3 -m pip install -e ."],
    ("ts", True): ["npm ci"],
    ("both", True): ["uv sync --locked", "npm ci"],
}
JENKINS_TOOLS = {
    ("python", True): ["python3", "uv"],
    ("python", False): ["python3"],
    ("ts", True): ["python3", "npm"],
    ("both", True): ["python3", "uv", "npm"],
}


@pytest.mark.ac("E07-AC-14")
@pytest.mark.ac("E07-AC-10")
@pytest.mark.parametrize(("stack", "uv_lock"), list(JENKINS_SETUP))
def test_jenkinsfile_is_a_declarative_pipeline_with_the_expected_steps(
    stack: str, uv_lock: bool
) -> None:
    text = render("jenkins", _spec(stack, uv_lock=uv_lock))
    assert _balanced(text)
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//"))
    assert body.strip().startswith("pipeline {")
    assert body.rstrip().endswith("}")
    assert "agent any" in body
    assert re.search(r"stage\('Setup'\)", body)
    assert re.search(r"stage\('Gate'\)", body)
    steps = _sh_steps(body)
    tool_checks = [s for s in steps if s.startswith("command -v ")]
    assert [s.split()[2] for s in tool_checks] == JENKINS_TOOLS[(stack, uv_lock)]
    for check in tool_checks:
        assert "exit 1" in check and "not" in check, check
    installs = [s for s in steps if not s.startswith(("command -v ", "git ")) and GATE not in s]
    assert installs == JENKINS_SETUP[(stack, uv_lock)]
    gates = [s for s in steps if GATE in s]
    assert gates == [
        "python " + GATE + " --base-ref origin/${env.CHANGE_TARGET}",
        "python " + GATE,
    ]
    assert "git fetch origin ${env.CHANGE_TARGET}" in steps


@pytest.mark.ac("E07-AC-10")
def test_jenkinsfile_gates_pull_requests_and_the_base_branch_with_full_history() -> None:
    text = render("jenkins", _spec("python", base="develop"))
    assert "changeRequest()" in text
    assert "branch 'develop'" in text
    assert "--unshallow" in text
    assert "Python 3.12" in text and "uv" in text  # the header names what the agent needs


@pytest.mark.ac("E07-AC-14")
@pytest.mark.parametrize("provider", list(PATHS))
@pytest.mark.parametrize("stack", list(STACKS))
def test_rendering_is_deterministic(provider: str, stack: str) -> None:
    assert render(provider, _spec(stack)) == render(provider, _spec(stack))


@pytest.mark.ac("E07-AC-14")
@pytest.mark.parametrize("provider", YAML_PROVIDERS)
@pytest.mark.parametrize("stack", list(STACKS))
def test_every_yaml_pipeline_parses(provider: str, stack: str) -> None:
    for uv_lock in (True, False):
        _yaml(render(provider, _spec(stack, uv_lock=uv_lock)))


# --- AC-09, AC-11, AC-12, AC-13: install.py ci ---------------------------------------------------


def _repo(tmp_path: Path, files: dict[str, str] | None = None) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for rel, text in (files or {"pyproject.toml": "[project]\nname = 'x'\n"}).items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    return repo


def _ci(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str]:
    code = cli.main(["ci", *args])
    out = capsys.readouterr()
    return code, out.out + out.err


def _manifest(repo: Path) -> dict[str, Any]:
    data = json.loads((repo / manifest.MANIFEST_RELPATH).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


TURN_ON = {
    "github": "nothing else",
    "gitlab": ".gitlab-ci.yml",
    "azure": "create a pipeline",
    "jenkins": "script path",
}


@pytest.mark.ac("E07-AC-09")
@pytest.mark.parametrize("provider", list(PATHS))
def test_ci_writes_one_file_per_provider_and_prints_the_turn_on_step(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], provider: str
) -> None:
    repo = _repo(tmp_path)
    code, output = _ci(capsys, provider, str(repo))
    assert code == 0, output
    assert (repo / PATHS[provider]).is_file()
    others = [p for name, p in PATHS.items() if name != provider]
    assert not any((repo / p).exists() for p in others)
    assert TURN_ON[provider] in output.lower(), output
    assert pipelines.PROVIDERS[provider].path == PATHS[provider]


@pytest.mark.ac("E07-AC-09")
def test_ci_installs_the_kit_and_renders_from_the_repo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, {"pyproject.toml": "[project]\nname = 'x'\n", "uv.lock": "x\n"})
    code, output = _ci(capsys, "github", str(repo))
    assert code == 0, output
    assert (repo / GATE).is_file()
    text = (repo / PATHS["github"]).read_text(encoding="utf-8")
    assert text == render("github", _spec("python", uv_lock=True))


@pytest.mark.ac("E07-AC-09")
def test_unknown_provider_exits_2(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    with pytest.raises(SystemExit) as exc:
        cli.main(["ci", "circleci", str(repo)])
    assert exc.value.code == 2


@pytest.mark.ac("E07-AC-10")
def test_ci_reads_python_command_and_base_ref_from_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    assert _ci(capsys, "github", str(repo))[0] == 0
    config = repo / ".agentic" / "config.toml"
    text = config.read_text(encoding="utf-8")
    text = text.replace('python_command = ["python"]', 'python_command = ["uv", "run", "python"]')
    text = text.replace('base_ref = "main"', 'base_ref = "origin/develop"')
    config.write_text(text, encoding="utf-8")
    code, output = _ci(capsys, "github", str(repo))
    assert code == 0, output
    expected = render(
        "github",
        _spec("python", uv_lock=False, python_command=("uv", "run", "python"), base="develop"),
    )
    assert (repo / PATHS["github"]).read_text(encoding="utf-8") == expected


@pytest.mark.ac("E07-AC-10")
def test_ci_detects_both_stacks(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path, {"pyproject.toml": "[project]\nname='x'\n", "package.json": "{}\n"})
    code, output = _ci(capsys, "azure", str(repo))
    assert code == 0, output
    expected = render("azure", _spec("both", uv_lock=False))
    assert (repo / PATHS["azure"]).read_text(encoding="utf-8") == expected


@pytest.mark.ac("E07-AC-11")
def test_ci_with_no_profile_exits_1_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, {"README.md": "hi\n"})
    code, output = _ci(capsys, "github", str(repo))
    assert code == 1
    assert "no profile applies" in output, output
    assert sorted(p.name for p in repo.iterdir()) == [".git", "README.md"]


@pytest.mark.ac("E07-AC-11")
def test_ci_outside_a_git_repo_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    code, _ = _ci(capsys, "github", str(plain))
    assert code == 1
    assert not (plain / ".github").exists()


@pytest.mark.ac("E07-AC-12")
def test_os_option_sets_the_github_runners(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    code, output = _ci(capsys, "github", str(repo), "--os", "ubuntu,windows,macos")
    assert code == 0, output
    job = _yaml((repo / PATHS["github"]).read_text(encoding="utf-8"))["jobs"]["gate"]
    assert job["strategy"]["matrix"]["os"] == ["ubuntu-latest", "windows-latest", "macos-latest"]
    assert _manifest(repo)["pipelines"] == {"github": {"os": ["ubuntu", "windows", "macos"]}}


@pytest.mark.ac("E07-AC-12")
def test_github_defaults_to_ubuntu(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path)
    assert _ci(capsys, "github", str(repo))[0] == 0
    assert _manifest(repo)["pipelines"] == {"github": {"os": ["ubuntu"]}}


@pytest.mark.ac("E07-AC-12")
@pytest.mark.parametrize("value", ["solaris", "ubuntu,beos", "", ","])
def test_unknown_os_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str], value: str) -> None:
    repo = _repo(tmp_path)
    code, output = _ci(capsys, "github", str(repo), "--os", value)
    assert code == 2, output
    assert not (repo / PATHS["github"]).exists()


@pytest.mark.ac("E07-AC-12")
@pytest.mark.parametrize("provider", ["gitlab", "azure", "jenkins"])
def test_other_providers_reject_os_with_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], provider: str
) -> None:
    repo = _repo(tmp_path)
    code, output = _ci(capsys, provider, str(repo), "--os", "ubuntu")
    assert code == 2, output
    assert not (repo / PATHS[provider]).exists()


@pytest.mark.ac("E07-AC-13")
def test_pipeline_file_is_tracked_in_the_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    assert _ci(capsys, "gitlab", str(repo))[0] == 0
    data = _manifest(repo)
    assert data["pipelines"] == {"gitlab": {}}
    assert PATHS["gitlab"] in data["files"]
    loaded = manifest.load(repo)
    assert loaded is not None
    assert PATHS["gitlab"] in loaded.files
    assert loaded.pipelines == {"gitlab": {}}


@pytest.mark.ac("E07-AC-13")
def test_running_ci_again_rerenders_with_no_changes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    assert _ci(capsys, "jenkins", str(repo))[0] == 0
    before = (repo / PATHS["jenkins"]).read_bytes()
    code, output = _ci(capsys, "jenkins", str(repo))
    assert code == 0, output
    assert (repo / PATHS["jenkins"]).read_bytes() == before


@pytest.mark.ac("E07-AC-13")
def test_plain_upgrade_rerenders_every_recorded_pipeline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    assert _ci(capsys, "github", str(repo))[0] == 0
    assert _ci(capsys, "azure", str(repo))[0] == 0
    config = repo / ".agentic" / "config.toml"
    text = config.read_text(encoding="utf-8").replace('base_ref = "main"', 'base_ref = "develop"')
    config.write_text(text, encoding="utf-8")
    (repo / "uv.lock").write_text("x\n", encoding="utf-8")
    code = cli.main([str(repo)])
    output = capsys.readouterr().out
    assert code == 0, output
    for provider in ("github", "azure"):
        rendered = (repo / PATHS[provider]).read_text(encoding="utf-8")
        assert rendered == render(provider, _spec("python", uv_lock=True, base="develop"))
        assert PATHS[provider] in output
    assert _manifest(repo)["pipelines"] == {"azure": {}, "github": {"os": ["ubuntu"]}}


@pytest.mark.ac("E07-AC-13")
def test_an_edited_pipeline_is_a_conflict_kept_unless_force(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    assert _ci(capsys, "github", str(repo))[0] == 0
    path = repo / PATHS["github"]
    edited = path.read_text(encoding="utf-8") + "# my edit\n"
    path.write_text(edited, encoding="utf-8")
    code, output = _ci(capsys, "github", str(repo), "--os", "ubuntu,windows")
    assert code == 0, output
    assert path.read_text(encoding="utf-8") == edited
    new = repo / (PATHS["github"] + ".factory-new")
    assert new.is_file()
    assert "windows-latest" in new.read_text(encoding="utf-8")

    code, output = _ci(capsys, "github", str(repo), "--force")
    assert code == 0, output
    assert path.read_text(encoding="utf-8") == render(
        "github", _spec("python", uv_lock=False, os_list=("ubuntu", "windows"))
    )


@pytest.mark.ac("E07-AC-13")
def test_a_deleted_pipeline_stays_deleted_on_upgrade(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    assert _ci(capsys, "azure", str(repo))[0] == 0
    (repo / PATHS["azure"]).unlink()
    assert cli.main([str(repo)]) == 0
    capsys.readouterr()
    assert not (repo / PATHS["azure"]).exists()


@pytest.mark.ac("E07-AC-13")
def test_manifest_ignores_unknown_providers_and_foreign_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".factory").mkdir(parents=True)
    (repo / manifest.MANIFEST_RELPATH).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kit_version": "0.1.0",
                "files": {
                    ".factory/gates/gate.py": "a" * 64,
                    PATHS["github"]: "b" * 64,
                    "evil/outside.yml": "c" * 64,
                    "jenkins/other.Jenkinsfile": "d" * 64,
                },
                "deleted": [PATHS["azure"], "evil/gone.yml"],
                "pipelines": {"github": {"os": ["windows"]}, "circleci": {}, "azure": {}},
            }
        ),
        encoding="utf-8",
    )
    loaded = manifest.load(repo)
    assert loaded is not None
    assert set(loaded.files) == {".factory/gates/gate.py", PATHS["github"]}
    assert loaded.deleted == [PATHS["azure"]]
    assert loaded.pipelines == {"github": {"os": ["windows"]}, "azure": {}}


@pytest.mark.ac("E07-AC-13")
def test_a_plain_install_without_pipelines_writes_no_pipelines_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    assert cli.main([str(repo)]) == 0
    capsys.readouterr()
    assert "pipelines" not in _manifest(repo)
