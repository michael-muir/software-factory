"""What the installer did (or would do), as text or JSON (AC-05, AC-11, AC-12, AC-14, AC-21)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from factory_installer.plan import Action, Step

# The six counts of the summary line (AC-11). "unchanged" and "deleted-locally" appear in the
# file list and JSON only.
SUMMARY_ACTIONS = (
    Action.CREATE,
    Action.SKIP,
    Action.OVERWRITE,
    Action.UPDATE,
    Action.KEEP,
    Action.REMOVE,
)


@dataclass
class Report:
    kit_version: str
    target: str
    dry_run: bool
    files: dict[str, list[str]] = field(default_factory=dict)
    pending_merge: list[str] = field(default_factory=list)

    @classmethod
    def from_steps(cls, kit_version: str, target: str, dry_run: bool, steps: list[Step]) -> Report:
        files: dict[str, list[str]] = {action.value: [] for action in Action}
        pending: list[str] = []
        for step in steps:
            files[step.action.value].append(step.path)
            if step.merge_path is not None:
                pending.append(step.merge_path)
        return cls(kit_version, target, dry_run, files, pending)

    @property
    def counts(self) -> dict[str, int]:
        return {action: len(paths) for action, paths in self.files.items()}

    @property
    def up_to_date(self) -> bool:
        """ADR 0006: nothing created, skipped, overwritten, updated, kept or removed; no merges."""
        counts = self.counts
        return not self.pending_merge and all(counts[a.value] == 0 for a in SUMMARY_ACTIONS)

    def to_json(self) -> str:
        data = {
            "kit_version": self.kit_version,
            "target": self.target,
            "dry_run": self.dry_run,
            "up_to_date": self.up_to_date,
            "counts": self.counts,
            "files": self.files,
            "pending_merge": self.pending_merge,
        }
        return json.dumps(data, indent=2)

    def to_text(self) -> str:
        if self.up_to_date:
            return f"Software Factory kit {self.kit_version} in {self.target} is up to date."
        verb = "Would install" if self.dry_run else "Installed"
        lines = [f"{verb} Software Factory kit {self.kit_version} into {self.target}"]
        width = max(len(action.value) for action in Action)
        for action in Action:
            if action is Action.UNCHANGED:
                continue
            for path in self.files.get(action.value, []):
                lines.append(f"  {action.value:<{width}}  {path}")
        if self.pending_merge:
            lines.append("New kit versions to merge (git-ignored; delete each after merging):")
            lines += [f"  {path}" for path in self.pending_merge]
        counts = self.counts
        lines.append(", ".join(f"{counts.get(a.value, 0)} {a.value}" for a in SUMMARY_ACTIONS))
        if self.dry_run:
            lines.append("Dry run: nothing was written.")
        if self.pending_merge:
            lines.append(f"{len(self.pending_merge)} file(s) waiting to be merged.")
        return "\n".join(lines)
