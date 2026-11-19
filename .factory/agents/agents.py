"""Software Factory agent roles and test locks (E03, ADRs 0016 to 0018). Standard library only.

    python .factory/agents/agents.py [--root PATH] check
    python .factory/agents/agents.py [--root PATH] lock [--replace] <task> <path>...
    python .factory/agents/agents.py [--root PATH] unlock <task>

Roles are `.factory/agents/**/<name>.md` files with TOML front matter. `_schema.md` documents
the format; files whose names start with `_` aren't roles. Test locks live in
`.agentic/locks/<task>.toml`: one SHA-256 per locked file, taken after line endings are
normalised (ADR 0004). The gate fails when a locked file changes (ADR 0018). This module is
built on its sibling `state.py`, which supplies the root finder, the atomic writer and the
problem type (ADR 0016).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import re
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from state import Problem

STATE_PATH = Path(__file__).resolve().parent.parent / "state" / "state.py"
NEEDS_STATE = f"agents.py needs {STATE_PATH.parent.parent.name}/state/state.py beside it"
AGENTS_REL = ".factory/agents"
TOOLS = ("read", "search", "edit", "write", "run", "web")
HINTS = ("strong", "any", "different-from")
SCOPE_KEYS = ("write", "run")
AGENT_HEADINGS = ("## Scope", "## Inputs", "## Outputs")
ROLE_NAME = re.compile(r"[a-z0-9-]+", re.ASCII)
LOCKS_REL = ".agentic/locks"
LOCK_KEYS = ("task", "locked", "files")
FILE_KEYS = ("path", "sha256")
SHA256 = re.compile(r"[0-9a-f]{64}")


def _load_state() -> ModuleType | None:
    """The sibling state module, loaded under the name the gate uses (ADR 0016)."""
    if not STATE_PATH.is_file():
        return None
    spec = importlib.util.spec_from_file_location("factory_state", STATE_PATH)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules["factory_state"] = module  # dataclasses look the module up by name
    spec.loader.exec_module(module)
    return module


STATE: Any = _load_state()


class Refused(Exception):
    """An action the files don't allow: exit 1 with the message."""


def _state() -> Any:
    if STATE is None:
        raise RuntimeError(NEEDS_STATE)
    return STATE


def _problem(path: str, where: str, message: str) -> Problem:
    problem: Problem = _state().Problem(path, where, message)
    return problem


def lf_sha256(data: bytes) -> str:
    """SHA-256 of the bytes with CRLF and CR turned into LF (ADR 0004)."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")).hexdigest()


def bad_rel_path(path: str) -> str | None:
    """Why `path` isn't a clean repo-relative posix path, or None if it is."""
    if not path:
        return "must not be empty"
    if "\\" in path:
        return "must use / as the separator"
    if path.startswith("/") or re.match(r"[A-Za-z]:", path):
        return "must be relative to the repo root"
    if ".." in PurePosixPath(path).parts:
        return "must not contain .."
    return None


# --- agent files (E03 AC-01 to AC-04) -----------------------------------------------------------


def _text(value: object) -> str | None:
    return None if isinstance(value, str) and value.strip() else "must be a non-empty string"


def _role_name(value: object) -> str | None:
    if not isinstance(value, str) or not ROLE_NAME.fullmatch(value):
        return "must be lowercase letters, digits and hyphens"
    return None


def _hint(value: object) -> str | None:
    return None if value in HINTS else f"must be one of {', '.join(HINTS)}"


def _string(value: object) -> str | None:
    return None if isinstance(value, str) else "must be a string"


def _tools(value: object) -> str | None:
    if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
        return "must be a non-empty list of tool names"
    unknown = [v for v in value if v not in TOOLS]
    if unknown:
        return f"unknown tool {unknown[0]!r}; tools are {', '.join(TOOLS)}"
    if len(set(value)) != len(value):
        return "lists a tool twice"
    return None


def _scope(value: object) -> str | None:
    return None if isinstance(value, dict) else "must be a table ([scope])"


AGENT_SCHEMA = {
    "name": _role_name,
    "title": _text,
    "summary": _text,
    "model_hint": _hint,
    "different_from": _string,
    "tools": _tools,
    "scope": _scope,
}
OPTIONAL_KEYS = frozenset({"scope"})
SCOPE_NEEDS = {"write": ("edit", "write"), "run": ("run",)}


def _check_scope(rel: str, scope: dict[str, Any], tools: object) -> list[Problem]:
    found: list[Problem] = []
    listed = tools if isinstance(tools, list) else []
    for key in sorted(scope):
        where = f"scope.{key}"
        value = scope[key]
        if key not in SCOPE_KEYS:
            found.append(
                _problem(rel, where, f"unknown key; scope keys are {', '.join(SCOPE_KEYS)}")
            )
            continue
        if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
            found.append(_problem(rel, where, "must be a non-empty list of strings"))
            continue
        if not any(tool in listed for tool in SCOPE_NEEDS[key]):
            needs = " or ".join(SCOPE_NEEDS[key])
            found.append(_problem(rel, where, f"needs {needs} in tools"))
        for item in value:
            why = (
                bad_rel_path(item)
                if key == "write"
                else (None if item.strip() else "must not be empty")
            )
            if why is not None:
                found.append(_problem(rel, where, f"{item!r} {why}"))
    return found


def _role_files(root: Path) -> list[Path]:
    folder = root / AGENTS_REL
    if not folder.is_dir():
        return []
    return sorted(
        (p for p in folder.rglob("*.md") if p.is_file() and not p.name.startswith("_")),
        key=lambda p: p.relative_to(folder).as_posix(),
    )


def _agent_problems(root: Path) -> list[Problem]:
    found: list[Problem] = []
    roles: dict[str, tuple[str, dict[str, Any]]] = {}
    for path in _role_files(root):
        rel = path.relative_to(root).as_posix()
        parsed = _state().parse(path.read_text(encoding="utf-8"))
        if isinstance(parsed, str):
            found.append(_problem(rel, _state().FRONT, parsed))
            continue
        data, body = parsed
        for key, rule in AGENT_SCHEMA.items():
            if key not in data:
                if key not in OPTIONAL_KEYS:
                    found.append(_problem(rel, key, "missing"))
                continue
            if (why := rule(data[key])) is not None:
                found.append(_problem(rel, key, why))
        for key in sorted(set(data) - set(AGENT_SCHEMA)):
            found.append(_problem(rel, key, "unknown key"))
        if isinstance(data.get("scope"), dict):
            found += _check_scope(rel, data["scope"], data.get("tools"))
        found += _state()._check_headings(rel, body, AGENT_HEADINGS)

        name = data.get("name")
        if isinstance(name, str) and _role_name(name) is None:
            if name != path.stem:
                found.append(_problem(rel, "name", f"{name!r} does not match the file name"))
            elif name in roles:
                found.append(_problem(rel, "name", f"{name!r} is also used by {roles[name][0]}"))
            else:
                roles[name] = (rel, data)

    for name, (rel, data) in roles.items():
        other = data.get("different_from")
        if not isinstance(other, str):
            continue
        if data.get("model_hint") == "different-from":
            if not other:
                found.append(_problem(rel, "different_from", "required for different-from"))
            elif other == name:
                found.append(_problem(rel, "different_from", "must name another role"))
            elif other not in roles:
                found.append(_problem(rel, "different_from", f"no role named {other!r}"))
        elif other:
            found.append(
                _problem(rel, "different_from", 'must be "" unless model_hint is different-from')
            )
    return found


# --- lock records (E03 AC-09 to AC-11, ADR 0018) ------------------------------------------------


def _record_paths(root: Path) -> list[Path]:
    folder = root / LOCKS_REL
    return sorted(folder.glob("*.toml")) if folder.is_dir() else []


def _load_record(path: Path) -> dict[str, Any] | str:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        return f"invalid TOML: {exc}"


def _check_record(
    root: Path, rel: str, stem: str, data: dict[str, Any], owners: dict[str, str]
) -> list[Problem]:
    found: list[Problem] = []
    for key in sorted(set(data) - set(LOCK_KEYS)):
        found.append(_problem(rel, key, "unknown key"))
    for key in LOCK_KEYS:
        if key not in data:
            found.append(_problem(rel, key, "missing"))

    task = data.get("task")
    if "task" in data:
        if not isinstance(task, str) or not _state().TASK_ID.fullmatch(task):
            found.append(_problem(rel, "task", "must be a task id"))
        elif task != stem:
            found.append(_problem(rel, "task", f"{task!r} does not match the file name {stem!r}"))
        elif not (root / _state().TASKS_REL / f"{task}.md").is_file():
            found.append(_problem(rel, "task", f"no task file for {task}"))

    locked = data.get("locked")
    if "locked" in data and not (isinstance(locked, dt.datetime) and locked.tzinfo is not None):
        found.append(_problem(rel, "locked", "must be a UTC date-time"))

    files = data.get("files")
    if "files" not in data:
        return found
    if not isinstance(files, list) or not files:
        found.append(_problem(rel, "files", "must list at least one [[files]] table"))
        return found
    seen: set[str] = set()
    for index, entry in enumerate(files):
        where = f"files[{index}]"
        if not isinstance(entry, dict):
            found.append(_problem(rel, where, "must be a table"))
            continue
        for key in sorted(set(entry) - set(FILE_KEYS)):
            found.append(_problem(rel, f"{where}.{key}", "unknown key"))
        path = entry.get("path")
        if not isinstance(path, str):
            found.append(_problem(rel, f"{where}.path", "must be a string"))
        elif (why := bad_rel_path(path)) is not None:
            found.append(_problem(rel, f"{where}.path", why))
        elif path in seen:
            found.append(_problem(rel, f"{where}.path", f"{path} is listed twice"))
        elif path in owners:
            found.append(
                _problem(rel, f"{where}.path", f"{path} is already locked by {owners[path]}")
            )
        else:
            seen.add(path)
            owners[path] = stem
        sha = entry.get("sha256")
        if not isinstance(sha, str) or not SHA256.fullmatch(sha):
            found.append(_problem(rel, f"{where}.sha256", "must be 64 lowercase hex digits"))
    return found


def _lock_problems(root: Path) -> list[Problem]:
    found: list[Problem] = []
    owners: dict[str, str] = {}
    for path in _record_paths(root):
        rel = path.relative_to(root).as_posix()
        data = _load_record(path)
        if isinstance(data, str):
            found.append(_problem(rel, "toml", data))
            continue
        found += _check_record(root, rel, path.stem, data, owners)
    return found


def _locked_files(root: Path) -> list[tuple[str, str, str]]:
    """(path, sha256, task) for every well-formed entry in every record."""
    entries: list[tuple[str, str, str]] = []
    for path in _record_paths(root):
        data = _load_record(path)
        if isinstance(data, str) or not isinstance(data.get("files"), list):
            continue
        for entry in data["files"]:
            if isinstance(entry, dict):
                rel, sha = entry.get("path"), entry.get("sha256")
                if isinstance(rel, str) and isinstance(sha, str) and bad_rel_path(rel) is None:
                    entries.append((rel, sha, path.stem))
    return entries


def verify_locks(root: Path) -> list[str]:
    """`<path>: locked by <task>: changed|missing`, one line per broken lock (spec AC-10)."""
    lines: list[str] = []
    for rel, sha, task in sorted(_locked_files(root)):
        target = root / rel
        if not target.is_file():
            lines.append(f"{rel}: locked by {task}: missing")
        elif lf_sha256(target.read_bytes()) != sha:
            lines.append(f"{rel}: locked by {task}: changed")
    return lines


def validate(root: Path) -> list[Problem]:
    """Problems in the agent files and lock records, sorted by path then key (spec AC-03)."""
    found = _agent_problems(root) + _lock_problems(root)
    return sorted(found, key=lambda p: (p.path, p.where))


def _emit_record(task: str, files: list[tuple[str, str]]) -> str:
    toml = _state()._toml
    lines = [f"task = {toml(task)}", f"locked = {toml(_state()._now())}"]
    for rel, sha in files:
        lines += ["", "[[files]]", f"path = {toml(rel)}", f"sha256 = {toml(sha)}"]
    return "\n".join(lines) + "\n"


def lock(root: Path, task: str, paths: Sequence[Path], *, replace: bool = False) -> Path:
    """Write `.agentic/locks/<task>.toml` for `paths` (spec AC-09)."""
    if (
        not _state().TASK_ID.fullmatch(task)
        or not (root / _state().TASKS_REL / f"{task}.md").is_file()
    ):
        raise Refused(f"no task {task!r} in {_state().TASKS_REL}/")
    record = root / LOCKS_REL / f"{task}.toml"
    if record.exists() and not replace:
        raise Refused(f"{task} is already locked; use --replace to lock it again")
    found = validate(root)
    if found:
        raise Refused("invalid lock records:\n" + "\n".join(str(p) for p in found))

    owners = {rel: owner for rel, _, owner in _locked_files(root) if owner != task}
    real_root = root.resolve()
    files: list[tuple[str, str]] = []
    for given in paths:
        target = given.resolve()
        try:
            rel = target.relative_to(real_root).as_posix()
        except ValueError:
            raise Refused(f"{given}: not inside the repo") from None
        if not target.is_file():
            raise Refused(f"{given}: not a file")
        if rel in owners:
            raise Refused(f"{rel}: already locked by {owners[rel]}")
        if rel not in (seen for seen, _ in files):
            files.append((rel, lf_sha256(target.read_bytes())))
    _state()._write(record, _emit_record(task, files))
    return record


def unlock(root: Path, task: str) -> None:
    """Remove `.agentic/locks/<task>.toml` (spec AC-09)."""
    record = root / LOCKS_REL / f"{task}.toml"
    if not record.is_file():
        raise Refused(f"{task} has no lock record in {LOCKS_REL}/")
    record.unlink()


# --- command line -------------------------------------------------------------------------------


def _check(root: Path) -> int:
    found = validate(root)
    for problem in found:
        print(problem)
    if found:
        count = len(found)
        print(f"{count} problem{'s' if count != 1 else ''}", file=sys.stderr)
        return 1
    print("agents OK")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agents.py", description=__doc__.split("\n")[0])
    parser.add_argument(
        "--root", help="repository root (default: the nearest folder holding .agentic/)"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="validate agent files and lock records")
    lock_cmd = commands.add_parser("lock", help="lock test files for a task")
    lock_cmd.add_argument("--replace", action="store_true", help="replace an existing lock")
    lock_cmd.add_argument("task")
    lock_cmd.add_argument("paths", nargs="+")
    unlock_cmd = commands.add_parser("unlock", help="remove a task's lock record")
    unlock_cmd.add_argument("task")
    args = parser.parse_args(argv)

    if STATE is None:
        print(NEEDS_STATE, file=sys.stderr)
        return 2
    cwd = Path.cwd()
    root = Path(args.root).resolve() if args.root else _state().find_root(cwd)
    try:
        if args.command == "check":
            return _check(root)
        if args.command == "lock":
            record = lock(root, args.task, [cwd / p for p in args.paths], replace=args.replace)
            print(f"locked {record.relative_to(root).as_posix()}")
            return 0
        unlock(root, args.task)
        print(f"unlocked {args.task}")
        return 0
    except Refused as exc:
        print(f"agents.py: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
