"""The lines a change touched, for changed-lines mutation (E06 AC-05c). Standard library only.

Shared by mutate_python.py and mutate_ts.py, which import it from this folder.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Sequence
from pathlib import Path

Ranges = list[tuple[int, int]]  # 1-based, inclusive
HUNK = re.compile(rb"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)


def changed_lines(root: Path, base_ref: str, files: Sequence[str]) -> dict[str, Ranges]:
    """Each file's lines added or modified since merge-base(base_ref, HEAD), uncommitted changes
    included. Untracked files count in full; deleted lines count for nothing."""
    merge_base = _git(root, "merge-base", base_ref, "HEAD")
    if merge_base.returncode != 0:
        raise ValueError(f"base ref '{base_ref}' not found")
    base = merge_base.stdout.decode().strip()
    untracked = set(
        _git(root, "ls-files", "-z", "--others", "--exclude-standard", "--", *files)
        .stdout.decode("utf-8", errors="surrogateescape")
        .split("\0")
    )
    found: dict[str, Ranges] = {}
    for rel in files:
        if rel in untracked:
            count = len((root / rel).read_bytes().splitlines())
            found[rel] = [(1, count)] if count else []
            continue
        diff = _git(root, "diff", "-U0", "--no-color", "--no-ext-diff", base, "--", rel).stdout
        found[rel] = [
            (int(start), int(start) + int(length or 1) - 1)
            for start, length in HUNK.findall(diff)
            if length != b"0"
        ]
    return found


def in_ranges(line: int, ranges: Ranges) -> bool:
    return any(first <= line <= last for first, last in ranges)
