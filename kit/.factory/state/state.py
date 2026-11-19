"""Software Factory state files (E02, ADRs 0014 and 0015). Standard library only.

    python .factory/state/state.py check [PATH]
    python .factory/state/state.py [--root PATH] {init,task,finding,start,block,unblock,handoff} ...

State lives in `.agentic/` as Markdown files that start with a strict TOML front matter between
`+++` lines: STATE.md (phase, track, active task, blockers), tasks/<id>.md (one per slice) and
handoffs/<time>-<task>.md (context passed between sessions). This module is the one validator
the CLI, the gate and `install.py check` all use.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
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


# --- writing (E02 AC-06 to AC-13, ADR 0014) ----------------------------------------------------

TASK_ID = re.compile(r"[A-Za-z0-9._-]+", re.ASCII)
DEFAULT_STATE_BODY = "\nNotes for the next session.\n"
TASK_BODY = "\n" + "\n\n".join(TASK_HEADINGS) + "\n"


class Refused(Exception):
    """An action the state files don't allow: exit 1 with the message."""


class Invalid(Exception):
    """An invalid value given on the command line: exit 2 with the message."""


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(microsecond=0)


def _toml(value: object) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")
    if isinstance(value, dt.datetime):
        return value.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, list):
        return "[" + ", ".join(_toml(item) for item in value) + "]"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    raise TypeError(f"cannot write {value!r} to a state file")


def emit(data: dict[str, object], schema: Schema) -> str:
    """The front matter block, keys in schema order, then any [[findings]] tables."""
    lines = [f"{key} = {_toml(data[key])}" for key in schema]
    findings = data.get("findings", [])
    for finding in findings if isinstance(findings, list) else []:
        lines += ["", "[[findings]]"]
        lines += [f"{key} = {_toml(finding[key])}" for key in FINDING_SCHEMA]
    return f"{FENCE}\n" + "\n".join(lines) + f"\n{FENCE}\n"


def _write(path: Path, text: str) -> None:
    """Atomic: a temp file beside the target, then a rename. LF endings only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".state-tmp")
    temp.write_bytes(normalise(text).encode("utf-8"))
    try:
        os.replace(temp, path)
    except OSError:
        temp.unlink(missing_ok=True)
        raise


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _require_valid(root: Path) -> None:
    found = validate(root)
    if found:
        for problem in found:
            print(problem)
        raise Refused("the state files are invalid; fix them first (state.py check)")


def _read(path: Path) -> tuple[dict[str, object], str]:
    parsed = parse(path.read_text(encoding="utf-8"))
    if isinstance(parsed, str):  # pragma: no cover - callers validate first
        raise Refused(f"{path.name}: {parsed}")
    return parsed


def _state(root: Path) -> tuple[dict[str, object], str]:
    path = root / STATE_REL
    if not path.is_file() or normalise(path.read_text(encoding="utf-8")) == E01_PLACEHOLDER:
        raise Refused("no STATE.md yet; run state.py init")
    return _read(path)


def _task_path(root: Path, task_id: str) -> Path:
    path = root / TASKS_REL / f"{task_id}.md"
    if not TASK_ID.fullmatch(task_id) or not path.is_file():
        raise Refused(f"no task {task_id!r} in {TASKS_REL}/")
    return path


def _save_state(root: Path, data: dict[str, object], body: str) -> None:
    data["updated"] = _now()
    _write(root / STATE_REL, emit(data, STATE_SCHEMA) + body)


def _save_task(path: Path, data: dict[str, object], body: str) -> None:
    data["updated"] = _now()
    _write(path, emit(data, TASK_SCHEMA) + body)


def _init(root: Path, args: argparse.Namespace) -> int:
    path = root / STATE_REL
    body = DEFAULT_STATE_BODY
    if path.is_file():
        text = normalise(path.read_text(encoding="utf-8"))
        if text.startswith(FENCE + "\n"):
            if not args.force:
                raise Refused(f"{STATE_REL} already exists; use --force to replace it")
            parsed = parse(text)
            body = parsed[1] if not isinstance(parsed, str) else DEFAULT_STATE_BODY
        elif text != E01_PLACEHOLDER:
            body = "\n" + text
    data: dict[str, object] = {"phase": "spec", "track": "full", "active_task": "", "blockers": []}
    _save_state(root, data, body)
    print(f"wrote {STATE_REL}")
    return 0


def _task_new(root: Path, args: argparse.Namespace) -> int:
    _require_valid(root)
    task_id: str = args.id
    if not TASK_ID.fullmatch(task_id):
        raise Refused(f"task id {task_id!r} must use only A-Z, a-z, 0-9, '.', '_' and '-'")
    path = root / TASKS_REL / f"{task_id}.md"
    if path.exists():
        raise Refused(f"task {task_id} already exists ({_rel(path, root)})")
    now = _now()
    data: dict[str, object] = {
        "id": task_id,
        "title": args.title,
        "status": "todo",
        "review_round": 0,
        "created": now,
        "updated": now,
    }
    _write(path, emit(data, TASK_SCHEMA) + TASK_BODY)
    print(f"created {_rel(path, root)}")
    return 0


def _task_set(root: Path, args: argparse.Namespace) -> int:
    if args.status is None and args.round is None:
        raise Invalid("give --status and/or --round")
    if args.round is not None and args.round < 0:
        raise Invalid("--round must be 0 or more")
    _require_valid(root)
    path = _task_path(root, args.id)
    data, body = _read(path)
    if args.status is not None:
        data["status"] = args.status
    if args.round is not None:
        data["review_round"] = args.round
    _save_task(path, data, body)
    print(f"updated {_rel(path, root)}")
    return 0


def _findings_of(data: dict[str, object]) -> list[dict[str, object]]:
    value = data.get("findings", [])
    return value if isinstance(value, list) else []


def _finding_add(root: Path, args: argparse.Namespace) -> int:
    _require_valid(root)
    path = _task_path(root, args.id)
    data, body = _read(path)
    findings = _findings_of(data)
    numbers = [int(str(f["id"])[1:]) for f in findings]
    finding_id = f"F{max(numbers, default=0) + 1}"
    findings.append(
        {"id": finding_id, "severity": args.severity, "status": "open", "summary": args.summary}
    )
    data["findings"] = findings
    _save_task(path, data, body)
    print(f"added {finding_id} to {_rel(path, root)}")
    return 0


def _finding_set(root: Path, args: argparse.Namespace) -> int:
    _require_valid(root)
    path = _task_path(root, args.id)
    data, body = _read(path)
    matches = [f for f in _findings_of(data) if f.get("id") == args.finding]
    if not matches:
        raise Refused(f"task {args.id} has no finding {args.finding}")
    matches[0]["status"] = args.status
    _save_task(path, data, body)
    print(f"updated {args.finding} in {_rel(path, root)}")
    return 0


def _start(root: Path, args: argparse.Namespace) -> int:
    _require_valid(root)
    state, state_body = _state(root)
    path = _task_path(root, args.id)
    task, task_body = _read(path)
    task["status"] = "in-progress"
    _save_task(path, task, task_body)
    state["active_task"] = args.id
    if args.phase is not None:
        state["phase"] = args.phase
    if args.track is not None:
        state["track"] = args.track
    _save_state(root, state, state_body)
    print(f"started {args.id}")
    return 0


def _blockers(data: dict[str, object]) -> list[str]:
    value = data.get("blockers", [])
    return [str(item) for item in value] if isinstance(value, list) else []


def _block(root: Path, args: argparse.Namespace) -> int:
    _require_valid(root)
    data, body = _state(root)
    blockers = _blockers(data)
    if args.reason not in blockers:
        blockers.append(args.reason)
    data["blockers"] = blockers
    _save_state(root, data, body)
    print(f"blocked: {args.reason}")
    return 0


def _unblock(root: Path, args: argparse.Namespace) -> int:
    _require_valid(root)
    data, body = _state(root)
    blockers = _blockers(data)
    if args.reason is None:
        blockers = []
    elif args.reason in blockers:
        blockers.remove(args.reason)
    else:
        raise Refused(f"no blocker {args.reason!r}")
    data["blockers"] = blockers
    _save_state(root, data, body)
    print("unblocked")
    return 0


def _handoff_path(root: Path, task_id: str, now: dt.datetime) -> Path:
    stem = f"{now.astimezone(dt.UTC):%Y%m%dT%H%M%SZ}-{task_id}"
    directory = root / HANDOFFS_REL
    path, number = directory / f"{stem}.md", 1
    while path.exists():
        number += 1
        path = directory / f"{stem}-{number}.md"
    return path


def _handoff(root: Path, args: argparse.Namespace) -> int:
    _require_valid(root)
    _task_path(root, args.task)
    if args.body_file is not None:
        text = Path(args.body_file).read_text(encoding="utf-8")
    else:
        text = sys.stdin.read()
    text = normalise(text)
    missing = _check_headings("handoff body", text, HANDOFF_HEADINGS)
    if missing:
        raise Invalid("; ".join(f"{p.where}: {p.message}" for p in missing))
    now = _now()
    data: dict[str, object] = {
        "task": args.task,
        "from": args.sender,
        "to": args.to,
        "created": now,
    }
    path = _handoff_path(root, args.task, now)
    _write(path, emit(data, HANDOFF_SCHEMA) + "\n" + text)
    print(f"wrote {_rel(path, root)}")
    return 0


# --- resume (E02 AC-12) -------------------------------------------------------------------------


def _jsonable(value: object) -> object:
    if isinstance(value, dt.datetime):
        return _toml(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _handoff_order(rel: str, front: dict[str, object]) -> tuple[str, int, str]:
    """Newest last: by created time, then the -N suffix of handoffs in the same second."""
    stem = Path(rel).stem
    rest = stem[len("YYYYMMDDTHHMMSSZ-") :]
    task = str(front.get("task", ""))
    number = 1
    tail = rest[len(task) + 1 :] if rest.startswith(task + "-") else ""
    if tail.isdigit():
        number = int(tail)
    return _toml(front.get("created")) if "created" in front else "", number, rel


def _latest_handoff(root: Path, task_id: str) -> dict[str, object] | None:
    candidates: list[tuple[tuple[str, int, str], dict[str, object]]] = []
    for rel in _markdown(root, HANDOFFS_REL):
        front, body = _read(root / rel)
        if front.get("task") == task_id:
            candidates.append(
                (_handoff_order(rel, front), {"path": rel, "front": front, "body": body})
            )
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def resume(root: Path) -> dict[str, object]:
    """Everything a new session needs, read from the state files alone."""
    _require_valid(root)
    front, body = _state(root)
    result: dict[str, object] = {
        "state": {"path": STATE_REL, "front": front, "body": body},
        "task": None,
        "handoff": None,
        "pending": [],
    }
    active = str(front.get("active_task", ""))
    if active:
        path = root / TASKS_REL / f"{active}.md"
        task_front, task_body = _read(path)
        result["task"] = {
            "path": _rel(path, root),
            "front": task_front,
            "open_findings": [f for f in _findings_of(task_front) if f.get("status") == "open"],
            "body": task_body,
        }
        result["handoff"] = _latest_handoff(root, active)
    else:
        pending = []
        for rel in _markdown(root, TASKS_REL):
            task_front, _ = _read(root / rel)
            if task_front.get("status") != "done":
                pending.append(
                    {k: task_front.get(k) for k in ("id", "title", "status", "review_round")}
                )
        result["pending"] = pending
    return result


def _section(title: str) -> str:
    return f"--- {title} " + "-" * max(3, 72 - len(title))


def render(data: dict[str, object]) -> str:
    state = data["state"]
    assert isinstance(state, dict)
    front = state["front"]
    blockers = ", ".join(front["blockers"]) or "none"
    lines = [
        f"Phase: {front['phase']}   Track: {front['track']}   Updated: {_toml(front['updated'])}",
        f"Blockers: {blockers}",
    ]
    task = data["task"]
    if not isinstance(task, dict):
        lines.append("No active task. Unfinished tasks:")
        pending = data["pending"]
        assert isinstance(pending, list)
        lines += [f"  {t['id']}  [{t['status']}]  {t['title']}" for t in pending] or ["  (none)"]
        return "\n".join(lines) + "\n"
    tf = task["front"]
    lines += [
        f"Active task: {tf['id']}: {tf['title']} ({task['path']})",
        f"Status: {tf['status']}   Review round: {tf['review_round']}",
        "Open findings:",
    ]
    findings = task["open_findings"]
    lines += [f"  {f['id']} [{f['severity']}] {f['summary']}" for f in findings] or ["  (none)"]
    lines += [_section("task notes"), task["body"].strip("\n")]
    handoff = data["handoff"]
    if isinstance(handoff, dict):
        hf = handoff["front"]
        to = hf["to"] or "anyone"
        title = f"latest handoff: {handoff['path']} (from {hf['from']} to {to})"
        lines += [_section(title), handoff["body"].strip("\n")]
    else:
        lines.append("No handoff for this task yet.")
    return "\n".join(lines) + "\n"


def _resume(root: Path, args: argparse.Namespace) -> int:
    data = resume(root)
    print(
        json.dumps(_jsonable(data), indent=2) if args.json else render(data),
        end="\n" if args.json else "",
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="state.py", description="Software Factory state files.")
    parser.add_argument(
        "--root", help="repository root (default: the nearest folder holding .agentic/)"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", help="validate STATE.md, task files and handoffs")
    check.add_argument("path", nargs="?", default=None, help="repository root (default: .)")
    check.set_defaults(run=None)

    init = commands.add_parser("init", help="write a fresh STATE.md")
    init.add_argument("--force", action="store_true", help="replace an existing STATE.md")
    init.set_defaults(run=_init)

    task = commands.add_parser("task", help="create or update a task file").add_subparsers(
        dest="task_command", required=True
    )
    new = task.add_parser("new", help="create tasks/<id>.md")
    new.add_argument("id")
    new.add_argument("title")
    new.set_defaults(run=_task_new)
    set_ = task.add_parser("set", help="set a task's status and/or review round")
    set_.add_argument("id")
    set_.add_argument("--status", choices=TASK_STATUSES)
    set_.add_argument("--round", type=int)
    set_.set_defaults(run=_task_set)

    finding = commands.add_parser("finding", help="record review findings").add_subparsers(
        dest="finding_command", required=True
    )
    add = finding.add_parser("add", help="add an open finding to a task")
    add.add_argument("id")
    add.add_argument("--severity", choices=SEVERITIES, required=True)
    add.add_argument("summary")
    add.set_defaults(run=_finding_add)
    fset = finding.add_parser("set", help="change a finding's status")
    fset.add_argument("id")
    fset.add_argument("finding")
    fset.add_argument("--status", choices=FINDING_STATUSES, required=True)
    fset.set_defaults(run=_finding_set)

    start = commands.add_parser("start", help="make a task the active one")
    start.add_argument("id")
    start.add_argument("--phase", choices=PHASES)
    start.add_argument("--track", choices=TRACKS)
    start.set_defaults(run=_start)

    block = commands.add_parser("block", help="add a blocker")
    block.add_argument("reason")
    block.set_defaults(run=_block)
    unblock = commands.add_parser("unblock", help="remove a blocker, or all of them")
    unblock.add_argument("reason", nargs="?")
    unblock.set_defaults(run=_unblock)

    handoff = commands.add_parser("handoff", help="write a handoff note for a task")
    handoff.add_argument("task")
    handoff.add_argument("--from", dest="sender", required=True, help="who is handing off")
    handoff.add_argument("--to", default="", help="who should pick it up (default: anyone)")
    handoff.add_argument("--body-file", help="the note's body (default: read stdin)")
    handoff.set_defaults(run=_handoff)

    resume_ = commands.add_parser("resume", help="print what a new session needs to carry on")
    resume_.add_argument("--json", action="store_true", help="print it as JSON")
    resume_.set_defaults(run=_resume)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "check":
        args.path = args.path if args.path is not None else (args.root or ".")
        return _check(args)
    root = find_root(Path(args.root or "."))
    run: Callable[[Path, argparse.Namespace], int] = args.run
    try:
        return run(root, args)
    except Refused as exc:
        print(f"state.py: {exc}", file=sys.stderr)
        return 1
    except Invalid as exc:
        print(f"state.py: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"state.py: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
