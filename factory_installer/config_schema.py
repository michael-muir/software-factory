"""Schema, defaults and validation for `.agentic/config.toml` (E01: AC-07, AC-18).

Standard library only: TOML is read with `tomllib` elsewhere and rendered here as text,
because the standard library cannot write TOML.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

Check = Callable[[Any], str | None]

_KIND_NAMES = {
    "int": "an integer",
    "number": "a number",
    "str": "a string",
    "bool": "a boolean",
    "strlist": "a list of strings",
    "booltable": "a table of true or false values",
}


@dataclass(frozen=True)
class Field:
    kind: str  # "int" | "number" | "str" | "bool" | "strlist" | "booltable"
    default: object
    check: Check | None = None
    comment: str = ""


@dataclass(frozen=True)
class Issue:
    key: str
    reason: str


@dataclass
class ValidationResult:
    errors: list[Issue] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def _one_of(*choices: str) -> Check:
    def check(value: Any) -> str | None:
        if value in choices:
            return None
        return "must be one of " + ", ".join(f'"{c}"' for c in choices)

    return check


def _between(low: float, high: float, *, low_open: bool = False) -> Check:
    def check(value: Any) -> str | None:
        ok_low = value > low if low_open else value >= low
        if ok_low and value <= high:
            return None
        left = "greater than" if low_open else "at least"
        return f"must be {left} {low:g} and at most {high:g}"

    return check


def _positive(value: Any) -> str | None:
    return None if value > 0 else "must be greater than 0"


def _at_least(low: float) -> Check:
    def check(value: Any) -> str | None:
        return None if value >= low else f"must be at least {low:g}"

    return check


def _equals_one(value: Any) -> str | None:
    return None if value == 1 else "must be 1"


def _not_empty(value: Any) -> str | None:
    return None if value.strip() else "must not be empty"


def _no_empty_items(value: Any) -> str | None:
    return None if all(item.strip() for item in value) else "must not contain empty names"


# The gate's check names, in its fixed order (mirrors gate.CHECK_ORDER).
CHECK_NAMES = ("format", "lint", "types", "build", "tests", "coverage", "mutation")


def _check_names(value: Any) -> str | None:
    unknown = [item for item in value if item not in CHECK_NAMES]
    if unknown:
        return f"unknown check(s) {', '.join(unknown)}; valid: {', '.join(CHECK_NAMES)}"
    return None


ADAPTER_TOOLS = ("claude-code", "copilot", "cursor")  # mirrors build.TOOLS (E12)


def _adapter_tools(value: Any) -> str | None:
    unknown = [item for item in value if item not in ADAPTER_TOOLS]
    if unknown:
        return f"unknown tool(s) {', '.join(unknown)}; valid: {', '.join(ADAPTER_TOOLS)}"
    return None


RULE_ID = re.compile(r"[A-Z]{2,5}-\d{3}")


def _pack_names(value: Any) -> str | None:
    return None if all(name.strip() for name in value) else "must not contain empty pack names"


def _rule_ids(value: Any) -> str | None:
    bad = [item for item in value if not RULE_ID.fullmatch(item)]
    return f"not rule ids (like PY-001): {', '.join(bad)}" if bad else None


def _command(value: Any) -> str | None:
    if not value:
        return "must not be empty"
    return None if all(item.strip() for item in value) else "must not contain empty items"


CHECKPOINTS = ("spec", "design", "merge")  # mirrors pipeline.CHECKPOINTS (E13)
PLACEHOLDERS = ("{role}", "{allowed_tools}", "{prompt}")  # mirrors pipeline.PLACEHOLDERS
AGENT_COMMAND = (  # mirrors pipeline.PIPELINE_DEFAULTS["agent_command"] (E13, ADR 0042)
    "claude",
    "-p",
    "--agent",
    "{role}",
    "--output-format",
    "json",
    "--permission-mode",
    "acceptEdits",
    "--permission-prompts",
    "none",
    "--allowedTools",
    "{allowed_tools}",
    "--",
    "{prompt}",
)
_PLACEHOLDER = re.compile(r"\{[^{}]*\}")


def _checkpoints(value: Any) -> str | None:
    unknown = [item for item in value if item not in CHECKPOINTS]
    if unknown:
        return f"unknown checkpoint(s) {', '.join(unknown)}; valid: {', '.join(CHECKPOINTS)}"
    if len(set(value)) != len(value):
        return "must not repeat a checkpoint"
    if "spec" not in value or "merge" not in value:
        return 'must include "spec" and "merge"'
    return None


def _agent_command(value: Any) -> str | None:
    if not value:
        return "must not be empty"
    if not all(item.strip() for item in value):
        return "must not contain empty items"
    for item in value:
        if _PLACEHOLDER.search(item) and item not in PLACEHOLDERS:
            return f"{item!r}: a placeholder must be a whole item, one of {', '.join(PLACEHOLDERS)}"
    if value.count("{prompt}") != 1:
        return "must contain {prompt} exactly once"
    return None


TOP_LEVEL: dict[str, Field] = {
    "schema_version": Field("int", 1, _equals_one),
}

SECTIONS: dict[str, dict[str, Field]] = {
    "hosting": {
        "mode": Field("str", "local", _one_of("local", "cloud"), '"local" | "cloud"'),
    },
    "budgets": {
        "per_job_usd": Field("number", 15, _positive, "> 0 and <= per_day_usd"),
        "per_day_usd": Field("number", 120, _positive, "> 0"),
        "warn_at": Field("number", 0.8, _positive, "fraction of budget; > 0 and <= halt_at"),
        "halt_at": Field("number", 1.0, _between(0, 1, low_open=True), "fraction of budget; <= 1"),
    },
    "review": {
        "max_rounds": Field("int", 3, _between(1, 10), "1 to 10"),
    },
    "gates": {
        "coverage_threshold": Field("number", 0.8, _between(0, 1), "0 to 1"),
        "mutation_threshold": Field("number", 0.6, _between(0, 1), "0 to 1"),
        "mutation_scope": Field(
            "str", "changed-lines", _one_of("changed-lines", "all"), '"changed-lines" | "all"'
        ),
        "profiles": Field("strlist", [], _no_empty_items, "empty = auto-detect"),
        "base_ref": Field("str", "main", _not_empty, "branch that changed files are measured from"),
        "commit_checks": Field(
            "strlist", ["format", "lint", "types"], _check_names, "checks the pre-commit hook runs"
        ),
        "python_command": Field(
            "strlist", ["python"], _command, 'runs the gate, e.g. ["uv", "run", "python"]'
        ),
    },
    "models": {
        "cross_model_vendor": Field("str", "openai", _not_empty),
    },
    "adapters": {
        "tools": Field(
            "strlist",
            list(ADAPTER_TOOLS),
            _adapter_tools,
            "the coding tools build.py writes files for",
        ),
    },
    "runner": {
        "max_turns": Field("int", 50, _between(1, 10000), "commands per job; 1 to 10000"),
        "job_timeout_minutes": Field("number", 120, _positive, "per job; > 0"),
        "max_parallel": Field("int", 2, _between(1, 64), "jobs at once per daemon; 1 to 64"),
        "worktree_root": Field("str", "", None, 'empty = "../<repo>.worktrees"'),
    },
    "pipeline": {
        "checkpoints": Field(
            "strlist",
            ["spec", "merge"],
            _checkpoints,
            'human checkpoints; "spec" and "merge" required, "design" optional',
        ),
        "agent_command": Field(
            "strlist",
            list(AGENT_COMMAND),
            _agent_command,
            "a role session; {role}, {allowed_tools}, {prompt} are whole items",
        ),
        "forge": Field("str", "github", _one_of("github", "git"), '"github" | "git"'),
        "gate_retries": Field("int", 2, _between(0, 5), "Debugger sessions on a red gate; 0 to 5"),
    },
    "standards": {
        "packs": Field(
            "booltable", {}, _pack_names, "pack name = true | false; empty = every pack on"
        ),
        "ignore": Field("strlist", [], _rule_ids, 'rule ids switched off here, e.g. ["PY-007"]'),
    },
    "jobs": {
        "lease_minutes": Field("number", 10, _positive, "a session's lease on a job; > 0"),
        "daemon_timeout_seconds": Field(
            "number", 60, _at_least(5), "a daemon is dead after this long silent; >= 5"
        ),
    },
    "telemetry": {
        "enabled": Field("bool", False),
    },
}


def _type_ok(kind: str, value: Any) -> bool:
    if isinstance(value, bool):
        return kind == "bool"
    if kind == "int":
        return isinstance(value, int)
    if kind == "number":
        return isinstance(value, int | float)
    if kind == "str":
        return isinstance(value, str)
    if kind == "strlist":
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    if kind == "booltable":
        return isinstance(value, dict) and all(isinstance(item, bool) for item in value.values())
    return False


def _type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "table"
    if isinstance(value, list):
        return "array"
    return type(value).__name__


def _check_field(key: str, spec: Field, value: Any, result: ValidationResult) -> bool:
    if not _type_ok(spec.kind, value):
        result.errors.append(
            Issue(key, f"expected {_KIND_NAMES[spec.kind]}, got {_type_name(value)}")
        )
        return False
    if spec.check is not None:
        reason = spec.check(value)
        if reason is not None:
            result.errors.append(Issue(key, reason))
            return False
    return True


def validate(data: Mapping[str, Any]) -> ValidationResult:
    """Validate parsed config data. Missing keys are allowed and listed in `missing`."""
    result = ValidationResult()
    valid: dict[str, Any] = {}

    for key, value in data.items():
        if key in TOP_LEVEL:
            if _check_field(key, TOP_LEVEL[key], value, result):
                valid[key] = value
        elif key in SECTIONS:
            if not isinstance(value, dict):
                result.errors.append(Issue(key, f"expected a table, got {_type_name(value)}"))
                continue
            fields = SECTIONS[key]
            for sub_key, sub_value in value.items():
                dotted = f"{key}.{sub_key}"
                if sub_key not in fields:
                    result.errors.append(Issue(dotted, "unknown key"))
                elif _check_field(dotted, fields[sub_key], sub_value, result):
                    valid[dotted] = sub_value
        else:
            result.errors.append(Issue(key, "unknown key"))

    for key in TOP_LEVEL:
        if key not in data:
            result.missing.append(key)
    for section, fields in SECTIONS.items():
        present = data.get(section)
        for sub_key in fields:
            if not isinstance(present, dict) or sub_key not in present:
                result.missing.append(f"{section}.{sub_key}")

    _check_cross_fields(valid, result)
    return result


def _effective(valid: Mapping[str, Any], dotted: str) -> Any:
    if dotted in valid:
        return valid[dotted]
    section, _, sub_key = dotted.partition(".")
    return SECTIONS[section][sub_key].default


def _check_cross_fields(valid: Mapping[str, Any], result: ValidationResult) -> None:
    bad = {issue.key for issue in result.errors}
    pairs = [
        ("budgets.per_job_usd", "budgets.per_day_usd"),
        ("budgets.warn_at", "budgets.halt_at"),
    ]
    for low_key, high_key in pairs:
        if low_key in bad or high_key in bad:
            continue
        low, high = _effective(valid, low_key), _effective(valid, high_key)
        if low > high:
            result.errors.append(Issue(low_key, f"must be at most {high_key} ({high:g})"))


def default_for(dotted: str) -> object:
    if dotted in TOP_LEVEL:
        return TOP_LEVEL[dotted].default
    section, _, sub_key = dotted.partition(".")
    return SECTIONS[section][sub_key].default


def _key(key: object) -> str:
    text = str(key)
    return text if re.fullmatch(r"[A-Za-z0-9_-]+", text) else toml_value(text)


def toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        if not value:
            return "{}"
        pairs = [f"{_key(k)} = {toml_value(v)}" for k, v in value.items()]
        return "{ " + ", ".join(pairs) + " }"
    raise TypeError(f"cannot render {type(value).__name__} as TOML")


def _line(key: str, spec: Field) -> str:
    text = f"{key} = {toml_value(spec.default)}"
    return f"{text}  # {spec.comment}" if spec.comment else text


def render_default() -> str:
    """Render the default config.toml text, LF line endings, trailing newline."""
    lines = [
        "# Software Factory project configuration.",
        "# Validate with: python install.py check",
        "",
    ]
    lines += [_line(key, spec) for key, spec in TOP_LEVEL.items()]
    for section, fields in SECTIONS.items():
        lines += ["", f"[{section}]"]
        lines += [_line(key, spec) for key, spec in fields.items()]
    return "\n".join(lines) + "\n"
