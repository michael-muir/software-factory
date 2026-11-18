"""The kit: files the installer copies into a target repo (ADR 0002, ADR 0003)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parent.parent / "kit"
KIT_DIR = ".factory"  # kit-managed files, tracked in the manifest
STATE_DIR = ".agentic"  # state seeds, created only when missing
# Kit files written with mode 0o755 (E07 AC-04): the git hook shims.
EXECUTABLE_FILES = frozenset({".factory/gates/hooks/pre-commit", ".factory/gates/hooks/pre-push"})


@dataclass(frozen=True)
class Kit:
    version: str
    files: dict[str, bytes]  # posix path relative to the target root -> LF content
    # Rendered files outside .factory/ that follow the kit-file rules (pipelines, ADR 0013).
    extra_managed: frozenset[str] = frozenset()

    def is_kit_managed(self, rel: str) -> bool:
        return rel.startswith(KIT_DIR + "/") or rel in self.extra_managed


def to_lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def content_hash(data: bytes) -> str:
    """ADR 0004: SHA-256 of the content with CRLF normalised to LF."""
    return hashlib.sha256(to_lf(data)).hexdigest()


def _is_bytecode(rel: Path) -> bool:
    """Python's caches, written into kit/ whenever the kit's scripts are imported."""
    return "__pycache__" in rel.parts or rel.suffix == ".pyc"


def load_kit(root: Path = KIT_ROOT) -> Kit:
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    files: dict[str, bytes] = {}
    for top in (KIT_DIR, STATE_DIR):
        for path in sorted((root / top).rglob("*")):
            if path.is_file() and not _is_bytecode(path.relative_to(root)):
                files[path.relative_to(root).as_posix()] = to_lf(path.read_bytes())
    return Kit(version=version, files=files)
