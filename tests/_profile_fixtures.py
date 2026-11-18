"""Reference projects and one-change seeds for profile tests (E06, ADR 0011).

A seed is a {path: content} overlay on a copy of a reference project that breaks exactly one
check. Projects get the real kit via install.py and run the real gate in a subprocess, with this
repo's venv first on PATH so the profiles' bare tool names resolve to it.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
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


def _write_lf(path: Path, text: str) -> None:
    # Always LF: on Windows write_text would emit CRLF, which Prettier (endOfLine lf) rejects.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _project(ref: Path, dest: Path, seed: Mapping[str, str] | None, extra_pyproject: str) -> Path:
    """Copy a reference, apply a seed, install the kit, scope mutation to all files, commit."""
    shutil.copytree(ref, dest, ignore=shutil.ignore_patterns("node_modules"))
    for rel, content in (seed or {}).items():
        _write_lf(dest / rel, content)
    if extra_pyproject:
        pyproject = dest / "pyproject.toml"
        _write_lf(pyproject, pyproject.read_text(encoding="utf-8") + "\n" + extra_pyproject)
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
    _write_lf(config, text.replace('mutation_scope = "changed-lines"', 'mutation_scope = "all"', 1))
    git(dest, "add", "-A")
    git(dest, "commit", "-q", "-m", "fixture")
    return dest


def python_project(
    dest: Path,
    seed: Mapping[str, str] | None = None,
    *,
    extra_pyproject: str = "",
) -> Path:
    """The Python reference, optionally seeded, as a committed git repo with the kit installed."""
    return _project(PYTHON_REF, dest, seed, extra_pyproject)


# --- TS/JS --------------------------------------------------------------------------------------

TS_REF = REPO_ROOT / "tests" / "fixtures" / "ts-js-ref"

_TS_CALC = (TS_REF / "src" / "calc.ts").read_text(encoding="utf-8")
_TS_TEST = (TS_REF / "src" / "calc.test.ts").read_text(encoding="utf-8")
_TS_PKG = (TS_REF / "package.json").read_text(encoding="utf-8")

TS_SEEDS: dict[str, dict[str, str]] = {
    "format": {
        "src/calc.ts": _swap(
            _TS_CALC,
            "export function add(a: number, b: number): number {\n  return a + b;",
            "export function add(a: number,b: number): number {\n  return a+b;",
        )
    },
    "lint": {
        "src/calc.ts": _swap(_TS_CALC, "  return a + b;", "  const unused = 1;\n  return a + b;"),
    },
    "types": {
        "src/calc.ts": _swap(
            _TS_CALC,
            "export function isPositive(x: number): boolean {",
            "export function isPositive(x: number): string {",
        ),
    },
    "build": {
        "package.json": _swap(
            _TS_PKG,
            '"build": "tsc -p tsconfig.build.json"',
            '"build": "node -e \\"process.exit(1)\\""',
        ),
    },
    "tests": {
        "src/calc.test.ts": _swap(
            _TS_TEST, "expect(add(2, 3)).toBe(5);", "expect(add(2, 3)).toBe(6);"
        ),
    },
    # Uncovered lines, but no Stryker mutants beyond one block and no lint errors.
    "coverage": {
        "src/calc.ts": _TS_CALC
        + "\nexport function untested(x: number): void {\n"
        + "  Number.isFinite(x);\n" * 20
        + "}\n"
    },
    # Same lines executed (coverage stays 100%), but assertions that kill almost nothing.
    "mutation": {
        "src/calc.test.ts": (
            'import { describe, expect, it } from "vitest";\n\n'
            'import { add, clamp, isPositive } from "./calc";\n\n'
            'describe("calc", () => {\n'
            '  it("adds", () => {\n'
            "    expect(add(2, 3)).toBeDefined();\n"
            "  });\n\n"
            '  it("knows positive numbers", () => {\n'
            "    expect(isPositive(1)).toBeDefined();\n"
            "    expect(isPositive(0)).toBeDefined();\n"
            "  });\n\n"
            '  it("clamps", () => {\n'
            "    expect(clamp(5, 0, 10)).toBeDefined();\n"
            "    expect(clamp(-1, 0, 10)).toBeDefined();\n"
            "    expect(clamp(11, 0, 10)).toBeDefined();\n"
            "  });\n"
            "});\n"
        )
    },
}

# Spec AC-12: tests also fails coverage and mutation (they need a green suite);
# types also fails build (the build compiles with tsc, which type-checks).
TS_ALSO_FAILS = {"tests": {"coverage", "mutation"}, "types": {"build"}}


def node_available() -> bool:
    return shutil.which("node") is not None and shutil.which("npm") is not None


def ts_node_modules() -> Path:
    """npm ci once per lockfile hash into a cache outside the repo (ADR 0011).

    Safe under pytest-xdist: each worker installs into its own staging directory and renames
    it into place; a worker that loses the race uses the winner's install.
    """
    lock = (TS_REF / "package-lock.json").read_bytes()
    digest = hashlib.sha256(lock).hexdigest()[:12]
    cache = Path.home() / ".cache" / "software-factory" / f"ts-js-ref-{digest}"
    if not (cache / ".complete").is_file():
        cache.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f"{cache.name}-", dir=cache.parent))
        try:
            for name in ("package.json", "package-lock.json"):
                shutil.copy2(TS_REF / name, staging / name)
            npm = shutil.which("npm")
            assert npm is not None
            result = subprocess.run(
                [npm, "ci", "--no-audit", "--no-fund"],
                cwd=staging,
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, f"npm ci failed:\n{result.stdout}{result.stderr}"
            (staging / ".complete").write_text("ok\n", encoding="utf-8")
            if cache.exists() and not (cache / ".complete").is_file():
                shutil.rmtree(cache, ignore_errors=True)  # a half-built cache from older code
            try:
                staging.rename(cache)
            except OSError:
                if not (cache / ".complete").is_file():
                    raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    return cache / "node_modules"


def _link_dir(link: Path, target: Path) -> None:
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except OSError:
        pass
    if sys.platform == "win32":
        import _winapi

        try:
            _winapi.CreateJunction(str(target), str(link))
            return
        except OSError:
            pass
    shutil.copytree(target, link, symlinks=True)


def ts_project(dest: Path, seed: Mapping[str, str] | None = None) -> Path:
    """The TS/JS reference, optionally seeded, with shared node_modules linked in."""
    modules = ts_node_modules()
    project = _project(TS_REF, dest, seed, "")
    _link_dir(project / "node_modules", modules)
    return project


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


def run_ts_helper(
    project: Path, *args: str, env: Mapping[str, str] | None = None, python: str = sys.executable
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [python, ".factory/gates/tools/mutate_ts.py", *args],
        cwd=project,
        capture_output=True,
        text=True,
        env=dict(env) if env is not None else tool_env(),
        check=False,
    )
