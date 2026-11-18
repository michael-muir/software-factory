"""Apply a plan to disk: atomic per-file writes, UTF-8 bytes with LF endings (AC-20)."""

from __future__ import annotations

import os
from pathlib import Path

from factory_installer.kit import to_lf
from factory_installer.plan import Action, Step


def write_file(root: Path, rel: str, data: bytes) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".factory-tmp")
    temp.write_bytes(to_lf(data))
    os.replace(temp, path)


def apply(root: Path, steps: list[Step]) -> None:
    for step in steps:
        if step.action.writes and step.content is not None:
            write_file(root, step.path, step.content)
        elif step.action is Action.REMOVE:
            (root / step.path).unlink()
        if step.merge_path is not None and step.content is not None:
            write_file(root, step.merge_path, step.content)
