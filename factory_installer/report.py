"""What the installer did (or would do), as text or JSON (AC-05, AC-11, AC-21)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from factory_installer.plan import Action, Step

# Order of the summary line (AC-11); "unchanged" is reported in JSON and the file list only.
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
        for step in steps:
            files[step.action.value].append(step.path)
        return cls(kit_version, target, dry_run, files)

    @property
    def counts(self) -> dict[str, int]:
        return {action: len(paths) for action, paths in self.files.items()}

    def to_json(self) -> str:
        data = {
            "kit_version": self.kit_version,
            "target": self.target,
            "dry_run": self.dry_run,
            "counts": self.counts,
            "files": self.files,
            "pending_merge": self.pending_merge,
        }
        return json.dumps(data, indent=2)

    def to_text(self) -> str:
        verb = "Would install" if self.dry_run else "Installed"
        lines = [f"{verb} Software Factory kit {self.kit_version} into {self.target}"]
        width = max(len(action.value) for action in Action)
        for action in Action:
            for path in self.files.get(action.value, []):
                lines.append(f"  {action.value:<{width}}  {path}")
        if self.pending_merge:
            lines.append("Waiting for you to merge (git-ignored):")
            lines += [f"  {path}" for path in self.pending_merge]
        counts = self.counts
        lines.append(", ".join(f"{counts.get(a.value, 0)} {a.value}" for a in SUMMARY_ACTIONS))
        if self.dry_run:
            lines.append("Dry run: nothing was written.")
        if self.pending_merge:
            lines.append(f"{len(self.pending_merge)} file(s) waiting to be merged.")
        return "\n".join(lines)
