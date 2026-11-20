"""Helpers for the E16/T3 halting tests: process trees, liveness, and repos with a real state.py.

The seams come from the E16 design note ("Process trees", "Test seams") and ADR 0031: the
fixture `tests/fixtures/runner/tree.py` writes the process ids of a command, its child and its
grandchild, and `alive(pid)` says whether one is still running, on every OS.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Iterable
from pathlib import Path

from tests._ac import REPO_ROOT
from tests._runner import git, runner_repo

TREE = REPO_ROOT / "tests" / "fixtures" / "runner" / "tree.py"
STATE_PY = REPO_ROOT / "kit" / ".factory" / "state" / "state.py"
ROLES = ("command", "child", "grandchild")
GONE_S = 10.0  # AC-17: the whole tree is gone within 10 seconds


def tree_argv(pids: Path, *, orphan: bool = False) -> list[str]:
    """A command that starts a child and a grandchild, writing their process ids into pids/."""
    pids.mkdir(parents=True, exist_ok=True)
    return [sys.executable, str(TREE), str(pids), "orphan" if orphan else "wait"]


def read_pids(pids: Path, timeout: float = 60) -> dict[str, int]:
    """The three process ids, once every process of the tree has written its own."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        files = [pids / f"{role}.pid" for role in ROLES]
        if all(f.exists() for f in files):
            return {
                role: int(f.read_text(encoding="utf-8"))
                for role, f in zip(ROLES, files, strict=True)
            }
        time.sleep(0.05)
    raise AssertionError(f"the tree in {pids} did not start: {sorted(os.listdir(pids))}")


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL

    def alive(pid: int) -> bool:
        """OpenProcess and GetExitCodeProcess: running means STILL_ACTIVE (259)."""
        handle = _kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not _kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259
        finally:
            _kernel32.CloseHandle(handle)

    def reap(pids: Iterable[int]) -> None:
        for pid in pids:
            if alive(pid):
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)

else:

    def alive(pid: int) -> bool:
        """Running, and not a zombie waiting to be reaped (a container's init may not reap)."""
        result = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, check=False
        )
        state = result.stdout.strip()
        return bool(state) and not state.startswith("Z")

    def reap(pids: Iterable[int]) -> None:
        for pid in pids:
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGKILL)


def all_gone(pids: Iterable[int], timeout: float = GONE_S) -> bool:
    wanted = list(pids)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(alive(pid) for pid in wanted):
            return True
        time.sleep(0.05)
    return not any(alive(pid) for pid in wanted)


def factory_repo(tmp_path: Path, config: str | None = None, *, name: str = "proj") -> Path:
    """A runner repo whose commit holds the kit's state.py and a valid `.agentic` (E02)."""
    root = runner_repo(tmp_path, config, name=name)
    state = root / ".factory" / "state"
    state.mkdir(parents=True)
    shutil.copy2(STATE_PY, state / "state.py")
    subprocess.run(
        [sys.executable, str(state / "state.py"), "--root", str(root), "init"],
        check=True,
        capture_output=True,
    )
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "factory state")
    return root


def state_py(worktree: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """The worktree's own state.py, as the runner runs it (design note, "The handoff on halt")."""
    script = worktree / ".factory" / "state" / "state.py"
    return subprocess.run(
        [sys.executable, str(script), "--root", str(worktree), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def handoffs(worktree: Path, task: str) -> list[Path]:
    folder = worktree / ".agentic" / "handoffs"
    return sorted(folder.glob(f"*-{task}.md")) if folder.is_dir() else []
