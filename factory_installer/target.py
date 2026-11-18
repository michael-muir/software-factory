"""The target repository: git detection, path containment, current file hashes."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from factory_installer.kit import content_hash


class PathEscapeError(Exception):
    """A path the installer would write resolves outside the target (AC-19)."""

    def __init__(self, rel: str, resolved: Path) -> None:
        super().__init__(f"{rel} resolves outside the target, to {resolved}")
        self.rel = rel
        self.resolved = resolved


def find_git_root(path: Path) -> Path | None:
    """Return the working-tree root containing `path`, or None if it is not in one."""
    start = path.resolve()
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def ensure_inside(root: Path, rels: Iterable[str]) -> None:
    """Raise PathEscapeError if any relative path resolves outside `root` (symlinks followed)."""
    real_root = root.resolve()
    for rel in rels:
        resolved = (root / rel).resolve()
        if not resolved.is_relative_to(real_root):
            raise PathEscapeError(rel, resolved)


def current_hashes(root: Path, rels: Iterable[str]) -> dict[str, str | None]:
    """Normalised hash of each path that exists as a file, None for those that do not."""
    hashes: dict[str, str | None] = {}
    for rel in rels:
        path = root / rel
        hashes[rel] = content_hash(path.read_bytes()) if path.is_file() else None
    return hashes
