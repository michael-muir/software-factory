"""Acceptance-criterion traceability helpers (E01 AC-23, E05 AC-23).

Every spec in docs/specs/ named `<EPIC>-*.md` defines ACs as **AC-nn**. Tests tag them with
@pytest.mark.ac(...): E01's as plain "AC-nn" (its tests predate multi-spec tracing), every later
epic's as "<EPIC>-AC-nn", for example "E05-AC-04".
"""

from __future__ import annotations

import os
import re
from collections.abc import Set
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SPECS_DIR = REPO_ROOT / "docs" / "specs"
SPEC_PATH = SPECS_DIR / "E01-repo-skeleton-installer.md"
LEGACY_EPIC = "E01"

# AC ids named by @pytest.mark.ac(...) on every collected test, captured before -k/-m deselection.
COLLECTED_AC_IDS = pytest.StashKey[Set[str]]()

_AC = re.compile(r"\*\*(AC-\d{2}[a-z]?)\*\*")  # e.g. AC-05, and AC-05b for a later insertion
_EPIC = re.compile(r"^(E\d{2})-")


def _spec_path(epic: str) -> Path:
    matches = sorted(SPECS_DIR.glob(f"{epic}-*.md"))
    assert len(matches) == 1, f"expected one spec for {epic}, found {matches}"
    return matches[0]


def spec_ac_ids(epic: str = LEGACY_EPIC) -> Set[str]:
    """AC tags one epic's spec defines: "AC-nn" for E01, "<EPIC>-AC-nn" for later epics."""
    found = _AC.findall(_spec_path(epic).read_text(encoding="utf-8"))
    return frozenset(found if epic == LEGACY_EPIC else (f"{epic}-{ac}" for ac in found))


def spec_epics() -> list[str]:
    """Every epic with a spec in docs/specs/, e.g. ["E01", "E05"]."""
    epics = {m.group(1) for p in SPECS_DIR.glob("*.md") if (m := _EPIC.match(p.name))}
    return sorted(epics)


def all_spec_ac_ids() -> Set[str]:
    """Every AC tag defined by any spec."""
    return frozenset().union(*(spec_ac_ids(epic) for epic in spec_epics()))
