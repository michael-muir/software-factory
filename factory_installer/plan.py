"""Pure planning: decide what happens to every kit and state file. No I/O (design note).

Implements ADR 0005's decision table as refined by ADR 0006. Hashes: M = manifest (previous
install), D = disk now, K = new kit. State seeds (ADR 0003) are only ever created or left alone.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from enum import StrEnum

from factory_installer.kit import Kit, content_hash

MERGE_SUFFIX = ".factory-new"


class Action(StrEnum):
    CREATE = "created"
    SKIP = "skipped"
    OVERWRITE = "overwritten"
    UPDATE = "updated"
    KEEP = "kept"
    REMOVE = "removed"
    UNCHANGED = "unchanged"
    DELETED_LOCALLY = "deleted-locally"

    @property
    def writes(self) -> bool:
        return self in (Action.CREATE, Action.OVERWRITE, Action.UPDATE)


# After these actions the file on disk holds the kit's content, so the manifest claims it.
CLAIMED = frozenset({Action.CREATE, Action.OVERWRITE, Action.UPDATE, Action.UNCHANGED})


@dataclass(frozen=True)
class Step:
    path: str
    action: Action
    kit_managed: bool
    kit_hash: str | None = None  # None when the file was dropped from the kit
    content: bytes | None = None  # kit content, written when action.writes or merge_path is set
    merge_path: str | None = None  # where to write the new kit version for the user to merge


def _kit_step(
    rel: str, content: bytes | None, previous: str | None, current: str | None, force: bool
) -> Step | None:
    kit_hash = content_hash(content) if content is not None else None

    def step(action: Action, merge: bool = False) -> Step:
        merge_path = rel + MERGE_SUFFIX if merge else None
        return Step(rel, action, True, kit_hash, content, merge_path)

    if previous is None:  # not installed by us before
        if current is None:
            return step(Action.CREATE)
        if current == kit_hash:
            return step(Action.UNCHANGED)
        return step(Action.OVERWRITE if force else Action.SKIP)

    if kit_hash is None:  # dropped from the kit
        if current is None:
            return None
        return step(Action.REMOVE if current == previous else Action.KEEP)

    if current is None:
        return step(Action.DELETED_LOCALLY)
    if current == kit_hash:
        return step(Action.UNCHANGED)
    if current == previous:
        return step(Action.UPDATE)
    if force:
        return step(Action.OVERWRITE)
    return step(Action.KEEP, merge=previous != kit_hash)


def plan(
    kit: Kit,
    disk: Mapping[str, str | None],
    previous: Mapping[str, str] | None = None,
    *,
    deleted: Collection[str] = (),
    force: bool = False,
) -> list[Step]:
    """Plan an install or upgrade.

    `disk` maps every path in the kit or the previous manifest to its normalised hash or None.
    `previous` is the previous manifest's files, or None on a first install; `deleted` lists kit
    files the user deleted after an earlier install (ADR 0005, choice A).
    """
    installed = previous is not None
    manifest = previous or {}
    steps: list[Step] = []
    for rel, content in kit.files.items():
        current = disk.get(rel)
        if kit.is_kit_managed(rel) and rel in deleted and current is None:
            steps.append(Step(rel, Action.DELETED_LOCALLY, True, content_hash(content)))
        elif kit.is_kit_managed(rel):
            kit_step = _kit_step(rel, content, manifest.get(rel), current, force)
            if kit_step is not None:
                steps.append(kit_step)
        elif current is None:
            steps.append(Step(rel, Action.CREATE, False, content_hash(content), content))
        else:
            action = Action.UNCHANGED if installed else Action.SKIP
            steps.append(Step(rel, action, False, content_hash(content)))
    for rel in sorted(set(manifest) - set(kit.files)):
        dropped = _kit_step(rel, None, manifest[rel], disk.get(rel), force)
        if dropped is not None:
            steps.append(dropped)
    return steps


def manifest_files(steps: list[Step], previous: Mapping[str, str] | None = None) -> dict[str, str]:
    """The new manifest: claimed files at the kit hash; kept files keep their old hash."""
    old = previous or {}
    files: dict[str, str] = {}
    for s in steps:
        if not s.kit_managed:
            continue
        if s.action in CLAIMED and s.kit_hash is not None:
            files[s.path] = s.kit_hash
        elif s.action is Action.KEEP and s.path in old:
            files[s.path] = old[s.path]
    return files


def manifest_deleted(steps: list[Step]) -> list[str]:
    """Kit files the user deleted that are still in the kit, so later runs leave them deleted."""
    return sorted(s.path for s in steps if s.action is Action.DELETED_LOCALLY)
