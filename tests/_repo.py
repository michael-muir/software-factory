"""Helpers for installer tests: throwaway git repos, file snapshots, the expected layout."""

from __future__ import annotations

import hashlib
import json
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
        ".factory/agents/core/adversary.md",
        ".factory/agents/core/architect.md",
        ".factory/agents/core/debugger.md",
        ".factory/agents/core/docs-writer.md",
        ".factory/agents/core/implementer.md",
        ".factory/agents/core/integrator.md",
        ".factory/agents/core/perf-reviewer.md",
        ".factory/agents/core/release-manager.md",
        ".factory/agents/core/retro.md",
        ".factory/agents/core/router.md",
        ".factory/agents/core/security-reviewer.md",
        ".factory/agents/core/spec-reviewer.md",
        ".factory/agents/core/spec-writer.md",
        ".factory/agents/core/standards-reviewer.md",
        ".factory/agents/core/test-designer.md",
        ".factory/agents/core/verifier.md",
        ".factory/agents/claude-hook",
        ".factory/agents/copilot-hook",
        ".factory/agents/cursor-hook",
        ".factory/skills/adversarial-testing/SKILL.md",
        ".factory/skills/debugging/SKILL.md",
        ".factory/skills/dependency-bump/SKILL.md",
        ".factory/skills/design-note/SKILL.md",
        ".factory/skills/handoff/SKILL.md",
        ".factory/skills/lock-tests/SKILL.md",
        ".factory/skills/perf-budget/SKILL.md",
        ".factory/skills/release/SKILL.md",
        ".factory/skills/resume-from-state/SKILL.md",
        ".factory/skills/retro/SKILL.md",
        ".factory/skills/spec-interview/SKILL.md",
        ".factory/skills/spec-review/SKILL.md",
        ".factory/skills/standards-review/SKILL.md",
        ".factory/skills/tdd-slices/SKILL.md",
        ".factory/skills/threat-check/SKILL.md",
        ".factory/skills/verify-with-evidence/SKILL.md",
        ".factory/standards/.gitkeep",
        ".factory/gates/gate.py",
        ".factory/gates/profiles/.gitkeep",
        ".factory/gates/profiles/python.toml",
        ".factory/gates/tools/changed_lines.py",
        ".factory/gates/tools/mutate_python.py",
        ".factory/gates/profiles/ts-js.toml",
        ".factory/gates/tools/mutate_ts.py",
        ".factory/gates/hooks/pre-commit",
        ".factory/gates/hooks/pre-push",
        ".factory/gates/hooks/run_hook.py",
        ".factory/state/state.py",
        ".factory/workflow/docs.py",
        ".factory/workflow/templates/adr.md",
        ".factory/workflow/templates/design.md",
        ".factory/workflow/templates/pr-evidence.md",
        ".factory/workflow/templates/spec.md",
        ".factory/workflow/templates/task.md",
        ".factory/adapters/build.py",
        ".factory/runner/run.py",
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


def generated_files(root: Path) -> set[str]:
    """E12: the tool files the adapter build wrote, and its manifest (ADR 0023)."""
    manifest = root / ".factory" / "adapters" / "generated.json"
    if not manifest.is_file():
        return set()
    listed = json.loads(manifest.read_text(encoding="utf-8"))["files"]
    return {*listed, ".factory/adapters/generated.json"}


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
