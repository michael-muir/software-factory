"""Software Factory state files (E02, ADRs 0014 and 0015). Standard library only.

    python .factory/state/state.py check [PATH]

State lives in `.agentic/` as Markdown files that start with a strict TOML front matter between
`+++` lines: STATE.md (phase, track, active task, blockers), tasks/<id>.md (one per slice) and
handoffs/<time>-<task>.md (context passed between sessions). This module is the one validator
the CLI, the gate and `install.py check` all use.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

AGENTIC = ".agentic"
STATE_REL = f"{AGENTIC}/STATE.md"
TASKS_REL = f"{AGENTIC}/tasks"
HANDOFFS_REL = f"{AGENTIC}/handoffs"
FENCE = "+++"
FRONT = "front matter"

# The E01 seed: a repo still holding it has no state yet, which is valid (spec AC-05).
E01_PLACEHOLDER = (
    "# STATE\n\n_Placeholder. E02 defines this file: current phase, track, active task and "
    "blockers._\n"
)

PHASES = ("spec", "design", "test", "build", "gate", "review", "docs", "ship", "learn")
TRACKS = ("full", "lite", "pass-through")
TASK_STATUSES = ("todo", "in-progress", "in-review", "blocked", "done")
SEVERITIES = ("blocker", "major", "minor")
FINDING_STATUSES = ("open", "fixed", "wont-fix")
TASK_HEADINGS = ("## Goal", "## Acceptance criteria", "## Notes")
HANDOFF_HEADINGS = ("## Done", "## Next", "## Open questions")
FINDING_ID = re.compile(r"F[1-9][0-9]*")


@dataclass(frozen=True)
class Problem:
    path: str  # posix path relative to the repo root
    where: str  # a front-matter key, a heading, or "front matter"
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.where}: {self.message}"


# --- schemas ------------------------------------------------------------------------------------


def _str(value: object) -> str | None:
    return None if isinstance(value, str) else "must be a string"


def _count(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return "must be a whole number, 0 or more"
    return None


def _utc(value: object) -> str | None:
    if isinstance(value, dt.datetime) and value.utcoffset() == dt.timedelta(0):
        return None
    return "must be a UTC date and time, like 2026-11-18T21:30:00Z"


def _strlist(value: object) -> str | None:
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return None
    return "must be a list of strings"


def _one_of(choices: Sequence[str]) -> Callable[[object], str | None]:
    def rule(value: object) -> str | None:
        if isinstance(value, str) and value in choices:
            return None
        return f"must be one of {', '.join(choices)}"

    return rule


def _finding_id(value: object) -> str | None:
    if isinstance(value, str) and FINDING_ID.fullmatch(value):
        return None
    return "must be F1, F2, ..."


Schema = dict[str, Callable[[object], str | None]]

STATE_SCHEMA: Schema = {
    "phase": _one_of(PHASES),
    "track": _one_of(TRACKS),
    "active_task": _str,
    "blockers": _strlist,
    "updated": _utc,
}
TASK_SCHEMA: Schema = {
    "id": _str,
    "title": _str,
    "status": _one_of(TASK_STATUSES),
    "review_round": _count,
    "created": _utc,
    "updated": _utc,
}
FINDING_SCHEMA: Schema = {
    "id": _finding_id,
    "severity": _one_of(SEVERITIES),
    "status": _one_of(FINDING_STATUSES),
    "summary": _str,
}
HANDOFF_SCHEMA: Schema = {
    "task": _str,
    "from": _str,
    "to": _str,
    "created": _utc,
}


# --- parsing ------------------------------------------------------------------------------------


def normalise(text: str) -> str:
    return text.replace("\r\n", "\n")


def split(text: str) -> tuple[str, str] | str:
    """(front matter TOML, body), or why the file has no well-formed front matter."""
    lines = normalise(text).split("\n")
    if not lines or lines[0] != FENCE:
        return f"the file must start with a {FENCE} line"
    for index in range(1, len(lines)):
        if lines[index] == FENCE:
            return "\n".join(lines[1:index]) + "\n", "\n".join(lines[index + 1 :])
    return f"no closing {FENCE} line"


def parse(text: str) -> tuple[dict[str, object], str] | str:
    """(front matter as a dict, body), or what's wrong with the front matter."""
    parts = split(text)
    if isinstance(parts, str):
        return parts
    front, body = parts
    try:
        return tomllib.loads(front), body
    except tomllib.TOMLDecodeError as exc:
        return f"invalid TOML: {exc}"


def _check_fields(
    rel: str, data: dict[str, object], schema: Schema, prefix: str = ""
) -> list[Problem]:
    found: list[Problem] = []
    for key, rule in schema.items():
        if key not in data:
            found.append(Problem(rel, prefix + key, "missing"))
            continue
        problem = rule(data[key])
        if problem:
            found.append(Problem(rel, prefix + key, problem))
    for key in data:
        if key not in schema:
            found.append(Problem(rel, prefix + key, "unknown key"))
    return found


def _check_headings(rel: str, body: str, headings: Sequence[str]) -> list[Problem]:
    lines = {line.rstrip() for line in body.split("\n")}
    return [
        Problem(rel, heading, "missing heading") for heading in headings if heading not in lines
    ]


def _load(root: Path, rel: str) -> tuple[dict[str, object], str] | Problem:
    parsed = parse((root / rel).read_text(encoding="utf-8"))
    if isinstance(parsed, str):
        return Problem(rel, FRONT, parsed)
    return parsed


def _check_findings(rel: str, value: object) -> list[Problem]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        return [Problem(rel, "findings", "must be [[findings]] tables")]
    found: list[Problem] = []
    seen: set[object] = set()
    for index, finding in enumerate(value):
        found += _check_fields(rel, finding, FINDING_SCHEMA, f"findings[{index}].")
        finding_id = finding.get("id")
        if finding_id in seen:
            found.append(Problem(rel, "findings", f"duplicate finding id {finding_id}"))
        seen.add(finding_id)
    return found


# --- validation ---------------------------------------------------------------------------------


def _check_state(root: Path) -> tuple[list[Problem], str]:
    """Problems in STATE.md, and its active task id ("" when none)."""
    path = root / STATE_REL
    if not path.is_file():
        return [], ""
    text = normalise(path.read_text(encoding="utf-8"))
    if text == E01_PLACEHOLDER:
        return [], ""
    if not text.startswith(FENCE + "\n"):
        return [Problem(STATE_REL, FRONT, "no front matter; run state.py init")], ""
    loaded = _load(root, STATE_REL)
    if isinstance(loaded, Problem):
        return [loaded], ""
    data, _body = loaded
    found = _check_fields(STATE_REL, data, STATE_SCHEMA)
    active = data.get("active_task")
    return found, active if isinstance(active, str) else ""


def _check_task(root: Path, rel: str) -> list[Problem]:
    loaded = _load(root, rel)
    if isinstance(loaded, Problem):
        return [loaded]
    data, body = loaded
    findings = data.pop("findings", [])
    found = _check_fields(rel, data, TASK_SCHEMA)
    found += _check_findings(rel, findings)
    stem = Path(rel).stem
    if isinstance(data.get("id"), str) and data["id"] != stem:
        found.append(Problem(rel, "id", f"must match the file name ({stem})"))
    return found + _check_headings(rel, body, TASK_HEADINGS)


def _check_handoff(root: Path, rel: str, tasks: set[str]) -> list[Problem]:
    loaded = _load(root, rel)
    if isinstance(loaded, Problem):
        return [loaded]
    data, body = loaded
    found = _check_fields(rel, data, HANDOFF_SCHEMA)
    task = data.get("task")
    if isinstance(task, str) and task not in tasks:
        found.append(Problem(rel, "task", f"no task file for {task}"))
    return found + _check_headings(rel, body, HANDOFF_HEADINGS)


def _markdown(root: Path, rel_dir: str) -> list[str]:
    directory = root / rel_dir
    if not directory.is_dir():
        return []
    return sorted(f"{rel_dir}/{p.name}" for p in directory.glob("*.md") if p.is_file())


def task_ids(root: Path) -> set[str]:
    return {Path(rel).stem for rel in _markdown(root, TASKS_REL)}


def validate(root: Path) -> list[Problem]:
    """Every problem in the repo's state files, sorted by file then key (spec AC-01, AC-02)."""
    found, active = _check_state(root)
    tasks = task_ids(root)
    if active and active not in tasks:
        found.append(Problem(STATE_REL, "active_task", f"no task file for {active}"))
    for rel in _markdown(root, TASKS_REL):
        found += _check_task(root, rel)
    for rel in _markdown(root, HANDOFFS_REL):
        found += _check_handoff(root, rel, tasks)
    return sorted(found, key=lambda p: (p.path, p.where, p.message))


# --- command line -------------------------------------------------------------------------------


def find_root(start: Path) -> Path:
    """The nearest folder at or above `start` that holds .agentic/, else `start` itself."""
    start = start.resolve()
    for candidate in (start, *start.parents):
        if (candidate / AGENTIC).is_dir():
            return candidate
    return start


def _check(args: argparse.Namespace) -> int:
    root = find_root(Path(args.path))
    found = validate(root)
    for problem in found:
        print(problem)
    if found:
        count = len(found)
        print(f"{count} state problem{'s' if count != 1 else ''}", file=sys.stderr)
        return 1
    print("state OK")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="state.py", description="Software Factory state files.")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="validate STATE.md, task files and handoffs")
    check.add_argument("path", nargs="?", default=".", help="repository root (default: .)")
    check.set_defaults(run=_check)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    run: Callable[[argparse.Namespace], int] = args.run
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
