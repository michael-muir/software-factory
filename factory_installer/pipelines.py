"""Pipeline files for `install.py ci <provider>` (E07 AC-09 to AC-14, ADR 0013).

Each provider has a fixed file path and a renderer: a plain function from a PipelineSpec to the
file's text. Rendering is deterministic, so a re-render of unchanged inputs is byte-identical and
the installer's upgrade rules (ADRs 0005 and 0006) apply to pipeline files as to kit files.
"""

from __future__ import annotations

import importlib.util
import json
import shlex
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

GATE = ".factory/gates/gate.py"
PYTHON_VERSION = "3.12"
PYTHON_PROFILE = "python"
TS_PROFILE = "ts-js"
GITHUB_RUNNERS = {"ubuntu": "ubuntu-latest", "windows": "windows-latest", "macos": "macos-latest"}
DEFAULT_OS = ("ubuntu",)
HEADER = (
    "Software Factory gate (E07). Rendered by `python install.py ci {name}`; upgrades re-render it."
)


class PipelineError(Exception):
    """The repo's settings or profiles stop a pipeline from being rendered (exit 1)."""


@dataclass(frozen=True)
class PipelineSpec:
    profiles: tuple[str, ...]
    has_uv_lock: bool
    python_command: tuple[str, ...]
    base_branch: str
    os: tuple[str, ...] = DEFAULT_OS

    @property
    def python(self) -> bool:
        return PYTHON_PROFILE in self.profiles

    @property
    def ts(self) -> bool:
        return TS_PROFILE in self.profiles

    @property
    def uv(self) -> bool:
        return self.python and self.has_uv_lock

    def gate(self, *args: str) -> str:
        """The gate command line; `args` are passed through as written (provider syntax)."""
        command = " ".join(shlex.quote(word) for word in self.python_command)
        return " ".join((command, GATE, *args))


def _q(text: str) -> str:
    """A YAML double-quoted scalar (JSON strings are valid YAML)."""
    return json.dumps(text)


# --- GitHub Actions -----------------------------------------------------------------------------


def render_github(spec: PipelineSpec) -> str:
    runners = ", ".join(GITHUB_RUNNERS[name] for name in spec.os)
    lines = [
        f"# {HEADER.format(name='github')}",
        "name: factory-gate",
        "on:",
        "  pull_request:",
        "  push:",
        f"    branches: [{_q(spec.base_branch)}]",
        "jobs:",
        "  gate:",
        "    strategy:",
        "      fail-fast: false",
        "      matrix:",
        f"        os: [{runners}]",
        "    runs-on: ${{ matrix.os }}",
        "    steps:",
        "      - uses: actions/checkout@v4",
        "        with:",
        "          fetch-depth: 0",
        "      - uses: actions/setup-python@v5",
        "        with:",
        f"          python-version: {_q(PYTHON_VERSION)}",
    ]
    if spec.uv:
        lines += ["      - uses: astral-sh/setup-uv@v6", "      - run: uv sync --locked"]
    elif spec.python:
        lines += ["      - run: python -m pip install -e ."]
    if spec.ts:
        lines += [
            "      - uses: actions/setup-node@v4",
            "        with:",
            "          node-version: lts/*",
            "      - run: npm ci",
        ]
    lines += [
        "      - name: Gate (pull request)",
        "        if: github.event_name == 'pull_request'",
        f"        run: {_q(spec.gate('--base-ref', 'origin/${{ github.base_ref }}'))}",
        "      - name: Gate",
        "        if: github.event_name != 'pull_request'",
        f"        run: {_q(spec.gate())}",
    ]
    return "\n".join(lines) + "\n"


# --- GitLab CI ----------------------------------------------------------------------------------

MR_TARGET = "$CI_MERGE_REQUEST_TARGET_BRANCH_NAME"


def _gitlab_setup(spec: PipelineSpec) -> tuple[str, list[str]]:
    if not spec.ts:
        install = ["pip install uv", "uv sync --locked"] if spec.uv else ["pip install -e ."]
        return "python:3.12", install
    if not spec.python:
        return "node:lts", [
            "apt-get update && apt-get install -y python3 python-is-python3",
            "npm ci",
        ]
    setup = [
        "apt-get update && apt-get install -y python3 python3-pip python3-venv python-is-python3"
    ]
    if spec.uv:
        setup += ["pip install --break-system-packages uv", "uv sync --locked"]
    else:
        setup += ["pip install --break-system-packages -e ."]
    return "node:lts", [*setup, "npm ci"]


def render_gitlab(spec: PipelineSpec) -> str:
    image, setup = _gitlab_setup(spec)
    pull = spec.gate("--base-ref", '"origin/' + MR_TARGET + '"')
    script = (
        f'if [ -n "{MR_TARGET}" ]; then '
        f'git fetch origin "{MR_TARGET}" && {pull}; '
        f"else {spec.gate()}; fi"
    )
    merge_request = '$CI_PIPELINE_SOURCE == "merge_request_event"'
    base_push = '$CI_COMMIT_BRANCH == "' + spec.base_branch + '"'
    lines = [
        f"# {HEADER.format(name='gitlab')}",
        "# Turn it on: `include:` this file from .gitlab-ci.yml, or set it as the CI config path.",
        "factory-gate:",
        f"  image: {_q(image)}",
        "  variables:",
        '    GIT_DEPTH: "0"',
        "  rules:",
        f"    - if: {_q(merge_request)}",
        f"    - if: {_q(base_push)}",
        "  before_script:",
        *(f"    - {_q(step)}" for step in setup),
        "  script:",
        f"    - {_q(script)}",
    ]
    return "\n".join(lines) + "\n"


# --- Azure Pipelines ----------------------------------------------------------------------------

AZURE_TARGET = "$(System.PullRequest.TargetBranchName)"


def render_azure(spec: PipelineSpec) -> str:
    lines = [
        f"# {HEADER.format(name='azure')}",
        "trigger:",
        "  branches:",
        f"    include: [{_q(spec.base_branch)}]",
        "pr:",
        "  branches:",
        '    include: ["*"]',
        "pool:",
        "  vmImage: ubuntu-latest",
        "steps:",
        "  - checkout: self",
        "    fetchDepth: 0",
        "  - task: UsePythonVersion@0",
        "    inputs:",
        f"      versionSpec: {_q(PYTHON_VERSION)}",
    ]
    if spec.uv:
        lines += ["  - script: pip install uv", "  - script: uv sync --locked"]
    elif spec.python:
        lines += ["  - script: python -m pip install -e ."]
    if spec.ts:
        lines += [
            "  - task: NodeTool@0",
            "    inputs:",
            '      versionSpec: "22.x"  # the current Node LTS line',
            "  - script: npm ci",
        ]
    pull = f"git fetch origin {AZURE_TARGET} && {spec.gate('--base-ref', f'origin/{AZURE_TARGET}')}"
    lines += [
        f"  - script: {_q(pull)}",
        "    displayName: Gate (pull request)",
        "    condition: eq(variables['Build.Reason'], 'PullRequest')",
        f"  - script: {_q(spec.gate())}",
        "    displayName: Gate",
        "    condition: ne(variables['Build.Reason'], 'PullRequest')",
    ]
    return "\n".join(lines) + "\n"


# --- Jenkins ------------------------------------------------------------------------------------


def _need(tool: str, what: str) -> str:
    return (
        f"            sh 'command -v {tool} >/dev/null || "
        f'{{ echo "factory-gate: {what} is not on this agent" >&2; exit 1; }}\''
    )


def render_jenkins(spec: PipelineSpec) -> str:
    setup = [_need("python3", f"Python {PYTHON_VERSION}")]
    if spec.uv:
        setup.append(_need("uv", "uv"))
    if spec.ts:
        setup.append(_need("npm", "Node (npm)"))
    setup.append(
        "            sh 'git rev-parse --is-shallow-repository | grep -q true "
        "&& git fetch --unshallow || true'"
    )
    if spec.uv:
        setup.append("            sh 'uv sync --locked'")
    elif spec.python:
        setup.append("            sh 'python3 -m pip install -e .'")
    if spec.ts:
        setup.append("            sh 'npm ci'")
    pull = spec.gate("--base-ref", "origin/${env.CHANGE_TARGET}")
    lines = [
        f"// {HEADER.format(name='jenkins')}",
        "// Turn it on: point a Pipeline or Multibranch job's script path at this file.",
        f"// The agent needs Python {PYTHON_VERSION}, uv (Python projects with uv.lock) and Node",
        "// (TS/JS projects) on PATH, and runs sh steps, so use a Linux or macOS agent.",
        "pipeline {",
        "    agent any",
        "    stages {",
        "        stage('Setup') {",
        "            steps {",
        *setup,
        "            }",
        "        }",
        "        stage('Gate') {",
        "            when {",
        "                anyOf {",
        "                    changeRequest()",
        f"                    branch '{spec.base_branch}'",
        "                }",
        "            }",
        "            steps {",
        "                script {",
        "                    if (env.CHANGE_TARGET) {",
        '                        sh "git fetch origin ${env.CHANGE_TARGET}"',
        f'                        sh "{pull}"',
        "                    } else {",
        f"                        sh '{spec.gate()}'",
        "                    }",
        "                }",
        "            }",
        "        }",
        "    }",
        "}",
    ]
    return "\n".join(lines) + "\n"


# --- providers ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Provider:
    path: str
    turn_on: str
    render: Callable[[PipelineSpec], str]


PROVIDERS: dict[str, Provider] = {
    "github": Provider(
        ".github/workflows/factory-gate.yml",
        "GitHub Actions runs it on the next push or pull request: nothing else to do.",
        render_github,
    ),
    "gitlab": Provider(
        ".gitlab/factory-gate.yml",
        "Turn it on: `include:` it from .gitlab-ci.yml, or set it as the project's CI config path.",
        render_gitlab,
    ),
    "azure": Provider(
        ".azure-pipelines/factory-gate.yml",
        "Turn it on: in Azure DevOps, create a pipeline from this file.",
        render_azure,
    ),
    "jenkins": Provider(
        "jenkins/factory-gate.Jenkinsfile",
        "Turn it on: point a Pipeline job's script path at this file.",
        render_jenkins,
    ),
}
PIPELINE_PATHS = frozenset(provider.path for provider in PROVIDERS.values())


def render(name: str, spec: PipelineSpec) -> str:
    return PROVIDERS[name].render(spec)


def parse_os(text: str) -> tuple[str, ...]:
    """`--os ubuntu,windows` -> ("ubuntu", "windows"); raises ValueError naming bad values."""
    names = [part.strip() for part in text.split(",")]
    if not any(names) or any(name not in GITHUB_RUNNERS for name in names):
        bad = ", ".join(repr(n) for n in names if n not in GITHUB_RUNNERS) or repr(text)
        raise ValueError(f"--os: unknown OS {bad}; choose from {', '.join(GITHUB_RUNNERS)}")
    return tuple(dict.fromkeys(names))


def clean_options(name: str, options: object) -> dict[str, list[str]]:
    """A provider's recorded options from the (untrusted) manifest, keeping only valid ones."""
    if name != "github" or not isinstance(options, Mapping):
        return {}
    os_list = options.get("os")
    if isinstance(os_list, list) and os_list and all(o in GITHUB_RUNNERS for o in os_list):
        return {"os": [str(o) for o in os_list]}
    return {}


# --- detection: the kit's own gate decides which profiles apply ---------------------------------


def _load_gate(kit_root: Path) -> ModuleType:
    path = kit_root / ".factory" / "gates" / "gate.py"
    spec = importlib.util.spec_from_file_location("factory_kit_gate", path)
    if spec is None or spec.loader is None:
        raise PipelineError(f"cannot load the kit's gate from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["factory_kit_gate"] = module  # dataclasses look the module up by name
    spec.loader.exec_module(module)
    return module


def spec_for(
    kit_root: Path, target: Path, options: Mapping[str, Sequence[str]] | None = None
) -> PipelineSpec:
    """Detect what the gate will check in `target` and build the spec to render."""
    gate = _load_gate(kit_root)
    try:
        settings = gate.Settings.load(target)
        profiles = dict(gate.load_profiles(kit_root))
        profiles.update(gate.load_profiles(target))
        selected = gate.select_profiles(target, profiles, settings)
    except gate.GateError as exc:
        raise PipelineError(str(exc)) from exc
    base = str(settings.base_ref)
    base = base.removeprefix("origin/")
    os_list = tuple((options or {}).get("os", DEFAULT_OS))
    return PipelineSpec(
        profiles=tuple(p.name for p in selected),
        has_uv_lock=(target / "uv.lock").is_file(),
        python_command=tuple(settings.python_command),
        base_branch=base,
        os=os_list,
    )
