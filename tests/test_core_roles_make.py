"""E09/T1: the eight Coordinate, Specify, Make and Learn role cards.

Covers E09 AC-01 to AC-07 for `router`, `spec-writer`, `architect`, `test-designer`,
`implementer`, `debugger`, `docs-writer` and `retro`. The rows below are the spec's table
(docs/specs/E09-core-roles.md); expectations come from the spec, the design note and ADR 0021.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

import agents
import state
from tests._ac import REPO_ROOT

CORE = REPO_ROOT / "kit" / ".factory" / "agents" / "core"

ALL_ROLES = frozenset(
    {
        "router",
        "spec-writer",
        "architect",
        "test-designer",
        "implementer",
        "debugger",
        "docs-writer",
        "verifier",
        "spec-reviewer",
        "standards-reviewer",
        "security-reviewer",
        "perf-reviewer",
        "adversary",
        "integrator",
        "release-manager",
        "retro",
    }
)


@dataclass(frozen=True)
class Row:
    name: str
    title: str
    tools: tuple[str, ...]
    hint: str
    summary: str
    must_not: tuple[str, ...] = ()  # AC-07 phrases its Must not list must contain


WRITERS = ("read", "search", "edit", "write")
ROWS = (
    Row(
        "router",
        "Router",
        ("read", "search", "run"),
        "strong",
        "Triages incoming work, dispatches it to workers, replies to people and enforces "
        "round limits.",
    ),
    Row(
        "spec-writer",
        "Spec Writer",
        (*WRITERS, "web"),
        "strong",
        "Interviews the requester and writes numbered acceptance criteria.",
    ),
    Row(
        "architect",
        "Architect",
        (*WRITERS, "web"),
        "strong",
        "Writes the design note, ADRs, test seams and vertical slices.",
    ),
    Row(
        "test-designer",
        "Test Designer",
        (*WRITERS, "run"),
        "strong",
        "Writes failing tests from the spec, never from the code.",
        ("from the code",),
    ),
    Row(
        "implementer",
        "Implementer",
        (*WRITERS, "run"),
        "strong",
        "Makes the smallest change to green and cannot edit locked tests.",
        ("locked test",),
    ),
    Row(
        "debugger",
        "Debugger",
        (*WRITERS, "run"),
        "strong",
        "Finds the systematic root cause when the gate goes red.",
    ),
    Row(
        "docs-writer",
        "Docs Writer",
        WRITERS,
        "any",
        "Writes user docs and the Unreleased changelog entry.",
    ),
    Row(
        "retro",
        "Retro",
        WRITERS,
        "any",
        "Turns recurring failures into new checks and standards.",
    ),
)
IDS = [row.name for row in ROWS]


def card(name: str) -> tuple[dict[str, object], str]:
    parsed = state.parse((CORE / f"{name}.md").read_text(encoding="utf-8"))
    assert not isinstance(parsed, str), parsed
    return parsed


def section(body: str, heading: str) -> str:
    lines = body.split("\n")
    assert heading in lines, f"no {heading}"
    out: list[str] = []
    for line in lines[lines.index(heading) + 1 :]:
        if line.startswith("## "):
            break
        out.append(line)
    return "\n".join(out)


def items_after(text: str, label: str) -> list[str]:
    """The `- ` items that follow a `label` line, up to the next non-item text."""
    lines = text.split("\n")
    assert label in lines, f"no {label!r} line"
    items: list[str] = []
    for line in lines[lines.index(label) + 1 :]:
        if line.startswith("- "):
            items.append(line[2:])
        elif line.strip() and not line.startswith("  "):
            break
    return items


# --- AC-01: the files ---------------------------------------------------------------------------


@pytest.mark.ac("E09-AC-01")
@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_the_role_file_exists_with_its_name_and_title(row: Row) -> None:
    data, _ = card(row.name)
    assert (data["name"], data["title"]) == (row.name, row.title)


@pytest.mark.ac("E09-AC-01")
def test_the_kits_core_roles_pass_agents_check(tmp_path: Path) -> None:
    shutil.copytree(CORE, tmp_path / ".factory" / "agents" / "core")
    assert [str(p) for p in agents.validate(tmp_path)] == []


# --- AC-02 to AC-04: tools, scopes, hints -------------------------------------------------------


@pytest.mark.ac("E09-AC-02")
@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_the_tools_are_exactly_the_tables(row: Row) -> None:
    data, _ = card(row.name)
    assert data["tools"] == list(row.tools)


@pytest.mark.ac("E09-AC-03")
@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_these_roles_have_no_scope(row: Row) -> None:
    data, _ = card(row.name)
    assert "scope" not in data


@pytest.mark.ac("E09-AC-04")
@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_the_model_hint_is_the_tables(row: Row) -> None:
    data, _ = card(row.name)
    assert (data["model_hint"], data["different_from"]) == (row.hint, "")


# --- AC-05: the role card -----------------------------------------------------------------------


@pytest.mark.ac("E09-AC-05")
@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_the_card_has_the_four_headings(row: Row) -> None:
    _, body = card(row.name)
    headings = [line for line in body.split("\n") if line.startswith("## ")]
    assert headings == ["## Scope", "## Inputs", "## Outputs", "## Hand-off"]


@pytest.mark.ac("E09-AC-05")
@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_scope_has_does_and_must_not_lists(row: Row) -> None:
    _, body = card(row.name)
    scope = section(body, "## Scope")
    assert items_after(scope, "Does:"), "empty Does: list"
    assert items_after(scope, "Must not:"), "empty Must not: list"


@pytest.mark.ac("E09-AC-05")
@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_inputs_and_outputs_say_something(row: Row) -> None:
    _, body = card(row.name)
    for heading in ("## Inputs", "## Outputs"):
        assert section(body, heading).strip(), f"empty {heading}"


@pytest.mark.ac("E09-AC-05")
@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_the_hand_off_names_real_roles(row: Row) -> None:
    _, body = card(row.name)
    named = set(re.findall(r"`([a-z0-9-]+)`", section(body, "## Hand-off")))
    assert named, "the hand-off names no role"
    assert named <= ALL_ROLES | {"human"}, sorted(named - ALL_ROLES)
    assert row.name not in named


# --- AC-06: summaries ---------------------------------------------------------------------------


@pytest.mark.ac("E09-AC-06")
@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_the_summary_is_the_blueprints_one_liner(row: Row) -> None:
    data, _ = card(row.name)
    assert data["summary"] == row.summary


@pytest.mark.ac("E09-AC-06")
@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_the_summary_is_one_sentence(row: Row) -> None:
    assert row.summary.endswith(".")
    assert ". " not in row.summary


# --- AC-07: must-not rules ----------------------------------------------------------------------


@pytest.mark.ac("E09-AC-07")
@pytest.mark.parametrize("row", [r for r in ROWS if r.must_not], ids=lambda r: r.name)
def test_the_blueprints_must_not_rules_are_stated(row: Row) -> None:
    _, body = card(row.name)
    rules = " ".join(items_after(section(body, "## Scope"), "Must not:")).lower()
    for phrase in row.must_not:
        assert phrase in rules, f"{row.name}: no {phrase!r} in its Must not: list"
