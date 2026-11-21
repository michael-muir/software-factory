"""Software Factory standards packs (E11, ADRs 0033 to 0035). Standard library only.

    python .factory/standards/standards.py [--root PATH] check

A pack is `.factory/standards/<name>/rules.md`: TOML front matter between `+++` lines (name,
title, rule-id prefix, the globs it applies to, optional detect markers and packs it replaces,
and its sources with their licences), then a `# <title>` heading, a `## Left to the tools`
section and a `## Rules` section holding one table: Rule id | Severity | Rule | Why/example |
Source. This module reads and validates every installed pack and the `[standards]` table of
`.agentic/config.toml`. It imports nothing from the kit, so `state.py` and the gate can load it
by path without an import cycle (ADR 0033).
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

STANDARDS_REL = ".factory/standards"
CONFIG_REL = ".agentic/config.toml"
FENCE = "+++"
FRONT = "front matter"
BODY = "body"
HEADER = ("Rule id", "Severity", "Rule", "Why/example", "Source")
SEVERITIES = ("blocker", "major", "minor", "retired")
PREFIX = re.compile(r"[A-Z]{2,5}")
RULE_ID = re.compile(r"[A-Z]{2,5}-\d{3}")
LINK = re.compile(r"\[[^\]]+\]\((https://[^)\s]+)\)")
SEPARATOR_CELL = re.compile(r":?-{3,}:?")
LEFT = "## Left to the tools"
RULES = "## Rules"
REQUIRED = ("name", "title", "prefix", "applies_to", "sources")
OPTIONAL = ("detect", "replaces")
SOURCE_KEYS = ("title", "url", "licence")


@dataclass(frozen=True)
class Problem:
    """One problem: `<file>: <where>: <message>`, as `state.py` reports them."""

    path: str
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.where}: {self.message}"


@dataclass(frozen=True)
class Source:
    title: str
    url: str
    licence: str


@dataclass(frozen=True)
class Rule:
    id: str
    severity: str
    text: str
    why: str
    source: str  # the link's URL
    line: int


@dataclass
class Pack:
    name: str
    title: str
    prefix: str
    applies_to: list[str]
    detect: list[str] = field(default_factory=list)
    replaces: list[str] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    path: str = ""


# --- reading one pack ---------------------------------------------------------------------------


def split(text: str) -> tuple[str, str] | str:
    """(front matter TOML, body), or why the file has no well-formed front matter.

    The same rule as `state.py`'s `split` (ADR 0033): the first line is `+++`, and so is the
    closing one.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0] != FENCE:
        return f"the file must start with a {FENCE} line"
    for index in range(1, len(lines)):
        if lines[index] == FENCE:
            return "\n".join(lines[1:index]) + "\n", "\n".join(lines[index + 1 :])
    return f"no closing {FENCE} line"


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _globs(value: object, *, empty_ok: bool) -> str | None:
    if not isinstance(value, list) or not all(_text(item) for item in value):
        return "must be a list of non-empty strings"
    if not value and not empty_ok:
        return "must not be empty"
    return None


def _check_front(rel: str, data: dict[str, object], folder: str) -> list[Problem]:
    found: list[Problem] = []

    def bad(key: str, message: str) -> None:
        found.append(Problem(rel, f"{FRONT}: {key}", message))

    for key in data:
        if key not in REQUIRED and key not in OPTIONAL:
            bad(key, "unknown key")
    for key in REQUIRED:
        if key not in data:
            bad(key, "missing")
    name, title, prefix = data.get("name"), data.get("title"), data.get("prefix")
    if "name" in data and name != folder:
        bad("name", f"must match the folder ({folder})")
    if "title" in data and not _text(title):
        bad("title", "must be a non-empty string")
    if "prefix" in data and not (isinstance(prefix, str) and PREFIX.fullmatch(prefix)):
        bad("prefix", "must be 2 to 5 capital letters")
    if "applies_to" in data and (why := _globs(data["applies_to"], empty_ok=False)):
        bad("applies_to", why)
    for key in OPTIONAL:
        if key in data and (why := _globs(data[key], empty_ok=True)):
            bad(key, why)
    if "sources" in data:
        found += [Problem(rel, f"{FRONT}: sources", m) for m in _source_problems(data["sources"])]
    return found


def _source_problems(value: object) -> list[str]:
    if not isinstance(value, list) or not value:
        return ["must be at least one [[sources]] table"]
    found: list[str] = []
    for index, source in enumerate(value, start=1):
        if not isinstance(source, dict):
            found.append(f"source {index} must be a table")
            continue
        unknown = sorted(set(source) - set(SOURCE_KEYS))
        if unknown:
            found.append(f"source {index}: unknown key {', '.join(unknown)}")
        for key in SOURCE_KEYS:
            if not _text(source.get(key)):
                found.append(f"source {index}: {key} must be a non-empty string")
        url = source.get("url")
        if _text(url) and not str(url).startswith("https://"):
            found.append(f"source {index}: url must start with https://")
    return found


def _cells(line: str) -> list[str] | None:
    """The cells of a `| a | b |` line, with `\\|` kept as a literal pipe; None if not a row."""
    stripped = line.strip()
    if len(stripped) < 2 or not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    cells: list[str] = []
    current: list[str] = []
    index = 1
    inner = stripped[:-1]
    while index < len(inner):
        char = inner[index]
        if char == "\\" and index + 1 < len(inner) and inner[index + 1] == "|":
            current.append("|")
            index += 2
            continue
        if char == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1
    cells.append("".join(current).strip())
    return cells


def _sections(lines: list[str]) -> dict[str, tuple[int, int]]:
    """Each `## ` heading's (first line index after it, end index), keyed by the heading."""
    starts = [i for i, line in enumerate(lines) if line.startswith("## ")]
    found: dict[str, tuple[int, int]] = {}
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        found.setdefault(lines[start].rstrip(), (start + 1, end))
    return found


def _check_body(rel: str, lines: list[str], title: object) -> list[Problem]:
    found: list[Problem] = []
    first = next((line for line in lines if line.startswith("#")), None)
    if first is None or not isinstance(title, str) or first.rstrip() != f"# {title}":
        found.append(
            Problem(rel, BODY, "the first heading must be `# <title>` from the front matter")
        )
    sections = _sections(lines)
    left = sections.get(LEFT)
    text = " ".join(lines[left[0] : left[1]]).lower() if left else ""
    if left is None:
        found.append(Problem(rel, BODY, f"no `{LEFT}` section"))
    elif "format" not in text or "lint" not in text:
        found.append(Problem(rel, BODY, f"`{LEFT}` must name the gate's format and lint checks"))
    if RULES not in sections:
        found.append(Problem(rel, BODY, f"no `{RULES}` section"))
    return found


def _rules(
    rel: str, lines: list[str], offset: int, prefix: str, sources: list[Source]
) -> tuple[list[Rule], list[Problem]]:
    """The rule table under `## Rules`. `offset` turns a body index into a file line number."""
    span = _sections(lines).get(RULES)
    if span is None:
        return [], []
    found: list[Problem] = []
    rules: list[Rule] = []
    tables = 0
    index = span[0]
    while index < span[1]:
        if _cells(lines[index]) is None:
            index += 1
            continue
        tables += 1
        start = index
        while index < span[1] and _cells(lines[index]) is not None:
            index += 1
        block = list(range(start, index))
        if tables > 1:
            found.append(Problem(rel, f"line {start + offset}", f"`{RULES}` must hold one table"))
            continue
        found += _table(rel, lines, block, offset, prefix, sources, rules)
    if tables == 0:
        found.append(Problem(rel, BODY, f"`{RULES}` has no table"))
    return rules, found


def _table(
    rel: str,
    lines: list[str],
    block: list[int],
    offset: int,
    prefix: str,
    sources: list[Source],
    rules: list[Rule],
) -> list[Problem]:
    found: list[Problem] = []
    header = _cells(lines[block[0]])
    if header is None or tuple(header) != HEADER:
        shown = " | ".join(HEADER)
        found.append(Problem(rel, f"line {block[0] + offset}", f"the header must be | {shown} |"))
        return found
    separator = _cells(lines[block[1]]) if len(block) > 1 else None
    if (
        separator is None
        or len(separator) != len(HEADER)
        or not all(SEPARATOR_CELL.fullmatch(cell) for cell in separator)
    ):
        found.append(Problem(rel, f"line {block[0] + offset + 1}", "no separator line"))
        return found
    seen: set[str] = set()
    previous = ""
    for index in block[2:]:
        number = index + offset
        cells = _cells(lines[index]) or []
        where = f"line {number}"
        if len(cells) != len(HEADER):
            found.append(Problem(rel, where, f"a row has {len(HEADER)} cells, not {len(cells)}"))
            continue
        rule_id, severity, text, why, source = cells
        if not RULE_ID.fullmatch(rule_id) or rule_id.split("-")[0] != prefix:
            found.append(Problem(rel, where, f"rule id {rule_id!r} must be {prefix}-NNN"))
        elif rule_id in seen:
            found.append(Problem(rel, where, f"duplicate rule id {rule_id}"))
        elif rule_id < previous:
            found.append(Problem(rel, where, f"rule id {rule_id} comes after {previous}"))
        if RULE_ID.fullmatch(rule_id):
            seen.add(rule_id)
            previous = max(previous, rule_id)
        if severity not in SEVERITIES:
            found.append(Problem(rel, where, f"severity must be one of {', '.join(SEVERITIES)}"))
        if not text:
            found.append(Problem(rel, where, "the Rule cell is empty"))
        if not why:
            found.append(Problem(rel, where, "the Why/example cell is empty"))
        link = LINK.fullmatch(source)
        url = link.group(1) if link else ""
        if not link:
            found.append(
                Problem(rel, where, "the Source cell must be one [text](https://...) link")
            )
        elif not any(url.startswith(s.url) for s in sources):
            found.append(
                Problem(rel, where, f"source {url} is not under a source in the front matter")
            )
        rules.append(Rule(rule_id, severity, text, why, url, number))
    return found


def read_pack(path: Path, rel: str) -> tuple[Pack | None, list[Problem]]:
    """One pack and its own problems. Never raises on bad input: it's a problem instead."""
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, [Problem(rel, FRONT, f"can't be read as UTF-8 text: {exc}")]
    parts = split(text)
    if isinstance(parts, str):
        return None, [Problem(rel, FRONT, parts)]
    front, body = parts
    try:
        data = tomllib.loads(front)
    except tomllib.TOMLDecodeError as exc:
        return None, [Problem(rel, FRONT, f"invalid TOML: {exc}")]
    found = _check_front(rel, data, path.parent.name)
    lines = body.split("\n")
    offset = front.count("\n") + 3  # body index 0 is the line after the closing fence
    found += _check_body(rel, lines, data.get("title"))
    sources = (
        [
            Source(str(s.get("title", "")), str(s.get("url", "")), str(s.get("licence", "")))
            for s in data.get("sources", [])
            if isinstance(s, dict) and _text(s.get("url"))
        ]
        if isinstance(data.get("sources"), list)
        else []
    )
    prefix = data.get("prefix")
    rules, problems = _rules(rel, lines, offset, prefix if isinstance(prefix, str) else "", sources)
    found += problems

    def strings(key: str) -> list[str]:
        value = data.get(key, [])
        return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []

    pack = Pack(
        name=str(data.get("name", "")),
        title=str(data.get("title", "")),
        prefix=prefix if isinstance(prefix, str) else "",
        applies_to=strings("applies_to"),
        detect=strings("detect"),
        replaces=strings("replaces"),
        sources=sources,
        rules=rules,
        path=rel,
    )
    return pack, found


# --- every pack, and the config -----------------------------------------------------------------


@dataclass
class Packs:
    packs: list[Pack] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)

    def by_name(self) -> dict[str, Pack]:
        return {p.name: p for p in self.packs}


def load(root: Path) -> Packs:
    """Every pack under `.factory/standards/`, in folder order, and their own problems."""
    loaded = Packs()
    folder = root / STANDARDS_REL
    if not folder.is_dir():
        return loaded
    for path in sorted(folder.glob("*/rules.md")):
        rel = f"{STANDARDS_REL}/{path.parent.name}/rules.md"
        pack, found = read_pack(path, rel)
        loaded.problems += found
        if pack is not None:
            loaded.packs.append(pack)
    return loaded


def _across(packs: list[Pack]) -> list[Problem]:
    """Problems that need every pack: unique prefixes, and `replaces` naming real packs."""
    found: list[Problem] = []
    owners: dict[str, str] = {}
    names = {p.name for p in packs}
    for pack in packs:
        if pack.prefix and pack.prefix in owners:
            found.append(
                Problem(
                    pack.path,
                    f"{FRONT}: prefix",
                    f"{pack.prefix} is already {owners[pack.prefix]}'s",
                )
            )
        elif pack.prefix:
            owners[pack.prefix] = pack.name
        for other in pack.replaces:
            if other == pack.name:
                found.append(
                    Problem(pack.path, f"{FRONT}: replaces", "a pack can't replace itself")
                )
            elif other not in names:
                found.append(Problem(pack.path, f"{FRONT}: replaces", f"no pack named {other}"))
    edges = {p.name: [o for o in p.replaces if o in names and o != p.name] for p in packs}
    for pack in packs:
        if _reaches(edges, pack.name, pack.name):
            found.append(Problem(pack.path, f"{FRONT}: replaces", "packs can't replace in a cycle"))
    return found


def _reaches(edges: dict[str, list[str]], start: str, target: str) -> bool:
    """Whether following `replaces` from `start` comes back to `target`."""
    seen: set[str] = set()
    todo = list(edges.get(start, []))
    while todo:
        name = todo.pop()
        if name == target:
            return True
        if name not in seen:
            seen.add(name)
            todo += edges.get(name, [])
    return False


@dataclass(frozen=True)
class Config:
    packs: dict[str, bool]
    ignore: list[str]


def read_config(root: Path) -> tuple[Config, list[Problem]]:
    """The `[standards]` table, with defaults for anything missing (spec AC-09)."""
    path = root / CONFIG_REL
    config = Config({}, [])
    if not path.is_file():
        return config, []
    try:
        data = tomllib.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        return config, [Problem(CONFIG_REL, "config", f"can't be read: {exc}")]
    table = data.get("standards", {})
    if not isinstance(table, dict):
        return config, [Problem(CONFIG_REL, "config: standards", "must be a table")]
    found: list[Problem] = []
    packs = table.get("packs", {})
    if not isinstance(packs, dict) or not all(isinstance(v, bool) for v in packs.values()):
        found.append(
            Problem(CONFIG_REL, "config: standards.packs", "must map pack names to true or false")
        )
        packs = {}
    ignore = table.get("ignore", [])
    if not isinstance(ignore, list) or not all(isinstance(v, str) for v in ignore):
        found.append(Problem(CONFIG_REL, "config: standards.ignore", "must be a list of rule ids"))
        ignore = []
    return Config(dict(packs), list(ignore)), found


def _config_problems(config: Config, packs: list[Pack]) -> list[Problem]:
    names = {p.name for p in packs}
    ids = {r.id for p in packs for r in p.rules}
    found = [
        Problem(CONFIG_REL, "config: standards.packs", f"no installed pack named {name}")
        for name in sorted(config.packs)
        if name not in names
    ]
    found += [
        Problem(CONFIG_REL, "config: standards.ignore", f"no rule {rule} in an installed pack")
        for rule in config.ignore
        if rule not in ids
    ]
    return found


def _order(problem: Problem) -> tuple[str, int, str, str]:
    line = int(problem.where[5:]) if problem.where.startswith("line ") else 0
    return problem.path, line, problem.where, problem.message


def validate(root: Path) -> list[Problem]:
    """Every problem in the installed packs and the `[standards]` config (spec AC-04)."""
    loaded = load(root)
    config, found = read_config(root)
    found += loaded.problems + _across(loaded.packs) + _config_problems(config, loaded.packs)
    return sorted(found, key=_order)


# --- command line -------------------------------------------------------------------------------


def find_root(start: Path) -> Path:
    """The nearest folder at or above `start` that holds .factory/, else `start` itself."""
    start = start.resolve()
    for candidate in (start, *start.parents):
        if (candidate / ".factory").is_dir():
            return candidate
    return start


def _check(root: Path) -> int:
    found = validate(root)
    for problem in found:
        print(problem)
    if found:
        print(f"standards: {len(found)} problem{'s' if len(found) != 1 else ''}")
        return 1
    loaded = load(root)
    rules = sum(len(p.rules) for p in loaded.packs)
    print(f"standards OK: {len(loaded.packs)} packs, {rules} rules")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="standards.py", description="Standards packs (E11).")
    parser.add_argument(
        "--root", help="repository root (default: the nearest folder holding .factory/)"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="validate the installed packs and the [standards] config")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve() if args.root else find_root(Path.cwd())
    return _check(root)


if __name__ == "__main__":
    sys.exit(main())
