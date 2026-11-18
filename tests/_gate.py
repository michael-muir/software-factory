"""Fixtures for gate tests: real git repos with fixture profiles and tiny stand-in commands.

Fixture commands run the current interpreter (`sys.executable -c ...`), so tests stay fast and
behave the same on every platform (E05 design note, test seams).
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

import gate
from tests._ac import REPO_ROOT

GATE_PY = REPO_ROOT / "kit" / ".factory" / "gates" / "gate.py"
CHECK_ORDER = ("format", "lint", "types", "build", "tests", "coverage", "mutation")

PASS = [sys.executable, "-c", "pass"]


def exits(code: int) -> list[str]:
    return [sys.executable, "-c", f"import sys; sys.exit({code})"]


def prints(*lines: str, code: int = 0) -> list[str]:
    script = f"import sys; print('\\n'.join({list(lines)!r})); sys.exit({code})"
    return [sys.executable, "-c", script]


def touches(name: str) -> list[str]:
    """A passing command that creates `name` in the current directory (proves it ran)."""
    return [sys.executable, "-c", f"open({name!r}, 'w').close()"]


def toml_str(value: str) -> str:
    return json.dumps(value)  # a JSON string is a valid TOML basic string


def toml_list(values: Sequence[str]) -> str:
    return "[" + ", ".join(toml_str(v) for v in values) + "]"


def profile(
    name: str,
    detect: Sequence[str] = (),
    checks: Mapping[str, Sequence[str]] | None = None,
    mutation_paths: Sequence[str] = ("*.py",),
) -> str:
    lines = [
        f"name = {toml_str(name)}",
        f"detect = {toml_list(detect)}",
        f"mutation_paths = {toml_list(mutation_paths)}",
    ]
    for check, command in (checks or {}).items():
        lines += ["", f"[checks.{check}]", f"command = {toml_list(command)}"]
    return "\n".join(lines) + "\n"


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def gate_repo(
    root: Path,
    profiles: Mapping[str, str],
    *,
    config: str | None = None,
    files: Mapping[str, str] | None = None,
) -> Path:
    """A git repo on branch main with one commit holding the profiles, config and files."""
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    profiles_dir = root / ".factory" / "gates" / "profiles"
    profiles_dir.mkdir(parents=True)
    for filename, text in profiles.items():
        (profiles_dir / filename).write_text(text, encoding="utf-8")
    if config is not None:
        (root / ".agentic").mkdir()
        (root / ".agentic" / "config.toml").write_text(config, encoding="utf-8")
    for rel, text in (files or {}).items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    (root / ".gitignore").write_text("ran-*.txt\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "fixture")
    return root


def run_gate(
    cwd: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *args: str,
) -> tuple[int, str]:
    monkeypatch.chdir(cwd)
    code = gate.main(list(args))
    out = capsys.readouterr()
    return code, out.out + out.err


def run_gate_json(
    cwd: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, dict[str, object]]:
    monkeypatch.chdir(cwd)
    code = gate.main(["--json"])
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, dict)
    return code, data


def checks_of(report: dict[str, object]) -> list[dict[str, object]]:
    checks = report["checks"]
    assert isinstance(checks, list)
    return checks
