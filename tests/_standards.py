"""Builders for standards-pack tests (E11): pack text and small repos that hold packs.

Each builder writes exactly what the E11 spec (AC-01 to AC-03) calls a valid pack, so a test can
change one thing and expect one problem.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

HEADER = "| Rule id | Severity | Rule | Why/example | Source |"
SEPARATOR = "| --- | --- | --- | --- | --- |"
STANDARDS_REL = ".factory/standards"
LEFT = "The gate's format and lint checks enforce layout, spacing and import order.\n"

Row = tuple[str, str, str, str, str]


def _q(value: str) -> str:
    return json.dumps(value)  # a JSON string is a valid TOML basic string


def _list(values: Sequence[str]) -> str:
    return "[" + ", ".join(_q(v) for v in values) + "]"


def rows(prefix: str = "AL", url: str = "https://example.com/alpha/") -> list[Row]:
    """Three valid rows, one of each severity, in ascending id order."""
    return [
        (
            f"{prefix}-001",
            "blocker",
            "Never swallow an error.",
            "Hidden failures.",
            f"[s1]({url}#1)",
        ),
        (
            f"{prefix}-002",
            "major",
            "Name things for what they are.",
            "`names`, not `strs`.",
            f"[s2]({url}#2)",
        ),
        (
            f"{prefix}-003",
            "minor",
            "Public functions have a docstring.",
            "Readers.",
            f"[s3]({url}#3)",
        ),
    ]


def row_line(row: Sequence[str]) -> str:
    return "| " + " | ".join(row) + " |"


def front(
    name: str = "alpha",
    *,
    title: str = "Alpha pack",
    prefix: str = "AL",
    applies_to: Sequence[str] = ("*.py",),
    extra: str = "",
    sources: Sequence[tuple[str, str, str]] = (
        ("Alpha guide", "https://example.com/alpha/", "CC-BY-4.0"),
    ),
    omit: Sequence[str] = (),
) -> str:
    lines = []
    if "name" not in omit:
        lines.append(f"name = {_q(name)}")
    if "title" not in omit:
        lines.append(f"title = {_q(title)}")
    if "prefix" not in omit:
        lines.append(f"prefix = {_q(prefix)}")
    if "applies_to" not in omit:
        lines.append(f"applies_to = {_list(applies_to)}")
    if extra:
        lines.append(extra.rstrip("\n"))
    if "sources" not in omit:
        for title_, url, licence in sources:
            lines += [
                "",
                "[[sources]]",
                f"title = {_q(title_)}",
                f"url = {_q(url)}",
                f"licence = {_q(licence)}",
            ]
    return "\n".join(lines) + "\n"


def pack(
    name: str = "alpha",
    *,
    title: str = "Alpha pack",
    prefix: str = "AL",
    applies_to: Sequence[str] = ("*.py",),
    extra: str = "",
    table: Sequence[Sequence[str]] | None = None,
    heading: str | None = None,
    left: str | None = LEFT,
    header: str = HEADER,
    after_table: str = "",
    front_text: str | None = None,
) -> str:
    """A whole rules.md. `table=None` means `rows(prefix)`; `left=None` drops that section."""
    body_rows = rows(prefix) if table is None else table
    head = front(name, title=title, prefix=prefix, applies_to=applies_to, extra=extra)
    parts = [f"+++\n{head if front_text is None else front_text}+++\n"]
    parts.append(f"\n# {title if heading is None else heading}\n")
    if left is not None:
        parts.append(f"\n## Left to the tools\n\n{left}")
    parts.append(
        "\n## Rules\n\n" + "\n".join([header, SEPARATOR, *map(row_line, body_rows)]) + "\n"
    )
    if after_table:
        parts.append(after_table)
    return "".join(parts)


def write_packs(root: Path, packs: Mapping[str, str], config: str | None = None) -> Path:
    """Write `<root>/.factory/standards/<name>/rules.md` for each pack, and an optional config."""
    for name, text in packs.items():
        path = root / STANDARDS_REL / name / "rules.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    if config is not None:
        path = root / ".agentic" / "config.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(config, encoding="utf-8", newline="\n")
    return root


def pack_rel(name: str) -> str:
    return f"{STANDARDS_REL}/{name}/rules.md"
