"""`.factory/manifest.json`: installed kit version and the hash of every kit file (AC-08)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

MANIFEST_RELPATH = ".factory/manifest.json"
SCHEMA_VERSION = 1


@dataclass
class Manifest:
    kit_version: str
    files: dict[str, str] = field(default_factory=dict)  # posix relpath -> normalised hash

    def to_bytes(self) -> bytes:
        data = {
            "schema_version": SCHEMA_VERSION,
            "kit_version": self.kit_version,
            "files": dict(sorted(self.files.items())),
        }
        return (json.dumps(data, indent=2) + "\n").encode("utf-8")
