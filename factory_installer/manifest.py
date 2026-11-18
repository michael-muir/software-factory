"""`.factory/manifest.json`: installed kit version and the hash of every kit file (AC-08, AC-17)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from factory_installer.pipelines import PIPELINE_PATHS, PROVIDERS, clean_options

MANIFEST_RELPATH = ".factory/manifest.json"
SCHEMA_VERSION = 1
KIT_PREFIX = ".factory/"


@dataclass
class Manifest:
    kit_version: str
    files: dict[str, str] = field(default_factory=dict)  # posix relpath -> normalised hash
    # Kit files the user deleted; remembered so later runs do not recreate them (ADR 0005, A).
    deleted: list[str] = field(default_factory=list)
    # Pipeline providers set up with `install.py ci`, and their options (ADR 0013).
    pipelines: dict[str, dict[str, list[str]]] = field(default_factory=dict)

    def to_bytes(self) -> bytes:
        data: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "kit_version": self.kit_version,
            "files": dict(sorted(self.files.items())),
            "deleted": sorted(self.deleted),
        }
        if self.pipelines:
            data["pipelines"] = dict(sorted(self.pipelines.items()))
        return (json.dumps(data, indent=2) + "\n").encode("utf-8")


def load(root: Path) -> Manifest | None:
    """Read the manifest, or None if there is none.

    Entries outside `.factory/` are ignored, except the four fixed pipeline paths: the file sits
    in the user's repo, so its paths are untrusted and must never steer an update or removal
    elsewhere. Unknown pipeline providers are ignored too.
    """
    path = root / MANIFEST_RELPATH
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    files = {
        str(rel): str(digest)
        for rel, digest in dict(data.get("files", {})).items()
        if _is_kit_path(str(rel))
    }
    deleted = [str(rel) for rel in data.get("deleted", []) if _is_kit_path(str(rel))]
    recorded = data.get("pipelines", {})
    pipelines = {
        name: clean_options(name, options)
        for name, options in (recorded.items() if isinstance(recorded, dict) else [])
        if name in PROVIDERS
    }
    return Manifest(
        kit_version=str(data.get("kit_version", "")),
        files=files,
        deleted=deleted,
        pipelines=pipelines,
    )


def _is_kit_path(rel: str) -> bool:
    return (rel.startswith(KIT_PREFIX) and rel != MANIFEST_RELPATH) or rel in PIPELINE_PATHS
