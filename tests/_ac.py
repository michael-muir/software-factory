"""Acceptance-criterion traceability helpers (AC-23)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO_ROOT / "docs" / "specs" / "E01-repo-skeleton-installer.md"

# AC ids named by @pytest.mark.ac(...) on every collected test, captured before -k/-m deselection.
COLLECTED_AC_IDS = pytest.StashKey[set[str]]()


def spec_ac_ids() -> set[str]:
    """Return every AC id the E01 spec defines, e.g. {"AC-01", ..., "AC-23"}."""
    text = SPEC_PATH.read_text(encoding="utf-8")
    return set(re.findall(r"\*\*(AC-\d{2})\*\*", text))
