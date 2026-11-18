"""Reference projects and one-change seeds for profile tests (E06, ADR 0011).

A seed is a {path: content} overlay on a copy of a reference project that breaks exactly one
check. Projects get the real kit via install.py and run the real gate in a subprocess, with this
repo's venv first on PATH so the profiles' bare tool names resolve to it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from tests._ac import REPO_ROOT

PYTHON_REF = REPO_ROOT / "tests" / "fixtures" / "python-ref"
VENV_BIN = Path(sys.executable).parent

_CALC = (PYTHON_REF / "calc.py").read_text(encoding="utf-8")
_TEST_CALC = (PYTHON_REF / "test_calc.py").read_text(encoding="utf-8")


def _swap(text: str, old: str, new: str) -> str:
    assert old in text, f"seed expects {old!r} in the reference"
    return text.replace(old, new, 1)


_UNTESTED = (
    "\n\ndef banner() -> list[str]:\n    lines: list[str] = []\n"
    + "".join(f'    lines.append("line {n}")\n' for n in range(1, 21))
    + "    return lines\n"
)

PYTHON_SEEDS: dict[str, dict[str, str]] = {
    "format": {
        "calc.py": _swap(
            _CALC,
            "def add(a: int, b: int) -> int:\n    return a + b",
            "def add(a: int,b: int)->int:\n    return a+b",
        )
    },
    "lint": {
        "calc.py": _swap(_CALC, '"""\n\n\ndef add', '"""\n\nimport os\n\n\ndef add'),
    },
    "types": {
        "calc.py": _swap(_CALC, "    return a + b", "    total: str = a + b\n    return total"),
    },
    "tests": {
        "test_calc.py": _swap(_TEST_CALC, "assert add(2, 3) == 5", "assert add(2, 3) == 6"),
    },
    "coverage": {"calc.py": _CALC + _UNTESTED},
    "mutation": {
        "test_calc.py": (
            "from calc import add, clamp, is_positive\n\n\n"
            "def test_add() -> None:\n    assert add(2, 3)\n\n\n"
            "def test_is_positive() -> None:\n    assert is_positive(1)\n\n\n"
            "def test_clamp() -> None:\n    assert clamp(5, 0, 10)\n"
        )
    },
}


def tool_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = str(VENV_BIN) + os.pathsep + env.get("PATH", "")
    return env


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def python_project(
    dest: Path,
    seed: Mapping[str, str] | None = None,
    *,
    extra_pyproject: str = "",
) -> Path:
    """Copy the Python reference, apply a seed, install the kit, scope mutation to all files."""
    shutil.copytree(PYTHON_REF, dest)
    for rel, content in (seed or {}).items():
        (dest / rel).write_text(content, encoding="utf-8")
    if extra_pyproject:
        with (dest / "pyproject.toml").open("a", encoding="utf-8") as f:
            f.write("\n" + extra_pyproject)
    subprocess.run(["git", "init", "-q", "-b", "main", str(dest)], check=True)
    install = subprocess.run(
        [sys.executable, str(REPO_ROOT / "install.py"), str(dest)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert install.returncode == 0, install.stdout + install.stderr
    config = dest / ".agentic" / "config.toml"
    text = config.read_text(encoding="utf-8")
    config.write_text(
        text.replace('mutation_scope = "changed-lines"', 'mutation_scope = "all"', 1),
        encoding="utf-8",
    )
    git(dest, "add", "-A")
    git(dest, "commit", "-q", "-m", "fixture")
    return dest


def run_gate(project: Path) -> tuple[int, dict[str, object]]:
    result = subprocess.run(
        [sys.executable, ".factory/gates/gate.py", "--json"],
        cwd=project,
        capture_output=True,
        text=True,
        env=tool_env(),
        check=False,
    )
    assert result.stdout.strip(), result.stderr
    report = json.loads(result.stdout)
    assert isinstance(report, dict)
    return result.returncode, report


def statuses(report: dict[str, object]) -> dict[str, str]:
    checks = report["checks"]
    assert isinstance(checks, list)
    return {str(c["check"]): str(c["status"]) for c in checks}


def run_helper(
    project: Path, *args: str, env: Mapping[str, str] | None = None, python: str = sys.executable
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [python, ".factory/gates/tools/mutate_python.py", *args],
        cwd=project,
        capture_output=True,
        text=True,
        env=dict(env) if env is not None else tool_env(),
        check=False,
    )
