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
built on its sibling `state.py`, which supplies the front matter parser, field checks, the
atomic writer and the problem type (ADR 0016).
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
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from state import Problem

STATE_PATH = Path(__file__).resolve().parent.parent / "state" / "state.py"
NEEDS_STATE = "agents.py needs .factory/state/state.py beside it"


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


state: Any = _load_state()

AGENTS_REL = ".factory/agents"
LOCKS_REL = ".agentic/locks"
CHECK_HINT = f"run python {AGENTS_REL}/agents.py check"
TOOLS = ("read", "search", "edit", "write", "run", "web")
HINTS = ("strong", "any", "different-from")
SCOPE_KEYS = ("write", "run")
SCOPE_NEEDS = {"write": ("edit", "write"), "run": ("run",)}
AGENT_HEADINGS = ("## Scope", "## Inputs", "## Outputs")
ROLE_NAME = re.compile(r"[a-z0-9-]+", re.ASCII)
SHA256 = re.compile(r"[0-9a-f]{64}")
SHELL_CONTROL = (";", "&", "|", "`", "$(", ">", "<", "\n", "\r")


class Refused(Exception):
    """An action the files don't allow: exit 1."""


class Unusable(Exception):
    """The roles can't be used as asked (unknown role, invalid files, missing input): exit 2."""


def lf_sha256(data: bytes) -> str:
    """SHA-256 of the bytes with CRLF turned into LF: the manifest's hash (ADR 0004)."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


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


def repo_path(root: Path, path: str | Path) -> str | None:
    """`path` (absolute, or relative to the root) as a repo-relative posix path; None if outside."""
    given = Path(path)
    target = Path(os.path.realpath(given if given.is_absolute() else root / given))
    try:
        rel = target.relative_to(os.path.realpath(root))
    except ValueError:
        return None
    return rel.as_posix() if rel.parts else None


# --- field rules ----------------------------------------------------------------------------------


def _text(value: object) -> str | None:
    return None if isinstance(value, str) and value.strip() else "must be a non-empty string"


def _string(value: object) -> str | None:
    return None if isinstance(value, str) else "must be a string"


def _role_name(value: object) -> str | None:
    if isinstance(value, str) and ROLE_NAME.fullmatch(value):
        return None
    return "must be lowercase letters, digits and hyphens"


def _hint(value: object) -> str | None:
    return None if value in HINTS else f"must be one of {', '.join(HINTS)}"


def _tools(value: object) -> str | None:
    if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
        return "must be a non-empty list of tool names"
    unknown = [v for v in value if v not in TOOLS]
    if unknown:
        return f"unknown tool {unknown[0]!r}; tools are {', '.join(TOOLS)}"
    return "lists a tool twice" if len(set(value)) != len(value) else None


def _table(value: object) -> str | None:
    return None if isinstance(value, dict) else "must be a table ([scope])"


def _task_id(value: object) -> str | None:
    return (
        None if isinstance(value, str) and state.TASK_ID.fullmatch(value) else "must be a task id"
    )


def _utc(value: object) -> str | None:
    if isinstance(value, dt.datetime) and value.utcoffset() == dt.timedelta(0):
        return None
    return "must be a UTC date-time"


def _files(value: object) -> str | None:
    if isinstance(value, list) and value:
        return None
    return "must list at least one [[files]] table"


def _rel_path(value: object) -> str | None:
    return bad_rel_path(value) if isinstance(value, str) else "must be a string"


def _sha256(value: object) -> str | None:
    if isinstance(value, str) and SHA256.fullmatch(value):
        return None
    return "must be 64 lowercase hex digits"


AGENT_SCHEMA = {
    "name": _role_name,
    "title": _text,
    "summary": _text,
    "model_hint": _hint,
    "different_from": _string,
    "tools": _tools,
    "scope": _table,
}
LOCK_SCHEMA = {"task": _task_id, "locked": _utc, "files": _files}
LOCKED_FILE_SCHEMA = {"path": _rel_path, "sha256": _sha256}


# --- loading and validation -----------------------------------------------------------------------


@dataclass
class Checked:
    """What validate() read: its problems (iterating a Checked gives them) and the valid parts."""

    problems: list[Problem] = field(default_factory=list)
    roles: dict[str, dict[str, Any]] = field(default_factory=dict)  # name -> front matter
    locks: dict[str, tuple[str, str]] = field(default_factory=dict)  # path -> (sha256, task)

    def __iter__(self) -> Iterator[Problem]:
        return iter(self.problems)

    def __len__(self) -> int:
        return len(self.problems)


def _scope_problems(rel: str, scope: dict[str, Any], tools: object) -> list[Problem]:
    found: list[Problem] = []
    listed = tools if isinstance(tools, list) else []
    for key, value in sorted(scope.items()):
        where = f"scope.{key}"
        if key not in SCOPE_KEYS:
            found.append(
                state.Problem(rel, where, f"unknown key; scope keys are {', '.join(SCOPE_KEYS)}")
            )
            continue
        if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
            found.append(state.Problem(rel, where, "must be a non-empty list of strings"))
            continue
        if not any(tool in listed for tool in SCOPE_NEEDS[key]):
            found.append(
                state.Problem(rel, where, f"needs {' or '.join(SCOPE_NEEDS[key])} in tools")
            )
        for item in value:
            why = (
                bad_rel_path(item)
                if key == "write"
                else None
                if item.strip()
                else "must not be empty"
            )
            if why is not None:
                found.append(state.Problem(rel, where, f"{item!r} {why}"))
    return found


def _role_files(root: Path) -> list[Path]:
    folder = root / AGENTS_REL
    if not folder.is_dir():
        return []
    roles = (p for p in folder.rglob("*.md") if p.is_file() and not p.name.startswith("_"))
    return sorted(roles, key=lambda p: p.relative_to(folder).as_posix())


def _different_from(name: str, data: dict[str, Any], named: Mapping[str, object]) -> str | None:
    other, hint = data.get("different_from"), data.get("model_hint")
    if not isinstance(other, str):
        return None
    if hint != "different-from":
        return 'must be "" unless model_hint is different-from' if other else None
    if not other:
        return "required for different-from"
    if other == name:
        return "must name another role"
    return None if other in named else f"no role named {other!r}"


def _check_roles(root: Path, checked: Checked) -> None:
    named: dict[str, tuple[str, dict[str, Any], list[Problem]]] = {}
    for path in _role_files(root):
        rel = path.relative_to(root).as_posix()
        parsed = state.parse(path.read_text(encoding="utf-8"))
        if isinstance(parsed, str):
            checked.problems.append(state.Problem(rel, state.FRONT, parsed))
            continue
        data, body = parsed
        found = state.check_fields(rel, data, AGENT_SCHEMA, optional={"scope"})
        if isinstance(data.get("scope"), dict):
            found += _scope_problems(rel, data["scope"], data.get("tools"))
        found += state.check_headings(rel, body, AGENT_HEADINGS)
        name = data.get("name")
        if isinstance(name, str) and _role_name(name) is None:
            if name != path.stem:
                found.append(state.Problem(rel, "name", f"{name!r} does not match the file name"))
            elif name in named:
                found.append(
                    state.Problem(rel, "name", f"{name!r} is also used by {named[name][0]}")
                )
            else:
                named[name] = (rel, data, found)
        checked.problems += found

    for name, (rel, data, found) in named.items():
        problem = _different_from(name, data, named)
        if problem is not None:
            checked.problems.append(state.Problem(rel, "different_from", problem))
        elif not found:
            checked.roles[name] = data


def _check_locks(root: Path, checked: Checked) -> None:
    folder = root / LOCKS_REL
    for path in sorted(folder.glob("*.toml")) if folder.is_dir() else []:
        rel, task = path.relative_to(root).as_posix(), path.stem
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            checked.problems.append(state.Problem(rel, "toml", f"invalid TOML: {exc}"))
            continue
        found = state.check_fields(rel, data, LOCK_SCHEMA)
        if _task_id(data.get("task")) is None:
            if data["task"] != task:
                found.append(
                    state.Problem(
                        rel, "task", f"{data['task']!r} does not match the file name {task!r}"
                    )
                )
            elif not (root / state.TASKS_REL / f"{task}.md").is_file():
                found.append(state.Problem(rel, "task", f"no task file for {task}"))
        entries = data["files"] if isinstance(data.get("files"), list) else []
        for index, entry in enumerate(entries):
            where = f"files[{index}]"
            if not isinstance(entry, dict):
                found.append(state.Problem(rel, where, "must be a table"))
                continue
            entry_found = state.check_fields(rel, entry, LOCKED_FILE_SCHEMA, f"{where}.")
            path_ok = _rel_path(entry.get("path")) is None
            if path_ok and entry["path"] in checked.locks:
                owner = checked.locks[entry["path"]][1]
                why = "is listed twice" if owner == task else f"is already locked by {owner}"
                entry_found.append(state.Problem(rel, f"{where}.path", f"{entry['path']} {why}"))
            elif path_ok and _sha256(entry.get("sha256")) is None:
                checked.locks[entry["path"]] = (entry["sha256"], task)
            found += entry_found
        checked.problems += found


# --- skills: the Agent Skills format, read as a YAML subset (E10, ADR 0022) ----------------------

SKILLS_REL = ".factory/skills"
SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*", re.ASCII)
SKILL_FIELDS = ("name", "description", "license", "compatibility", "metadata", "allowed-tools")
YAML_KEY = re.compile(r"([A-Za-z][A-Za-z0-9_-]*):(?: (.*))?")
YAML_SPECIAL = "[]{}&*!|>%@`#"


class _Unsupported(Exception):
    """A line outside the YAML subset of ADR 0022."""


def _yaml_scalar(raw: str) -> str:
    value = raw.strip()
    if not value or value[0] in YAML_SPECIAL or value.startswith("- "):
        raise _Unsupported
    if value[0] == "'":
        if len(value) < 2 or not value.endswith("'"):
            raise _Unsupported
        return value[1:-1].replace("''", "'")
    if value[0] == '"':
        try:
            decoded = json.loads(value)
        except ValueError:
            raise _Unsupported from None
        if not isinstance(decoded, str):
            raise _Unsupported
        return decoded
    return value


def _read_yaml(text: str) -> tuple[dict[str, object], str, list[str]] | str:
    """(fields, body, keys seen twice) from YAML front matter, or why it can't be read."""
    lines = text.removeprefix("\ufeff").replace("\r\n", "\n").split("\n")
    if lines[0].rstrip() != "---":
        return "no YAML front matter: the first line must be ---"
    end = next((i for i in range(1, len(lines)) if lines[i].rstrip() == "---"), None)
    if end is None:
        return "the front matter is never closed with ---"
    data: dict[str, object] = {}
    twice: list[str] = []
    mapping: dict[str, str] | None = None
    for number, line in enumerate(lines[1:end], start=1):
        try:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if line[0] in " \t":
                inner = YAML_KEY.fullmatch(line[2:]) if line.startswith("  ") else None
                if mapping is None or "\t" in line or line[2] == " " or inner is None:
                    raise _Unsupported
                if inner.group(2) is None:
                    raise _Unsupported
                mapping[inner.group(1)] = _yaml_scalar(inner.group(2))
                continue
            match = YAML_KEY.fullmatch(line.rstrip())
            if match is None:
                raise _Unsupported
            key, raw = match.group(1), match.group(2)
            if key in data:
                twice.append(key)
            if raw is None or not raw.strip():
                if key != "metadata":
                    raise _Unsupported
                mapping = {}
                data[key] = mapping
                continue
            mapping = None
            data[key] = _yaml_scalar(raw)
        except _Unsupported:
            return f"unsupported YAML on line {number}"
    return data, "\n".join(lines[end + 1 :]), twice


def read_yaml_front(text: str) -> tuple[dict[str, object], str] | str:
    """A SKILL.md's front matter fields and body, or why they can't be read (ADR 0022)."""
    result = _read_yaml(text)
    if isinstance(result, str):
        return result
    data, body, twice = result
    if twice:
        return f"{twice[0]!r} appears twice"
    return data, body


def _bounded(value: object, low: int, high: int) -> str | None:
    if not isinstance(value, str):
        return "must be a string"
    if not low <= len(value) <= high:
        return f"must be {low} to {high} characters"
    return None


def _skill_name(value: object, folder: str) -> str | None:
    why = _bounded(value, 1, 64)
    if why is not None:
        return why
    if not isinstance(value, str) or not SKILL_NAME.fullmatch(value):
        return "lowercase letters, digits and single hyphens, not at either end"
    return None if value == folder else f"{value!r} does not match its folder {folder!r}"


def _skill_field(key: str, value: object, folder: str) -> str | None:
    """Why a standard field's value breaks the Agent Skills rules, or None (spec AC-02)."""
    if key == "name":
        return _skill_name(value, folder)
    if key == "description":
        return _bounded(value, 1, 1024)
    if key == "compatibility":
        return _bounded(value, 1, 500)
    if key == "metadata":
        ok = isinstance(value, dict) and all(isinstance(v, str) for v in value.values())
        return None if ok else "must be a map of strings to strings"
    if key in ("license", "allowed-tools"):
        return None if isinstance(value, str) else "must be a string"
    return None


def _check_skills(root: Path, checked: Checked) -> None:
    folder = root / SKILLS_REL
    for path in sorted(folder.glob("*/SKILL.md")) if folder.is_dir() else []:
        rel = path.relative_to(root).as_posix()
        result = _read_yaml(path.read_text(encoding="utf-8"))
        if isinstance(result, str):
            checked.problems.append(state.Problem(rel, state.FRONT, result))
            continue
        data, _, twice = result
        found = [state.Problem(rel, key, "appears twice") for key in dict.fromkeys(twice)]
        for key in data:
            if key not in SKILL_FIELDS:
                found.append(state.Problem(rel, key, "not an Agent Skills field"))
        for key in ("name", "description"):
            if key not in data:
                found.append(state.Problem(rel, key, "missing"))
        for key, value in data.items():
            why = _skill_field(key, value, path.parent.name)
            if why is not None:
                found.append(state.Problem(rel, key, why))
        checked.problems += found


def validate(root: Path) -> Checked:
    """Problems in the agent files, lock records and skills, sorted by path then key."""
    checked = Checked()
    _check_roles(root, checked)
    _check_locks(root, checked)
    _check_skills(root, checked)
    checked.problems.sort(key=lambda p: (p.path, p.where))
    return checked


def verify_locks(root: Path) -> list[str]:
    """`<path>: locked by <task>: changed|missing`, one line per broken lock (spec AC-10)."""
    lines: list[str] = []
    for rel, (sha, task) in sorted(validate(root).locks.items()):
        target = root / rel
        if not target.is_file():
            lines.append(f"{rel}: locked by {task}: missing")
        elif lf_sha256(target.read_bytes()) != sha:
            lines.append(f"{rel}: locked by {task}: changed")
    return lines


# --- lock and unlock (spec AC-09) -----------------------------------------------------------------


def lock(root: Path, task: str, paths: Sequence[Path], *, replace: bool = False) -> Path:
    """Write `.agentic/locks/<task>.toml` for `paths`."""
    if _task_id(task) is not None or not (root / state.TASKS_REL / f"{task}.md").is_file():
        raise Refused(f"no task {task!r} in {state.TASKS_REL}/")
    record = root / LOCKS_REL / f"{task}.toml"
    if record.exists() and not replace:
        raise Refused(f"{task} is already locked; use --replace to lock it again")
    checked = validate(root)
    if checked:
        raise Refused("invalid lock records:\n" + "\n".join(map(str, checked)))
    files: dict[str, str] = {}
    for given in paths:
        rel = repo_path(root, given)
        if rel is None:
            raise Refused(f"{given}: not inside the repo")
        if not (root / rel).is_file():
            raise Refused(f"{given}: not a file")
        owner = checked.locks.get(rel, ("", task))[1]
        if owner != task:
            raise Refused(f"{rel}: already locked by {owner}")
        files[rel] = lf_sha256((root / rel).read_bytes())
    now = dt.datetime.now(dt.UTC).replace(microsecond=0)
    lines = [f"task = {state.toml_value(task)}", f"locked = {state.toml_value(now)}"]
    for rel, sha in files.items():
        lines += [
            "",
            "[[files]]",
            f"path = {state.toml_value(rel)}",
            f"sha256 = {state.toml_value(sha)}",
        ]
    state.write(record, "\n".join(lines) + "\n")
    return record


def unlock(root: Path, task: str) -> None:
    record = root / LOCKS_REL / f"{task}.toml"
    if not record.is_file():
        raise Refused(f"{task} has no lock record in {LOCKS_REL}/")
    record.unlink()


# --- the checker (spec AC-05 and AC-07) -----------------------------------------------------------


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


def _decide(
    root: Path,
    checked: Checked,
    role: str | None,
    tool: str,
    path: str | None,
    command: str | None,
) -> Decision:
    if tool not in TOOLS:
        raise Unusable(f"unknown tool {tool!r}; tools are {', '.join(TOOLS)}")
    if tool in ("edit", "write") and not path:
        raise Unusable(f"{tool} needs --path")
    if tool == "run" and command is None:
        raise Unusable("run needs --command")
    if checked:
        raise Unusable(f"invalid agent files or lock records; {CHECK_HINT}")
    if role is not None and role not in checked.roles:
        raise Unusable(f"unknown role {role!r}")
    data = checked.roles.get(role or "", {})
    scope = data.get("scope", {})
    who = role or "this session"

    if role is not None and tool not in data["tools"]:
        return Decision(
            False, f"{role} may not use {tool}; its tools are {', '.join(data['tools'])}"
        )
    if tool in ("edit", "write") and path:
        rel = repo_path(root, path)
        if rel is None:
            return Decision(False, f"{path} is outside the repo")
        if rel in checked.locks:
            return Decision(
                False, f"{rel} is locked by {checked.locks[rel][1]}; locked tests can't be edited"
            )
        globs = scope.get("write")
        if globs and not any(glob_match(glob, rel) for glob in globs):
            return Decision(False, f"{who} may only write {', '.join(globs)}, not {rel}")
    if tool == "run" and command is not None and scope.get("run"):
        prefixes = scope["run"]
        if any(mark in command for mark in SHELL_CONTROL):
            return Decision(False, f"{who} may not run commands with shell control characters")
        try:
            words = shlex.split(command)
        except ValueError as exc:
            return Decision(False, f"{who}: can't read the command: {exc}")
        if not any(words[: len(shlex.split(p))] == shlex.split(p) for p in prefixes):
            return Decision(
                False, f"{who} may only run commands starting with: {'; '.join(prefixes)}"
            )
    return Decision(True)


def allow(
    root: Path, role: str | None, tool: str, *, path: str | None = None, command: str | None = None
) -> Decision:
    """May `role` use `tool` here? With role None, only locks apply."""
    return _decide(root, validate(root), role, tool, path, command)


# --- the Claude Code hook (spec AC-06 to AC-08, ADR 0017) -----------------------------------------

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
# --- the adapters' tables: neutral tool -> each tool's agent-file names (E12, ADR 0023) ----------

CLAUDE_CODE_AGENT_TOOLS = {
    "read": ["Read"],
    "search": ["Glob", "Grep"],
    "edit": ["Edit", "MultiEdit", "NotebookEdit"],
    "write": ["Write"],
    "run": ["Bash"],
    "web": ["WebFetch", "WebSearch"],
}
COPILOT_AGENT_TOOLS = {
    "read": "read",
    "search": "search",
    "edit": "edit",
    "write": "edit",  # Copilot's edit alias covers creating files too
    "run": "execute",
    "web": "web",
}


@dataclass(frozen=True)
class RoleCard:
    source: str  # repo-relative path of the role file
    name: str
    summary: str
    tools: tuple[str, ...]
    body: str


def role_cards(root: Path) -> list[RoleCard]:
    """Every valid role, sorted by name. Raises Unusable when the agent files are invalid."""
    if validate(root).problems:
        raise Unusable(f"invalid agent files, lock records or skills; {CHECK_HINT}")
    cards: list[RoleCard] = []
    for path in _role_files(root):
        parsed = state.parse(path.read_text(encoding="utf-8"))
        if isinstance(parsed, str):  # pragma: no cover - validate() reported it already
            continue
        data, body = parsed
        tools = tuple(str(tool) for tool in data["tools"])
        rel = path.relative_to(root).as_posix()
        cards.append(RoleCard(rel, str(data["name"]), str(data["summary"]), tools, body))
    return sorted(cards, key=lambda card: card.name)


# --- the hooks: one handler for Claude Code, Copilot and Cursor (ADR 0017, ADR 0024) -------------

HOOK_ENTRIES = ("claude-code", "copilot", "cursor")
COPILOT_HOOK_TOOLS = {
    "view": "read",
    "glob": "search",
    "grep": "search",
    "edit": "edit",
    "create": "write",
    "bash": "run",
    "powershell": "run",
    "web_fetch": "web",
}
CURSOR_HOOK_TOOLS = {  # Cursor matches edits as Write; Delete counts as a write
    "Read": "read",
    "Grep": "search",
    "Write": "write",
    "Delete": "write",
    "Shell": "run",
}
HOOK_TABLES = {
    "claude-code": CLAUDE_CODE_TOOLS,
    "copilot": COPILOT_HOOK_TOOLS,
    "cursor": CURSOR_HOOK_TOOLS,
}
CLAUDE_CODE_PATHS = {
    "Edit": "file_path",
    "MultiEdit": "file_path",
    "Write": "file_path",
    "NotebookEdit": "notebook_path",
}
HOOK_PATH_KEYS = {"copilot": ("path",), "cursor": ("file_path", "path")}
HOOK_AGENT_FIELDS = {
    "claude-code": ("agent_type",),
    "copilot": ("agentType", "agent_type"),
    "cursor": (),  # Cursor's payload names no agent: FACTORY_ROLE only
}


def recognise(payload: Mapping[str, object]) -> str | None:
    """Which tool sent a hook payload, by its shape (ADR 0024); None if it's none of them."""
    if "toolName" in payload:
        return "copilot"
    name = payload.get("tool_name")
    if payload.get("hook_event_name") == "PreToolUse" and name in COPILOT_HOOK_TOOLS:
        return "copilot"  # VS Code's form of Copilot's payload
    if "workspace_roots" in payload or "conversation_id" in payload:
        return "cursor"
    if "tool_name" in payload:
        return "claude-code"
    return None


def _hook_start(payload: Mapping[str, object]) -> Path:
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd:
        return Path(cwd)
    roots = payload.get("workspace_roots")
    if isinstance(roots, list) and roots and isinstance(roots[0], str) and roots[0]:
        return Path(roots[0])
    return Path.cwd()


def _hook_call(payload: Mapping[str, object]) -> tuple[str, dict[str, Any]]:
    """The tool name the payload calls, and its arguments."""
    if "toolName" in payload:
        name, args = payload.get("toolName"), payload.get("toolArgs")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError as exc:
                raise Unusable(f"toolArgs is not JSON: {exc}") from None
    else:
        name, args = payload.get("tool_name"), payload.get("tool_input")
    if not isinstance(name, str) or not isinstance(args, dict):
        raise Unusable("hook input needs a tool name and its arguments as an object")
    return name, args


def _hook_role(
    kind: str, payload: Mapping[str, object], checked: Checked, env: Mapping[str, str]
) -> str | None:
    for key in HOOK_AGENT_FIELDS[kind]:
        agent = payload.get(key)
        if isinstance(agent, str) and agent in checked.roles:
            return agent
    role = env.get("FACTORY_ROLE")
    if not role:
        return None
    if role not in checked.roles:
        raise Unusable(f"unknown role {role!r} in FACTORY_ROLE")
    return role


def _hook_decision(kind: str, payload: Mapping[str, object], env: Mapping[str, str]) -> Decision:
    name, args = _hook_call(payload)
    start = _hook_start(payload)
    root = state.find_root(start)
    checked = validate(root)
    if checked:
        raise Unusable(f"invalid agent files or lock records; {CHECK_HINT}")
    role = _hook_role(kind, payload, checked, env)

    tool = HOOK_TABLES[kind].get(name)
    if tool is None:
        if role is None:
            return Decision(True)
        return Decision(False, f"{role} may not use {name}: it maps to no factory tool")
    if kind == "cursor" and name == "Write" and role is not None:
        tools = checked.roles[role]["tools"]
        if "write" not in tools and "edit" in tools:
            tool = "edit"  # Cursor can't tell an edit from a write (ADR 0024)
    path = command = None
    if tool in ("edit", "write"):
        keys = (CLAUDE_CODE_PATHS[name],) if kind == "claude-code" else HOOK_PATH_KEYS[kind]
        value = next((args[k] for k in keys if isinstance(args.get(k), str) and args[k]), None)
        if value is None:
            raise Unusable(f"{name} input has no {' or '.join(keys)}")
        path = str(start / value)
    if tool == "run":
        command = args.get("command")
        if not isinstance(command, str):
            raise Unusable(f"{name} input has no command")
    return _decide(root, checked, role, tool, path, command)


def _answer(kind: str, decision: Decision) -> int:
    """Allow: exit 0, no output. Deny: exit 2, which all three tools honour, in the tool's form."""
    if decision.allowed:
        return 0
    reason = f"factory hook: blocked: {decision.reason}"
    if kind == "copilot":
        print(json.dumps({"permissionDecision": "deny", "permissionDecisionReason": reason}))
    elif kind == "cursor":
        print(json.dumps({"permission": "deny", "user_message": reason, "agent_message": reason}))
    else:
        print(reason, file=sys.stderr)
    return 2


def hook(entry: str, stdin: str | bytes, env: Mapping[str, str]) -> int:
    """Judge one tool call. The payload's shape picks the tool; `entry` answers if it can't.

    Raw stdin is read as UTF-8 whatever the locale, and leading byte order marks are dropped:
    Cursor on Windows pipes the payload through PowerShell, and Windows PowerShell 5.1 adds two.
    """
    kind = entry
    try:
        text = stdin.decode("utf-8") if isinstance(stdin, bytes) else stdin
        payload = json.loads(text.lstrip("\ufeff"))
        if not isinstance(payload, dict):
            raise Unusable("hook input must be a JSON object")
        kind = recognise(payload) or entry
        decision = _hook_decision(kind, payload, env)
    except BaseException as exc:  # fail closed: any other exit code could let the call through
        decision = Decision(False, str(exc) or type(exc).__name__)
    return _answer(kind, decision)


def hook_claude_code(stdin: str, env: Mapping[str, str]) -> int:
    """0 to allow; 2 to block, with the reason on stderr (ADR 0017)."""
    return hook("claude-code", stdin, env)


# --- command line ---------------------------------------------------------------------------------


def _check(root: Path, args: argparse.Namespace) -> int:
    checked = validate(root)
    for problem in checked:
        print(problem)
    if checked:
        print(f"{len(checked)} problem{'s' if len(checked) != 1 else ''}", file=sys.stderr)
        return 1
    print("agents OK")
    return 0


def _lock(root: Path, args: argparse.Namespace) -> int:
    record = lock(root, args.task, [Path.cwd() / p for p in args.paths], replace=args.replace)
    print(f"locked {record.relative_to(root).as_posix()}")
    return 0


def _unlock(root: Path, args: argparse.Namespace) -> int:
    unlock(root, args.task)
    print(f"unlocked {args.task}")
    return 0


def _allow(root: Path, args: argparse.Namespace) -> int:
    path = str(Path.cwd() / args.path) if args.path else None
    decision = allow(root, args.role, args.tool, path=path, command=args.command)
    print("allowed" if decision.allowed else f"denied: {decision.reason}")
    return 0 if decision.allowed else 1


def _hook(root: Path, args: argparse.Namespace) -> int:
    raw = getattr(sys.stdin, "buffer", None)  # bytes, not the locale's decoding of them
    return hook(args.tool, sys.stdin.read() if raw is None else raw.read(), os.environ)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agents.py", description=__doc__.split("\n")[0])
    parser.add_argument(
        "--root", help="repository root (default: the nearest folder holding .agentic/)"
    )
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("check", help="validate agent files and lock records").set_defaults(
        run=_check
    )
    lock_cmd = commands.add_parser("lock", help="lock test files for a task")
    lock_cmd.add_argument("--replace", action="store_true", help="replace an existing lock")
    lock_cmd.add_argument("task")
    lock_cmd.add_argument("paths", nargs="+")
    lock_cmd.set_defaults(run=_lock)
    unlock_cmd = commands.add_parser("unlock", help="remove a task's lock record")
    unlock_cmd.add_argument("task")
    unlock_cmd.set_defaults(run=_unlock)
    allow_cmd = commands.add_parser("allow", help="may a role use a tool? exit 0 yes, 1 no")
    allow_cmd.add_argument("role")
    allow_cmd.add_argument("tool")
    allow_cmd.add_argument("--path", help="the file an edit or write would change")
    allow_cmd.add_argument("--command", help="the shell command a run would execute")
    allow_cmd.set_defaults(run=_allow)
    hook_cmd = commands.add_parser("hook", help="run as a coding tool's hook")
    hook_cmd.add_argument("tool", choices=HOOK_ENTRIES)
    hook_cmd.set_defaults(run=_hook)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if state is None:
        prefix = "factory hook: blocked: " if args.action == "hook" else ""
        print(prefix + NEEDS_STATE, file=sys.stderr)
        return 2
    root = Path(args.root).resolve() if args.root else state.find_root(Path.cwd())
    try:
        code: int = args.run(root, args)
    except Refused as exc:
        print(f"agents.py: {exc}", file=sys.stderr)
        return 1
    except Unusable as exc:
        print(f"agents.py: {exc}", file=sys.stderr)
        return 2
    return code


if __name__ == "__main__":
    sys.exit(main())
