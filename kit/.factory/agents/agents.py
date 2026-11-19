"""Software Factory agent roles and test locks (E03, ADRs 0016 to 0018). Standard library only.

    python .factory/agents/agents.py [--root PATH] check
    python .factory/agents/agents.py [--root PATH] lock [--replace] <task> <path>...
    python .factory/agents/agents.py [--root PATH] unlock <task>
    python .factory/agents/agents.py [--root PATH] allow <role> <tool> [--path P] [--command C]
    python .factory/agents/agents.py hook claude-code      # PreToolUse JSON on stdin (ADR 0017)

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
import fnmatch
import hashlib
import importlib.util
import json
import os
import re
import shlex
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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


# --- the checker (E03 AC-05) --------------------------------------------------------------------

SHELL_CONTROL = (";", "&", "|", "`", "$(", ">", "<", "\n", "\r")
CHECK_HINT = f"run python {AGENTS_REL}/agents.py check"


class Unusable(Exception):
    """The roles can't be used as asked (unknown role, invalid files, missing input): exit 2."""


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str = ""


def glob_match(pattern: str, path: str) -> bool:
    """`*` and `?` stay within one segment; `**` matches zero or more segments."""

    def match(pat: list[str], parts: list[str]) -> bool:
        if not pat:
            return not parts
        if pat[0] == "**":
            return any(match(pat[1:], parts[i:]) for i in range(len(parts) + 1))
        return bool(parts) and fnmatch.fnmatchcase(parts[0], pat[0]) and match(pat[1:], parts[1:])

    return match(pattern.split("/"), path.split("/"))


def roles(root: Path) -> dict[str, dict[str, Any]]:
    """Every role's front matter by name. Raises Unusable when the agent files are invalid."""
    if validate(root):
        raise Unusable(f"invalid agent files or lock records; {CHECK_HINT}")
    found: dict[str, dict[str, Any]] = {}
    for path in _role_files(root):
        parsed = _state().parse(path.read_text(encoding="utf-8"))
        if not isinstance(parsed, str):
            found[str(parsed[0]["name"])] = parsed[0]
    return found


def _repo_rel(root: Path, path: str) -> str | None:
    """`path` (absolute, or relative to the root) as a repo-relative posix path; None if outside."""
    given = Path(path)
    target = os.path.realpath(given if given.is_absolute() else root / given)
    base = os.path.realpath(root)
    norm_target, norm_base = os.path.normcase(target), os.path.normcase(base)
    if norm_target == norm_base or not norm_target.startswith(norm_base.rstrip(os.sep) + os.sep):
        return None
    return Path(target[len(base.rstrip(os.sep)) + 1 :]).as_posix()


def _locks_by_path(root: Path) -> dict[str, str]:
    return {rel: task for rel, _, task in _locked_files(root)}


def _check_write(root: Path, who: str, data: Mapping[str, Any] | None, path: str) -> Decision:
    rel = _repo_rel(root, path)
    if rel is None:
        return Decision(False, f"{path} is outside the repo")
    owner = _locks_by_path(root).get(rel)
    if owner is not None:
        return Decision(False, f"{rel} is locked by {owner}; locked tests can't be edited")
    globs = (data or {}).get("scope", {}).get("write")
    if globs and not any(glob_match(glob, rel) for glob in globs):
        return Decision(False, f"{who} may only write {', '.join(globs)}, not {rel}")
    return Decision(True)


def _check_run(who: str, data: Mapping[str, Any], command: str) -> Decision:
    prefixes = data.get("scope", {}).get("run")
    if not prefixes:
        return Decision(True)
    if any(mark in command for mark in SHELL_CONTROL):
        return Decision(False, f"{who} may not run commands with shell control characters")
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        return Decision(False, f"{who}: can't read the command: {exc}")
    for prefix in prefixes:
        words = shlex.split(prefix)
        if tokens[: len(words)] == words:
            return Decision(True)
    return Decision(False, f"{who} may only run commands starting with: {'; '.join(prefixes)}")


def allow(
    root: Path,
    role: str | None,
    tool: str,
    *,
    path: str | None = None,
    command: str | None = None,
) -> Decision:
    """May `role` use `tool` here? With role None, only locks apply (spec AC-05 and AC-07)."""
    if tool not in TOOLS:
        raise Unusable(f"unknown tool {tool!r}; tools are {', '.join(TOOLS)}")
    if tool in ("edit", "write") and not path:
        raise Unusable(f"{tool} needs --path")
    if tool == "run" and command is None:
        raise Unusable("run needs --command")
    known = roles(root)
    data: dict[str, Any] | None = None
    if role is not None:
        if role not in known:
            raise Unusable(f"unknown role {role!r}")
        data = known[role]
        if tool not in data["tools"]:
            return Decision(
                False, f"{role} may not use {tool}; its tools are {', '.join(data['tools'])}"
            )
    who = role or "this session"
    if tool in ("edit", "write") and path:
        return _check_write(root, who, data, path)
    if tool == "run" and data is not None and command is not None:
        return _check_run(who, data, command)
    return Decision(True)


# --- the Claude Code hook (E03 AC-06 to AC-08, ADR 0017) -----------------------------------------

CLAUDE_CODE_TOOLS = {
    "Read": "read",
    "Glob": "search",
    "Grep": "search",
    "Edit": "edit",
    "MultiEdit": "edit",
    "NotebookEdit": "edit",
    "Write": "write",
    "Bash": "run",
    "WebFetch": "web",
    "WebSearch": "web",
}
CLAUDE_CODE_PATHS = {
    "Edit": "file_path",
    "MultiEdit": "file_path",
    "Write": "file_path",
    "NotebookEdit": "notebook_path",
}


def _claude_code_decision(payload: object, env: Mapping[str, str]) -> Decision:
    if not isinstance(payload, dict):
        raise Unusable("hook input must be a JSON object")
    name, tool_input = payload.get("tool_name"), payload.get("tool_input")
    if not isinstance(name, str) or not isinstance(tool_input, dict):
        raise Unusable("hook input needs tool_name and tool_input")
    cwd = payload.get("cwd")
    start = Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd()
    root = _state().find_root(start)
    known = roles(root)

    agent_type = payload.get("agent_type")
    role: str | None = None
    if isinstance(agent_type, str) and agent_type in known:
        role = agent_type
    elif env.get("FACTORY_ROLE"):
        role = env["FACTORY_ROLE"]
        if role not in known:
            raise Unusable(f"unknown role {role!r} in FACTORY_ROLE")

    tool = CLAUDE_CODE_TOOLS.get(name)
    if tool is None:
        if role is None:
            return Decision(True)
        return Decision(False, f"{role} may not use {name}: it maps to no factory tool")
    path: str | None = None
    if name in CLAUDE_CODE_PATHS:
        value = tool_input.get(CLAUDE_CODE_PATHS[name])
        if not isinstance(value, str) or not value:
            raise Unusable(f"{name} input has no {CLAUDE_CODE_PATHS[name]}")
        path = value if Path(value).is_absolute() else str(start / value)
    command: str | None = None
    if tool == "run":
        value = tool_input.get("command")
        if not isinstance(value, str):
            raise Unusable("Bash input has no command")
        command = value
    return allow(root, role, tool, path=path, command=command)


def hook_claude_code(stdin: str, env: Mapping[str, str]) -> int:
    """0 to allow; 2 to block, with the reason on stderr. Never any other code (ADR 0017)."""
    try:
        decision = _claude_code_decision(json.loads(stdin), env)
    except BaseException as exc:  # fail closed: any other exit code would let the call through
        print(f"factory hook: blocked: {exc}", file=sys.stderr)
        return 2
    if decision.allowed:
        return 0
    print(f"factory hook: blocked: {decision.reason}", file=sys.stderr)
    return 2


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
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("check", help="validate agent files and lock records")
    lock_cmd = commands.add_parser("lock", help="lock test files for a task")
    lock_cmd.add_argument("--replace", action="store_true", help="replace an existing lock")
    lock_cmd.add_argument("task")
    lock_cmd.add_argument("paths", nargs="+")
    unlock_cmd = commands.add_parser("unlock", help="remove a task's lock record")
    unlock_cmd.add_argument("task")
    allow_cmd = commands.add_parser("allow", help="may a role use a tool? exit 0 yes, 1 no")
    allow_cmd.add_argument("role")
    allow_cmd.add_argument("tool")
    allow_cmd.add_argument("--path", help="the file an edit or write would change")
    allow_cmd.add_argument("--command", help="the shell command a run would execute")
    hook_cmd = commands.add_parser("hook", help="run as a coding tool's hook")
    hook_cmd.add_argument("tool", choices=["claude-code"])
    args = parser.parse_args(argv)

    if args.action == "hook":
        if STATE is None:
            print(f"factory hook: blocked: {NEEDS_STATE}", file=sys.stderr)
            return 2
        return hook_claude_code(sys.stdin.read(), os.environ)
    if STATE is None:
        print(NEEDS_STATE, file=sys.stderr)
        return 2
    cwd = Path.cwd()
    root = Path(args.root).resolve() if args.root else _state().find_root(cwd)
    if args.action == "allow":
        try:
            path = str(cwd / args.path) if args.path else None
            decision = allow(root, args.role, args.tool, path=path, command=args.command)
        except Unusable as exc:
            print(f"agents.py: {exc}", file=sys.stderr)
            return 2
        if decision.allowed:
            print("allowed")
            return 0
        print(f"denied: {decision.reason}")
        return 1
    try:
        if args.action == "check":
            return _check(root)
        if args.action == "lock":
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
