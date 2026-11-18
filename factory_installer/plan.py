"""Pure planning: decide what happens to every kit and state file. No I/O (design note).

T3 scope: a first install (no manifest). The upgrade rows of ADR 0005 arrive with T5.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from factory_installer.kit import Kit, content_hash


class Action(StrEnum):
    CREATE = "created"
    SKIP = "skipped"
    OVERWRITE = "overwritten"
    UPDATE = "updated"
    KEEP = "kept"
    REMOVE = "removed"
    UNCHANGED = "unchanged"

    @property
    def writes(self) -> bool:
        return self in (Action.CREATE, Action.OVERWRITE, Action.UPDATE)


# Actions after which the file on disk is the kit's content, so the manifest may claim it.
CLAIMED = frozenset({Action.CREATE, Action.OVERWRITE, Action.UPDATE, Action.UNCHANGED})


@dataclass(frozen=True)
class Step:
    path: str
    action: Action
    kit_managed: bool
    kit_hash: str
    content: bytes  # kit content for this path; written only when action.writes


def plan(kit: Kit, disk: Mapping[str, str | None], *, force: bool = False) -> list[Step]:
    """Plan a first install. `disk` maps each kit path to its current normalised hash or None."""
    steps: list[Step] = []
    for rel, content in kit.files.items():
        managed = kit.is_kit_managed(rel)
        kit_hash = content_hash(content)
        current = disk.get(rel)
        if current is None:
            action = Action.CREATE
        elif managed and current == kit_hash:
            action = Action.UNCHANGED
        elif managed and force:
            action = Action.OVERWRITE
        else:
            action = Action.SKIP
        steps.append(Step(rel, action, managed, kit_hash, content))
    return steps


def manifest_files(steps: list[Step]) -> dict[str, str]:
    """Kit-managed files whose content on disk is now the kit's, with their hashes (ADR 0005)."""
    return {s.path: s.kit_hash for s in steps if s.kit_managed and s.action in CLAIMED}
