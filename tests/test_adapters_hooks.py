"""E12/T2: one hook handler for Claude Code, Copilot and Cursor, and the hook configs (ADR 0024).

Covers E12 AC-03 to AC-06. Payloads follow each tool's documented `preToolUse` input.
Expectations come from the E12 spec, the design note and ADR 0024, not from the implementation.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

import agents
import build
from tests._ac import REPO_ROOT
from tests.test_adapters_build import repo_with, run_build
from tests.test_agents_hook import AGENTS_REL, KIT, LOCKED_TEST, make_repo, role

POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="the launcher tests run sh")

COPILOT_TOOLS = {
    "view": "read",
    "glob": "search",
    "grep": "search",
    "edit": "edit",
    "create": "write",
    "bash": "run",
    "powershell": "run",
    "web_fetch": "web",
}
CURSOR_TOOLS = {
    "Read": "read",
    "Grep": "search",
    "Write": "write",
    "Delete": "write",
    "Shell": "run",
}

CLAUDE_ENTRY: dict[str, Any] = {
    "matcher": (
        "Read|Glob|Grep|Edit|MultiEdit|NotebookEdit|Write|Bash|PowerShell|WebFetch|WebSearch"
    ),
    "hooks": [
        {
            "type": "command",
            "command": (
                "git -c 'alias.factory-hook=!sh .factory/agents/claude-hook' factory-hook;"
                " exit $LASTEXITCODE"
            ),
            "timeout": 10,
            "onFailure": "block",
        }
    ],
}
COPILOT_ENTRY = {
    "type": "command",
    "bash": "sh .factory/agents/copilot-hook",
    "powershell": (
        "git -c 'alias.factory-hook=!sh .factory/agents/copilot-hook' factory-hook;"
        " exit $LASTEXITCODE"
    ),
    "timeoutSec": 10,
}
# Cursor blocks a permission hook that exits 0 with no output, when failClosed is set.
CURSOR_ALLOW = '{"permission": "allow"}\n'
CURSOR_ENTRY = {
    "command": (
        "git -c 'alias.factory-hook=!sh .factory/agents/cursor-hook' factory-hook;"
        " exit $LASTEXITCODE"
    ),
    "timeout": 10,
    "failClosed": True,
}


def hook_repo(root: Path) -> Path:
    """E03's fixture repo, plus an `editor` role that may edit but not write."""
    make_repo(root)
    path = root / AGENTS_REL / "core" / "editor.md"
    path.write_text(role("editor", ["read", "search", "edit"]), encoding="utf-8", newline="\n")
    return root


def run_hook(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    entry: str,
    payload: Mapping[str, object] | str,
    role_env: str | None = None,
) -> tuple[int, str, str]:
    """`agents.py hook <entry>` in-process: (exit code, stdout, stderr)."""
    if role_env is None:
        monkeypatch.delenv("FACTORY_ROLE", raising=False)
    else:
        monkeypatch.setenv("FACTORY_ROLE", role_env)
    text = payload if isinstance(payload, str) else json.dumps(payload)
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))
    code = agents.main(["hook", entry])
    out = capsys.readouterr()
    return code, out.out, out.err


def copilot(root: Path, name: str, form: object = "string", **args: object) -> dict[str, object]:
    """Copilot's preToolUse payload: the CLI form, toolArgs a string or an object, or VS Code's."""
    if form == "vscode":
        return {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "cwd": str(root),
            "tool_name": name,
            "tool_input": args,
        }
    tool_args: object = json.dumps(args) if form == "string" else args
    return {"timestamp": 1704614600000, "cwd": str(root), "toolName": name, "toolArgs": tool_args}


def cursor(root: Path, name: str, **tool_input: object) -> dict[str, object]:
    return {
        "conversation_id": "c1",
        "generation_id": "g1",
        "hook_event_name": "preToolUse",
        "workspace_roots": [str(root)],
        "tool_name": name,
        "tool_input": tool_input,
    }


def claude(root: Path, name: str, **tool_input: object) -> dict[str, object]:
    return {
        "hook_event_name": "PreToolUse",
        "cwd": str(root),
        "tool_name": name,
        "tool_input": tool_input,
    }


def copilot_denied(code: int, out: str) -> str:
    assert code == 2, out
    answer = json.loads(out)
    assert answer["permissionDecision"] == "deny"
    assert answer["permissionDecisionReason"]
    return str(answer["permissionDecisionReason"])


def cursor_denied(code: int, out: str) -> str:
    assert code == 2, out
    answer = json.loads(out)
    assert answer["permission"] == "deny"
    assert answer["user_message"]
    assert answer["agent_message"]
    return str(answer["agent_message"])


def denied(entry: str, code: int, out: str, err: str) -> str:
    """The reason, read in the protocol of the tool that sent the payload."""
    if entry == "copilot":
        return copilot_denied(code, out)
    if entry == "cursor":
        return cursor_denied(code, out)
    assert code == 2
    assert out == ""
    return err


def payload_for(entry: str, root: Path, name: str, **args: object) -> dict[str, object]:
    return copilot(root, name, **args) if entry == "copilot" else cursor(root, name, **args)


# --- AC-03: the hook configs ---------------------------------------------------------------------


def built_json(out: Mapping[str, bytes], rel: str) -> object:
    data = out[rel]
    assert data.endswith(b"\n") and b"\r" not in data, rel
    return json.loads(data.decode("utf-8"))


@pytest.mark.ac("E12-AC-03")
def test_the_copilot_hook_config(tmp_path: Path) -> None:
    out = build.build(repo_with(tmp_path, ["verifier"]))
    assert built_json(out, ".github/hooks/factory.json") == {
        "version": 1,
        "hooks": {"preToolUse": [COPILOT_ENTRY]},
    }


@pytest.mark.ac("E12-AC-03")
def test_the_cursor_hook_config(tmp_path: Path) -> None:
    out = build.build(repo_with(tmp_path, ["verifier"]))
    assert built_json(out, ".cursor/hooks.json") == {
        "version": 1,
        "hooks": {"preToolUse": [CURSOR_ENTRY]},
    }


@pytest.mark.ac("E12-AC-03")
def test_the_claude_code_settings(tmp_path: Path) -> None:
    out = build.build(repo_with(tmp_path, ["verifier"]))
    assert built_json(out, ".claude/settings.json") == {"hooks": {"PreToolUse": [CLAUDE_ENTRY]}}
    assert set(CLAUDE_ENTRY["matcher"].split("|")) == set(agents.CLAUDE_CODE_TOOLS)


@pytest.mark.ac("E12-AC-03")
def test_claude_code_settings_keep_every_other_setting(tmp_path: Path) -> None:
    root = repo_with(tmp_path, ["verifier"])
    theirs = {"matcher": "Bash", "hooks": [{"type": "command", "command": "./audit.sh"}]}
    stale = {
        "matcher": "Edit",
        "hooks": [{"type": "command", "command": "sh .factory/agents/claude-hook", "timeout": 5}],
    }
    existing: dict[str, Any] = {
        "permissions": {"allow": ["Bash(git status)"]},
        "hooks": {
            "PreToolUse": [theirs, stale],
            "PostToolUse": [{"matcher": "Write", "hooks": [{"type": "command", "command": "x"}]}],
        },
        "model": "sonnet",
    }
    (root / ".claude").mkdir()
    (root / ".claude" / "settings.json").write_text(json.dumps(existing), encoding="utf-8")
    got: Any = built_json(build.build(root), ".claude/settings.json")
    assert isinstance(got, dict)
    assert list(got) == ["permissions", "hooks", "model"]
    assert got["permissions"] == existing["permissions"]
    assert got["model"] == "sonnet"
    assert got["hooks"]["PostToolUse"] == existing["hooks"]["PostToolUse"]
    assert got["hooks"]["PreToolUse"] == [theirs, CLAUDE_ENTRY]


@pytest.mark.ac("E12-AC-03")
def test_cursor_hooks_keep_every_other_entry(tmp_path: Path) -> None:
    root = repo_with(tmp_path, ["verifier"])
    theirs = {"command": "./guard.sh"}
    stale = {"command": "sh .factory/agents/cursor-hook", "timeout": 3}
    existing = {
        "version": 1,
        "hooks": {
            "beforeShellExecution": [{"command": "./audit.sh"}],
            "preToolUse": [stale, theirs],
        },
    }
    (root / ".cursor").mkdir()
    (root / ".cursor" / "hooks.json").write_text(json.dumps(existing), encoding="utf-8")
    got = built_json(build.build(root), ".cursor/hooks.json")
    assert got == {
        "version": 1,
        "hooks": {
            "beforeShellExecution": [{"command": "./audit.sh"}],
            "preToolUse": [CURSOR_ENTRY, theirs],
        },
    }


@pytest.mark.ac("E12-AC-03")
@pytest.mark.parametrize("rel", [".claude/settings.json", ".cursor/hooks.json"])
def test_an_unreadable_config_to_merge_into_stops_the_build(tmp_path: Path, rel: str) -> None:
    root = repo_with(tmp_path, ["verifier"])
    (root / rel).parent.mkdir()
    (root / rel).write_text("{not json", encoding="utf-8")
    with pytest.raises(build.BuildError, match=rel):
        build.build(root)


@pytest.mark.ac("E12-AC-03")
def test_the_hook_configs_follow_the_chosen_tools(tmp_path: Path) -> None:
    out = build.build(repo_with(tmp_path, ["verifier"], ["copilot"]))
    assert ".github/hooks/factory.json" in out
    assert ".claude/settings.json" not in out
    assert ".cursor/hooks.json" not in out


@pytest.mark.ac("E12-AC-03")
def test_dropping_a_tool_takes_only_the_factory_entry_out_of_a_shared_config(
    tmp_path: Path,
) -> None:
    root = repo_with(tmp_path, ["verifier"])
    (root / ".claude").mkdir()
    settings = root / ".claude" / "settings.json"
    settings.write_text(json.dumps({"model": "sonnet"}), encoding="utf-8")
    assert run_build(root) == 0
    assert json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PreToolUse"] == [CLAUDE_ENTRY]
    (root / ".agentic").mkdir(exist_ok=True)
    (root / ".agentic" / "config.toml").write_text(
        '[adapters]\ntools = ["copilot"]\n', encoding="utf-8"
    )
    assert run_build(root) == 0
    assert json.loads(settings.read_text(encoding="utf-8")) == {"model": "sonnet"}
    assert not (root / ".cursor" / "hooks.json").exists()
    assert (root / ".github" / "hooks" / "factory.json").is_file()


@pytest.mark.ac("E12-AC-03")
def test_the_kit_ships_a_launcher_per_tool() -> None:
    for name, entry in (("copilot-hook", "copilot"), ("cursor-hook", "cursor")):
        text = (KIT / "agents" / name).read_text(encoding="utf-8")
        assert text.startswith("#!/bin/sh\n"), name
        assert f'"$here/agents.py" hook {entry}' in text, name
        assert "3, 11" in text, name
        assert "\r" not in text, name


@pytest.mark.ac("E12-AC-03")
def test_this_repo_registers_the_copilot_and_cursor_hooks() -> None:
    copilot_config = json.loads((REPO_ROOT / ".github/hooks/factory.json").read_text("utf-8"))
    assert copilot_config["hooks"]["preToolUse"] == [COPILOT_ENTRY]
    cursor_config = json.loads((REPO_ROOT / ".cursor/hooks.json").read_text("utf-8"))
    assert CURSOR_ENTRY in cursor_config["hooks"]["preToolUse"]


# --- AC-04: the Copilot hook ---------------------------------------------------------------------


@pytest.mark.ac("E12-AC-04")
def test_the_copilot_hook_tool_map() -> None:
    assert agents.COPILOT_HOOK_TOOLS == COPILOT_TOOLS


@pytest.mark.ac("E12-AC-04")
@pytest.mark.parametrize("form", ["string", "object", "vscode"])
def test_an_allowed_copilot_call_exits_0_with_no_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    form: str,
) -> None:
    root = hook_repo(tmp_path)
    monkeypatch.chdir(root)
    payload = copilot(root, "view", form, path="src/app.py")
    assert run_hook(monkeypatch, capsys, "copilot", payload, "reader") == (0, "", "")


@pytest.mark.ac("E12-AC-04")
@pytest.mark.parametrize("form", ["string", "object", "vscode"])
def test_a_denied_copilot_call_prints_the_deny_json_and_exits_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    form: str,
) -> None:
    root = hook_repo(tmp_path)
    monkeypatch.chdir(root)
    payload = copilot(root, "bash", form, command="ls")
    code, out, _ = run_hook(monkeypatch, capsys, "copilot", payload, "reader")
    assert "reader may not use run" in copilot_denied(code, out)


@pytest.mark.ac("E12-AC-04")
@pytest.mark.parametrize(
    ("who", "name", "args", "allowed"),
    [
        ("reader", "glob", {"pattern": "**/*.py"}, True),
        ("reader", "grep", {"pattern": "x"}, True),
        ("reader", "edit", {"path": "src/app.py"}, False),
        ("reader", "web_fetch", {"url": "https://example.com"}, False),
        ("operator", "web_fetch", {"url": "https://example.com"}, True),
        ("implementer", "edit", {"path": "src/app.py"}, True),
        ("implementer", "edit", {"path": "docs/notes.md"}, False),
        ("implementer", "create", {"path": "tests/test_new.py"}, True),
        ("implementer", "create", {"path": "docs/new.md"}, False),
        ("implementer", "bash", {"command": "uv run pytest -q"}, True),
        ("implementer", "bash", {"command": "rm -rf src"}, False),
        ("implementer", "powershell", {"command": "git status"}, True),
        ("implementer", "powershell", {"command": "git push"}, False),
    ],
)
def test_the_copilot_hook_maps_tools_and_applies_scopes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    who: str,
    name: str,
    args: dict[str, object],
    allowed: bool,
) -> None:
    root = hook_repo(tmp_path)
    monkeypatch.chdir(root)
    code, out, _ = run_hook(monkeypatch, capsys, "copilot", copilot(root, name, **args), who)
    assert (code == 0) is allowed, out
    if not allowed:
        copilot_denied(code, out)


@pytest.mark.ac("E12-AC-04")
@pytest.mark.parametrize("field", ["agentType", "agent_type"])
def test_the_copilot_agent_field_names_the_role(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    field: str,
) -> None:
    root = hook_repo(tmp_path)
    monkeypatch.chdir(root)
    payload = {**copilot(root, "bash", command="ls"), field: "reader"}
    code, out, _ = run_hook(monkeypatch, capsys, "copilot", payload, "operator")
    assert "reader" in copilot_denied(code, out)


@pytest.mark.ac("E12-AC-04")
def test_a_copilot_agent_that_is_no_factory_role_falls_back_to_factory_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = hook_repo(tmp_path)
    monkeypatch.chdir(root)
    payload = {**copilot(root, "bash", command="ls"), "agentType": "custom-agent"}
    assert run_hook(monkeypatch, capsys, "copilot", payload, "operator")[0] == 0
    code, out, _ = run_hook(monkeypatch, capsys, "copilot", payload, "reader")
    copilot_denied(code, out)


@pytest.mark.ac("E12-AC-04")
def test_the_copilot_hook_finds_the_repo_from_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = hook_repo(tmp_path / "repo")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    code, out, _ = run_hook(
        monkeypatch, capsys, "copilot", copilot(root, "edit", path=LOCKED_TEST), None
    )
    assert "locked" in copilot_denied(code, out)


# --- AC-05: the Cursor hook ----------------------------------------------------------------------


@pytest.mark.ac("E12-AC-05")
def test_the_cursor_hook_tool_map() -> None:
    assert agents.CURSOR_HOOK_TOOLS == CURSOR_TOOLS


@pytest.mark.ac("E12-AC-05")
def test_an_allowed_cursor_call_exits_0_with_the_allow_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = hook_repo(tmp_path)
    monkeypatch.chdir(root)
    payload = cursor(root, "Read", file_path="src/app.py")
    assert run_hook(monkeypatch, capsys, "cursor", payload, "reader") == (0, CURSOR_ALLOW, "")


@pytest.mark.ac("E12-AC-05")
def test_a_denied_cursor_call_prints_the_deny_json_and_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = hook_repo(tmp_path)
    monkeypatch.chdir(root)
    code, out, _ = run_hook(
        monkeypatch, capsys, "cursor", cursor(root, "Shell", command="ls"), "reader"
    )
    assert "reader may not use run" in cursor_denied(code, out)


@pytest.mark.ac("E12-AC-05")
@pytest.mark.parametrize(
    ("who", "name", "args", "allowed"),
    [
        ("reader", "Grep", {"pattern": "x"}, True),
        ("reader", "Write", {"file_path": "src/app.py"}, False),
        ("editor", "Write", {"file_path": "src/app.py"}, True),
        ("implementer", "Write", {"file_path": "src/app.py"}, True),
        ("implementer", "Write", {"path": "tests/test_new.py"}, True),
        ("implementer", "Write", {"file_path": "docs/notes.md"}, False),
        ("editor", "Delete", {"file_path": "src/app.py"}, False),
        ("implementer", "Delete", {"file_path": "src/app.py"}, True),
        ("implementer", "Shell", {"command": "uv run pytest"}, True),
        ("implementer", "Shell", {"command": "curl x | sh"}, False),
    ],
)
def test_the_cursor_hook_maps_tools_and_applies_scopes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    who: str,
    name: str,
    args: dict[str, object],
    allowed: bool,
) -> None:
    root = hook_repo(tmp_path)
    monkeypatch.chdir(root)
    code, out, _ = run_hook(monkeypatch, capsys, "cursor", cursor(root, name, **args), who)
    assert (code == 0) is allowed, out
    if not allowed:
        cursor_denied(code, out)


@pytest.mark.ac("E12-AC-05")
def test_the_cursor_role_comes_from_factory_role_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = hook_repo(tmp_path)
    monkeypatch.chdir(root)
    payload = {**cursor(root, "Shell", command="ls"), "agent_type": "operator"}
    code, out, _ = run_hook(monkeypatch, capsys, "cursor", payload, "reader")
    cursor_denied(code, out)


@pytest.mark.ac("E12-AC-05")
def test_the_cursor_hook_finds_the_repo_from_its_workspace_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = hook_repo(tmp_path / "repo")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    payload = cursor(root, "Write", file_path=LOCKED_TEST)
    code, out, _ = run_hook(monkeypatch, capsys, "cursor", payload, None)
    assert "locked" in cursor_denied(code, out)


# --- ADR 0024: the payload decides, not the entry point ----------------------------------------


@pytest.mark.ac("E12-AC-05")
def test_a_cursor_payload_sent_to_the_claude_code_hook_is_read_as_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = hook_repo(tmp_path)
    monkeypatch.chdir(root)
    payload = cursor(root, "Shell", command="ls")
    code, out, _ = run_hook(monkeypatch, capsys, "claude-code", payload, "reader")
    cursor_denied(code, out)
    allowed = cursor(root, "Read", file_path="src/app.py")
    assert run_hook(monkeypatch, capsys, "claude-code", allowed, "reader") == (0, CURSOR_ALLOW, "")


@pytest.mark.ac("E12-AC-04")
@pytest.mark.parametrize("form", ["string", "vscode"])
def test_a_copilot_payload_sent_to_the_claude_code_hook_is_read_as_copilot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    form: str,
) -> None:
    root = hook_repo(tmp_path)
    monkeypatch.chdir(root)
    payload = copilot(root, "bash", form, command="ls")
    code, out, _ = run_hook(monkeypatch, capsys, "claude-code", payload, "reader")
    copilot_denied(code, out)


@pytest.mark.ac("E12-AC-04")
@pytest.mark.parametrize("entry", ["copilot", "cursor"])
def test_a_claude_code_payload_is_answered_in_claude_codes_protocol(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    entry: str,
) -> None:
    root = hook_repo(tmp_path)
    monkeypatch.chdir(root)
    code, out, err = run_hook(
        monkeypatch, capsys, entry, claude(root, "Bash", command="ls"), "reader"
    )
    assert "reader may not use run" in denied("claude-code", code, out, err)


# --- AC-06: both hooks fail closed ---------------------------------------------------------------

ENTRIES = ["copilot", "cursor"]


@pytest.mark.ac("E12-AC-06")
@pytest.mark.parametrize("entry", ENTRIES)
@pytest.mark.parametrize("text", ["not json", "[]", "42", "{}"])
def test_malformed_input_is_denied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    entry: str,
    text: str,
) -> None:
    monkeypatch.chdir(hook_repo(tmp_path))
    code, out, err = run_hook(monkeypatch, capsys, entry, text, None)
    denied(entry, code, out, err)


@pytest.mark.ac("E12-AC-06")
@pytest.mark.parametrize("tool_args", ["{not json", "[1, 2]", 7])
def test_unreadable_copilot_tool_args_are_denied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tool_args: object,
) -> None:
    root = hook_repo(tmp_path)
    monkeypatch.chdir(root)
    payload = {**copilot(root, "view"), "toolArgs": tool_args}
    code, out, _ = run_hook(monkeypatch, capsys, "copilot", payload, None)
    copilot_denied(code, out)


@pytest.mark.ac("E12-AC-06")
@pytest.mark.parametrize("entry", ENTRIES)
def test_an_unknown_factory_role_is_denied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    entry: str,
) -> None:
    root = hook_repo(tmp_path)
    monkeypatch.chdir(root)
    name = "view" if entry == "copilot" else "Read"
    code, out, err = run_hook(
        monkeypatch, capsys, entry, payload_for(entry, root, name, path="x"), "nobody"
    )
    assert "unknown role" in denied(entry, code, out, err)


@pytest.mark.ac("E12-AC-06")
@pytest.mark.parametrize("entry", ENTRIES)
def test_invalid_agent_files_are_denied_and_name_the_fix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    entry: str,
) -> None:
    root = hook_repo(tmp_path)
    monkeypatch.chdir(root)
    (root / AGENTS_REL / "core" / "broken.md").write_text(role("broken", ["fly"]), "utf-8")
    name = "view" if entry == "copilot" else "Read"
    code, out, err = run_hook(
        monkeypatch, capsys, entry, payload_for(entry, root, name, path="x"), None
    )
    assert "agents.py check" in denied(entry, code, out, err)


@pytest.mark.ac("E12-AC-06")
@pytest.mark.parametrize("entry", ENTRIES)
def test_a_crash_is_denied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    entry: str,
) -> None:
    root = hook_repo(tmp_path)
    monkeypatch.chdir(root)

    def boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr(agents, "validate", boom)
    name = "view" if entry == "copilot" else "Read"
    code, out, err = run_hook(
        monkeypatch, capsys, entry, payload_for(entry, root, name, path="x"), None
    )
    assert "boom" in denied(entry, code, out, err)


@pytest.mark.ac("E12-AC-06")
@pytest.mark.parametrize(("entry", "name"), [("copilot", "task"), ("cursor", "Task")])
def test_an_unmapped_tool_is_denied_with_a_role_and_allowed_without(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    entry: str,
    name: str,
) -> None:
    root = hook_repo(tmp_path)
    monkeypatch.chdir(root)
    payload = payload_for(entry, root, name, prompt="do it")
    code, out, err = run_hook(monkeypatch, capsys, entry, payload, "operator")
    assert name in denied(entry, code, out, err)
    allowed = CURSOR_ALLOW if entry == "cursor" else ""
    assert run_hook(monkeypatch, capsys, entry, payload, None) == (0, allowed, "")


@pytest.mark.ac("E12-AC-06")
@pytest.mark.parametrize(
    ("entry", "name"),
    [("copilot", "edit"), ("copilot", "create"), ("cursor", "Write"), ("cursor", "Delete")],
)
def test_a_write_with_no_path_is_denied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    entry: str,
    name: str,
) -> None:
    root = hook_repo(tmp_path)
    monkeypatch.chdir(root)
    code, out, err = run_hook(
        monkeypatch, capsys, entry, payload_for(entry, root, name, content="x"), "operator"
    )
    denied(entry, code, out, err)


@pytest.mark.ac("E12-AC-06")
@pytest.mark.parametrize(
    ("entry", "name", "key"),
    [
        ("copilot", "edit", "path"),
        ("copilot", "create", "path"),
        ("cursor", "Write", "file_path"),
        ("cursor", "Write", "path"),
        ("cursor", "Delete", "file_path"),
    ],
)
@pytest.mark.parametrize("role_env", [None, "operator"])
def test_locked_files_are_always_protected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    entry: str,
    name: str,
    key: str,
    role_env: str | None,
) -> None:
    root = hook_repo(tmp_path)
    monkeypatch.chdir(root)
    payload = payload_for(entry, root, name, **{key: LOCKED_TEST})
    code, out, err = run_hook(monkeypatch, capsys, entry, payload, role_env)
    assert "locked" in denied(entry, code, out, err)


@pytest.mark.ac("E12-AC-06")
@pytest.mark.parametrize("entry", ENTRIES)
def test_the_hook_without_state_py_is_denied(tmp_path: Path, entry: str) -> None:
    lonely = tmp_path / AGENTS_REL
    lonely.mkdir(parents=True)
    shutil.copyfile(KIT / "agents" / "agents.py", lonely / "agents.py")
    result = subprocess.run(
        [sys.executable, str(lonely / "agents.py"), "hook", entry],
        input=json.dumps(payload_for(entry, tmp_path, "view", path="x")),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, result


# --- the launchers -------------------------------------------------------------------------------


def installed(root: Path) -> Path:
    hook_repo(root)
    for rel in ("state/state.py", "agents/agents.py", "agents/copilot-hook", "agents/cursor-hook"):
        (root / ".factory" / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(KIT / rel, root / ".factory" / rel)
    return root


def launch(
    root: Path, launcher: str, payload: Mapping[str, object], role_env: str | None, path: str = ""
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "FACTORY_ROLE"}
    if role_env is not None:
        env["FACTORY_ROLE"] = role_env
    if path:
        env["PATH"] = path
    return subprocess.run(
        ["/bin/sh", str(root / ".factory" / "agents" / launcher)],
        input=json.dumps(payload),
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@POSIX_ONLY
@pytest.mark.ac("E12-AC-04")
def test_the_copilot_launcher_runs_the_hook(tmp_path: Path) -> None:
    root = installed(tmp_path)
    assert launch(root, "copilot-hook", copilot(root, "view", path="x"), "reader").returncode == 0
    result = launch(root, "copilot-hook", copilot(root, "bash", command="ls"), "reader")
    copilot_denied(result.returncode, result.stdout)


@POSIX_ONLY
@pytest.mark.ac("E12-AC-05")
def test_the_cursor_launcher_runs_the_hook(tmp_path: Path) -> None:
    root = installed(tmp_path)
    assert (
        launch(root, "cursor-hook", cursor(root, "Read", file_path="x"), "reader").returncode == 0
    )
    result = launch(root, "cursor-hook", cursor(root, "Shell", command="ls"), "reader")
    cursor_denied(result.returncode, result.stdout)


@POSIX_ONLY
@pytest.mark.ac("E12-AC-06")
@pytest.mark.parametrize("launcher", ["copilot-hook", "cursor-hook"])
def test_a_launcher_without_python_is_denied(tmp_path: Path, launcher: str) -> None:
    root = installed(tmp_path)
    payload = cursor(root, "Read", file_path="x")
    result = launch(root, launcher, payload, None, path=str(tmp_path / "empty-bin"))
    assert result.returncode == 2, result
    assert "Python" in result.stderr
