"""The kit: files the installer copies into a target repo (ADR 0002, ADR 0003)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parent.parent / "kit"
KIT_DIR = ".factory"  # kit-managed files, tracked in the manifest
STATE_DIR = ".agentic"  # state seeds, created only when missing


@dataclass(frozen=True)
class Kit:
    version: str
    files: dict[str, bytes]  # posix path relative to the target root -> LF content

    def is_kit_managed(self, rel: str) -> bool:
        return rel.startswith(KIT_DIR + "/")


def to_lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def content_hash(data: bytes) -> str:
    """ADR 0004: SHA-256 of the content with CRLF normalised to LF."""
    return hashlib.sha256(to_lf(data)).hexdigest()


def load_kit(root: Path = KIT_ROOT) -> Kit:
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    files: dict[str, bytes] = {}
    for top in (KIT_DIR, STATE_DIR):
        for path in sorted((root / top).rglob("*")):
            if path.is_file():
                files[path.relative_to(root).as_posix()] = to_lf(path.read_bytes())
    return Kit(version=version, files=files)
