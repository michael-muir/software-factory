"""`install.py hooks`: switch the kit's git hooks on or off for one clone (E07 AC-08, ADR 0012).

Hooks are switched on by pointing the clone's local core.hooksPath at the kit's hooks folder.
A hooks path set by something else (husky, pre-commit) is never replaced without --force.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from factory_installer.kit import EXECUTABLE_FILES
from factory_installer.target import find_git_root

HOOKS_PATH = ".factory/gates/hooks"
LAUNCHER = HOOKS_PATH + "/run_hook.py"


def _git_config(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "config", "--local", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def current_hooks_path(repo: Path) -> str | None:
    result = _git_config(repo, "--get", "core.hooksPath")
    return result.stdout.strip() if result.returncode == 0 else None


def _is_ours(value: str) -> bool:
    return value.replace("\\", "/").rstrip("/") in (HOOKS_PATH, "./" + HOOKS_PATH)


def make_executable(repo: Path) -> None:
    """Set 0o755 on the hook scripts; repos committed from Windows can lose the exec bit."""
    for rel in EXECUTABLE_FILES:
        path = repo / rel
        if path.is_file():
            os.chmod(path, 0o755)


def run_hooks(target: Path, *, force: bool, remove: bool) -> int:
    if not target.is_dir() or find_git_root(target) is None:
        print(f"{target}: not inside a git working tree", file=sys.stderr)
        return 1
    if not (target / LAUNCHER).is_file():
        print(
            f"{target}: the factory kit is not installed here; run install.py first",
            file=sys.stderr,
        )
        return 1

    current = current_hooks_path(target)
    if remove:
        if current is None:
            print("Factory hooks are already off (core.hooksPath is not set).")
            return 0
        if not _is_ours(current):
            print(
                f"core.hooksPath is {current!r}, not the factory hooks; left unchanged.",
                file=sys.stderr,
            )
            return 1
        _git_config(target, "--unset", "core.hooksPath")
        print("Factory hooks off: core.hooksPath unset.")
        return 0

    make_executable(target)
    if current is not None and _is_ours(current):
        print(f"Factory hooks are already on (core.hooksPath = {current}).")
        return 0
    if current is not None and not force:
        print(
            f"core.hooksPath is already set to {current!r}; "
            "use --force to replace it with the factory hooks.",
            file=sys.stderr,
        )
        return 1
    result = _git_config(target, "core.hooksPath", HOOKS_PATH)
    if result.returncode != 0:
        print(f"git config failed: {result.stderr.strip()}", file=sys.stderr)
        return 1
    replaced = f" (replaced {current!r})" if current is not None else ""
    print(f"Factory hooks on: core.hooksPath = {HOOKS_PATH}{replaced}.")
    print("pre-commit runs gates.commit_checks; pre-push runs the full gate.")
    return 0
