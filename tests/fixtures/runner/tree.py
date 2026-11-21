"""E16 AC-17 fixture: a command that starts a child, which starts a grandchild, all waiting.

Usage: tree.py <pid-dir> wait|orphan [command|child|grandchild]

Each process writes its own process id to `<pid-dir>/<role>.pid`, then waits. In `orphan` mode
the child exits as soon as the grandchild has written its id, so the grandchild is left without
a parent. Every process gives up after two minutes, so a failed test leaves nothing behind for
long.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

WAIT_S = 120.0


def write_pid(folder: Path, role: str) -> None:
    tmp = folder / f"{role}.tmp"
    tmp.write_text(str(os.getpid()), encoding="utf-8")
    os.replace(tmp, folder / f"{role}.pid")


def spawn(folder: Path, mode: str, role: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), str(folder), mode, role],
        stdin=subprocess.DEVNULL,
    )


def main(argv: list[str]) -> int:
    folder, mode = Path(argv[0]), argv[1]
    role = argv[2] if len(argv) > 2 else "command"
    write_pid(folder, role)
    if role == "command":
        spawn(folder, mode, "child")
    elif role == "child":
        spawn(folder, mode, "grandchild")
        if mode == "orphan":
            deadline = time.monotonic() + WAIT_S
            while not (folder / "grandchild.pid").exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            return 0
    time.sleep(WAIT_S)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
