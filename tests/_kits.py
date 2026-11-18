"""Build throwaway kit versions for upgrade tests (design note: the kit directory is injectable)."""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from pathlib import Path

from tests._ac import REPO_ROOT

SOURCE_KIT = REPO_ROOT / "kit"


def make_kit(base: Path, version: str, changes: Mapping[str, bytes | None] | None = None) -> Path:
    """Copy the real kit to `base/kit-<version>`, set VERSION, then apply `changes`.

    `changes` maps a posix path relative to the kit root to new bytes, or None to delete it.
    """
    root = base / f"kit-{version}"
    shutil.copytree(SOURCE_KIT, root)
    (root / "VERSION").write_text(version + "\n", encoding="utf-8")
    for rel, content in (changes or {}).items():
        path = root / rel
        if content is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    return root
