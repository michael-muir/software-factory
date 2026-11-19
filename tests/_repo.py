"""Helpers for installer tests: throwaway git repos, file snapshots, the expected layout."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

from tests._ac import REPO_ROOT

INSTALL_PY = REPO_ROOT / "install.py"
KIT_VERSION = (REPO_ROOT / "kit" / "VERSION").read_text(encoding="utf-8").strip()

# E01 spec "Target layout" plus the files ADR 0004 (.gitattributes) and ADR 0005 (.gitignore)
# add, plus the gate engine E05 AC-21 ships in .factory/gates/ (replacing its .gitkeep),
# plus the Python profile and its mutation helper (E06 AC-01, AC-05), plus the git hooks
# and their launcher (E07 AC-04), plus the state module (E02, ADR 0015).
KIT_FILES = frozenset(
    {
        ".factory/.gitattributes",
        ".factory/.gitignore",
        ".factory/agents/_schema.md",
        ".factory/agents/_template.md",
        ".factory/agents/agents.py",
        ".factory/skills/.gitkeep",
        ".factory/standards/.gitkeep",
        ".factory/gates/gate.py",
        ".factory/gates/profiles/.gitkeep",
        ".factory/gates/profiles/python.toml",
        ".factory/gates/tools/mutate_python.py",
        ".factory/gates/profiles/ts-js.toml",
        ".factory/gates/tools/mutate_ts.py",
        ".factory/gates/hooks/pre-commit",
        ".factory/gates/hooks/pre-push",
        ".factory/gates/hooks/run_hook.py",
        ".factory/state/state.py",
        ".factory/workflow/.gitkeep",
        ".factory/adapters/.gitkeep",
    }
)
STATE_FILES = frozenset(
    {
        ".agentic/.gitattributes",
        ".agentic/config.toml",
        ".agentic/STATE.md",
        ".agentic/tasks/.gitkeep",
        ".agentic/handoffs/.gitkeep",
        ".agentic/locks/.gitkeep",
        "docs/GLOSSARY.md",
        "docs/adr/README.md",
    }
)
MANIFEST = ".factory/manifest.json"
INSTALLED_FILES = KIT_FILES | STATE_FILES | {MANIFEST}


def git_repo(path: Path) -> Path:
    """Create an empty git repository at `path` and return it."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


def files_under(root: Path) -> set[str]:
    """Every file below `root` as a posix relative path, ignoring the .git directory."""
    found: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            found.add((Path(dirpath) / name).relative_to(root).as_posix())
    return found


def snapshot(root: Path) -> dict[str, bytes]:
    """Map of relative path to bytes for every file below `root` (excluding .git)."""
    return {rel: (root / rel).read_bytes() for rel in files_under(root)}


def normalised_hash(data: bytes) -> str:
    """ADR 0004: SHA-256 of the content with CRLF normalised to LF."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def run_install_py(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run `python install.py ...` in a subprocess with the current interpreter."""
    return subprocess.run(
        [sys.executable, str(INSTALL_PY), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )
