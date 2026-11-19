"""E03/T3: the allow/deny checker, the Claude Code hook and its launcher, and dogfooding.

Covers E03 AC-05 to AC-08 and AC-12 to AC-14. Expectations come from the E03 spec, the design
note and ADR 0017, not from the implementation.
"""

from __future__ import annotations

import ast
import io
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

import agents
from tests._ac import REPO_ROOT
from tests._gate import PASS, gate_repo, profile, run_gate, touches

KIT = REPO_ROOT / "kit" / ".factory"
KIT_AGENTS_PY = KIT / "agents" / "agents.py"
KIT_LAUNCHER = KIT / "agents" / "claude-hook"
AGENTS_REL = ".factory/agents"
POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="the launcher tests run sh")

VALID_STATE = """+++
phase = "build"
track = "full"
active_task = ""
blockers = []
updated = 2026-11-18T21:30:00Z
+++
"""

TASK = """+++
id = "E03-T3"
title = "A slice"
status = "in-progress"
review_round = 0
created = 2026-11-18T21:30:00Z
updated = 2026-11-18T21:30:00Z
+++

## Goal

## Acceptance criteria

## Notes
"""

BODY = "\n## Scope\n\n## Inputs\n\n## Outputs\n"
LOCKED_TEST = "tests/test_locked.py"


def role(name: str, tools: list[str], scope: Mapping[str, list[str]] | None = None) -> str:
    lines = [
        f'name = "{name}"',
        f'title = "{name.title()}"',
        'summary = "A fixture role."',
        'model_hint = "any"',
        'different_from = ""',
        f"tools = {json.dumps(tools)}",
    ]
    if scope:
        lines += ["", "[scope]"] + [f"{k} = {json.dumps(v)}" for k, v in scope.items()]
    return "+++\n" + "\n".join(lines) + "\n+++\n" + BODY


ROLES = {
    "reader.md": role("reader", ["read", "search"]),
    "implementer.md": role(
        "implementer",
        ["read", "search", "edit", "write", "run"],
        {"write": ["src/**", "tests/*.py"], "run": ["uv run pytest", "git status"]},
    ),
    "operator.md": role("operator", ["read", "search", "edit", "write", "run", "web"]),
}


def make_repo(root: Path, *, lock: bool = True) -> Path:
    files = {
        ".agentic/STATE.md": VALID_STATE,
        ".agentic/tasks/E03-T3.md": TASK,
        "src/app.py": "x = 1\n",
        "src/pkg/mod.py": "y = 2\n",
        LOCKED_TEST: "def test_locked() -> None:\n    assert True\n",
        "tests/test_open.py": "def test_open() -> None:\n    assert True\n",
        "tests/unit/test_deep.py": "def test_deep() -> None:\n    assert True\n",
        "docs/notes.md": "notes\n",
    }
    files.update({f"{AGENTS_REL}/core/{rel}": text for rel, text in ROLES.items()})
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    if lock:
        agents.lock(root, "E03-T3", [root / LOCKED_TEST])
    return root


def allow(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *args: str,
) -> tuple[int, str]:
    monkeypatch.chdir(root)
    code = agents.main(["allow", *args])
    out = capsys.readouterr()
    return code, out.out + out.err


def hook(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    payload: Mapping[str, object] | str,
    role_env: str | None = None,
) -> tuple[int, str, str]:
    """Run `agents.py hook claude-code` in-process: (exit code, stdout, stderr)."""
    monkeypatch.chdir(root)
    if role_env is None:
        monkeypatch.delenv("FACTORY_ROLE", raising=False)
    else:
        monkeypatch.setenv("FACTORY_ROLE", role_env)
    text = payload if isinstance(payload, str) else json.dumps({"cwd": str(root), **payload})
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))
    code = agents.main(["hook", "claude-code"])
    out = capsys.readouterr()
    return code, out.out, out.err


def call(tool: str, **tool_input: str) -> dict[str, object]:
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input}


# --- AC-05: the checker -------------------------------------------------------------------------


@pytest.mark.ac("E03-AC-05")
def test_a_listed_tool_is_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path)
    assert allow(root, monkeypatch, capsys, "reader", "read")[0] == 0
    assert allow(root, monkeypatch, capsys, "reader", "search")[0] == 0


@pytest.mark.ac("E03-AC-05")
@pytest.mark.parametrize("tool", ["edit", "write", "run", "web"])
def test_a_tool_outside_the_list_is_denied_with_a_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tool: str,
) -> None:
    root = make_repo(tmp_path)
    extra = {"edit": ["--path", "src/app.py"], "write": ["--path", "src/new.py"]}
    extra["run"] = ["--command", "ls"]
    code, output = allow(root, monkeypatch, capsys, "reader", tool, *extra.get(tool, []))
    assert code == 1, output
    assert tool in output and "reader" in output


@pytest.mark.ac("E03-AC-05")
@pytest.mark.parametrize(
    ("path", "allowed"),
    [
        ("src/app.py", True),
        ("src/pkg/mod.py", True),
        ("src/new/deep/file.py", True),
        ("tests/test_open.py", True),
        ("tests/unit/test_deep.py", False),
        ("docs/notes.md", False),
        ("README.md", False),
    ],
)
def test_edit_and_write_paths_follow_the_write_globs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    path: str,
    allowed: bool,
) -> None:
    root = make_repo(tmp_path)
    for tool in ("edit", "write"):
        code, output = allow(root, monkeypatch, capsys, "implementer", tool, "--path", path)
        assert code == (0 if allowed else 1), (tool, path, output)


@pytest.mark.ac("E03-AC-05")
def test_paths_outside_the_repo_are_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path / "repo")
    outside = tmp_path / "elsewhere.py"
    for path in (str(outside), "../elsewhere.py"):
        code, output = allow(root, monkeypatch, capsys, "operator", "write", "--path", path)
        assert code == 1, output
        assert "outside" in output


@pytest.mark.ac("E03-AC-05")
def test_absolute_paths_inside_the_repo_are_judged_like_relative_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path)
    inside = str(root / "src" / "app.py")
    assert allow(root, monkeypatch, capsys, "implementer", "edit", "--path", inside)[0] == 0
    docs = str(root / "docs" / "notes.md")
    assert allow(root, monkeypatch, capsys, "implementer", "edit", "--path", docs)[0] == 1


@pytest.mark.ac("E03-AC-05")
@pytest.mark.parametrize("role_name", ["implementer", "operator"])
def test_a_locked_file_is_denied_to_every_role(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    role_name: str,
) -> None:
    root = make_repo(tmp_path)
    for tool in ("edit", "write"):
        code, output = allow(root, monkeypatch, capsys, role_name, tool, "--path", LOCKED_TEST)
        assert code == 1, output
        assert "locked by E03-T3" in output


@pytest.mark.ac("E03-AC-05")
@pytest.mark.parametrize(
    ("command", "allowed"),
    [
        ("uv run pytest", True),
        ("uv run pytest -q tests/test_open.py", True),
        ("git status --short", True),
        ("uv run pytester", False),
        ("uv run", False),
        ("uv  run   pytest -x", True),
        ("rm -rf src", False),
        ("uv run pytest && rm -rf src", False),
        ("uv run pytest; rm -rf src", False),
        ("uv run pytest | tee out.txt", False),
        ("uv run pytest > out.txt", False),
        ("uv run pytest < in.txt", False),
        ("uv run pytest `rm -rf src`", False),
        ("uv run pytest $(rm -rf src)", False),
        ("uv run pytest &", False),
        ("uv run pytest\nrm -rf src", False),
        ("uv run pytest 'unbalanced", False),
    ],
)
def test_run_commands_follow_the_run_prefixes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    allowed: bool,
) -> None:
    root = make_repo(tmp_path)
    code, output = allow(root, monkeypatch, capsys, "implementer", "run", "--command", command)
    assert code == (0 if allowed else 1), (command, output)


@pytest.mark.ac("E03-AC-05")
def test_without_a_run_scope_any_command_is_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path)
    for command in ("rm -rf build", "make && make test", "echo hi > out.txt"):
        code, output = allow(root, monkeypatch, capsys, "operator", "run", "--command", command)
        assert code == 0, (command, output)


@pytest.mark.ac("E03-AC-05")
def test_without_a_write_scope_any_repo_path_is_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path)
    for path in ("docs/notes.md", "README.md", "tests/unit/test_deep.py"):
        assert allow(root, monkeypatch, capsys, "operator", "write", "--path", path)[0] == 0


@pytest.mark.ac("E03-AC-05")
def test_an_unknown_role_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path)
    code, output = allow(root, monkeypatch, capsys, "nobody", "read")
    assert code == 2, output
    assert "nobody" in output


@pytest.mark.ac("E03-AC-05")
def test_invalid_agent_files_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path)
    (root / AGENTS_REL / "core" / "broken.md").write_text(role("broken", ["fly"]), "utf-8")
    code, output = allow(root, monkeypatch, capsys, "reader", "read")
    assert code == 2, output
    assert "agents.py check" in output


@pytest.mark.ac("E03-AC-05")
@pytest.mark.parametrize(("tool", "missing"), [("edit", "--path"), ("run", "--command")])
def test_edit_needs_a_path_and_run_needs_a_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tool: str,
    missing: str,
) -> None:
    root = make_repo(tmp_path)
    code, output = allow(root, monkeypatch, capsys, "operator", tool)
    assert code == 2, output
    assert missing in output


@pytest.mark.ac("E03-AC-05")
def test_the_checker_api_returns_a_decision(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    granted = agents.allow(root, "implementer", "edit", path="src/app.py")
    assert granted.allowed is True
    refused = agents.allow(root, "reader", "edit", path="src/app.py")
    assert refused.allowed is False
    assert refused.reason


# --- AC-06: the Claude Code hook ----------------------------------------------------------------


@pytest.mark.ac("E03-AC-06")
def test_the_claude_code_tool_map() -> None:
    assert agents.CLAUDE_CODE_TOOLS == {
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


@pytest.mark.ac("E03-AC-06")
def test_an_allowed_call_exits_0_with_no_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path)
    code, out, err = hook(root, monkeypatch, capsys, call("Read", file_path="src/app.py"), "reader")
    assert (code, out, err) == (0, "", "")


@pytest.mark.ac("E03-AC-06")
def test_a_denied_call_exits_2_with_the_reason_on_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path)
    payload = call("Edit", file_path=str(root / "src" / "app.py"))
    code, out, err = hook(root, monkeypatch, capsys, payload, "reader")
    assert code == 2
    assert out == ""
    assert "reader" in err and "edit" in err


@pytest.mark.ac("E03-AC-06")
@pytest.mark.parametrize(
    ("payload", "role_name", "expected"),
    [
        (call("Write", file_path="docs/notes.md"), "implementer", 2),
        (call("Write", file_path="src/new.py"), "implementer", 0),
        (call("MultiEdit", file_path="src/app.py"), "implementer", 0),
        (call("NotebookEdit", notebook_path="docs/book.ipynb"), "implementer", 2),
        (call("NotebookEdit", notebook_path="src/book.ipynb"), "implementer", 0),
        (call("Bash", command="uv run pytest -q"), "implementer", 0),
        (call("Bash", command="curl example.com"), "implementer", 2),
        (call("Grep", pattern="x"), "reader", 0),
        (call("Glob", pattern="**/*.py"), "reader", 0),
        (call("WebFetch", url="https://example.com"), "reader", 2),
        (call("WebSearch", query="x"), "operator", 0),
    ],
)
def test_the_hook_maps_tools_and_applies_scopes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    payload: dict[str, object],
    role_name: str,
    expected: int,
) -> None:
    root = make_repo(tmp_path)
    code, _, err = hook(root, monkeypatch, capsys, payload, role_name)
    assert code == expected, err


@pytest.mark.ac("E03-AC-06")
def test_an_unmapped_tool_is_denied_when_a_role_is_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path)
    code, _, err = hook(root, monkeypatch, capsys, call("Task", prompt="go"), "operator")
    assert code == 2
    assert "Task" in err


@pytest.mark.ac("E03-AC-06")
def test_agent_type_naming_a_factory_role_decides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path)
    payload = {**call("Bash", command="ls"), "agent_type": "reader"}
    code, _, err = hook(root, monkeypatch, capsys, payload, "operator")
    assert code == 2, err
    assert "reader" in err


@pytest.mark.ac("E03-AC-06")
def test_agent_type_that_is_not_a_factory_role_falls_back_to_factory_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path)
    payload = {**call("Bash", command="ls"), "agent_type": "Explore"}
    assert hook(root, monkeypatch, capsys, payload, "reader")[0] == 2
    assert hook(root, monkeypatch, capsys, payload, "operator")[0] == 0
    assert hook(root, monkeypatch, capsys, payload, None)[0] == 0


# --- AC-07: no role set -------------------------------------------------------------------------


@pytest.mark.ac("E03-AC-07")
@pytest.mark.parametrize("role_env", [None, ""])
def test_with_no_role_tool_lists_do_not_apply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    role_env: str | None,
) -> None:
    root = make_repo(tmp_path)
    for payload in (
        call("Bash", command="rm -rf build && make"),
        call("Write", file_path="docs/notes.md"),
        call("Task", prompt="go"),
        call("WebFetch", url="https://example.com"),
    ):
        code, _, err = hook(root, monkeypatch, capsys, payload, role_env)
        assert code == 0, (payload, err)


@pytest.mark.ac("E03-AC-07")
@pytest.mark.parametrize("tool", ["Edit", "Write", "MultiEdit"])
def test_with_no_role_locked_files_are_still_protected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tool: str,
) -> None:
    root = make_repo(tmp_path)
    code, _, err = hook(root, monkeypatch, capsys, call(tool, file_path=LOCKED_TEST), None)
    assert code == 2
    assert "locked by E03-T3" in err


# --- AC-08: fails closed ------------------------------------------------------------------------


@pytest.mark.ac("E03-AC-08")
@pytest.mark.parametrize(
    "payload",
    ["not json", "[]", json.dumps({"tool_input": {}}), json.dumps({"tool_name": "Edit"})],
)
def test_malformed_input_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    payload: str,
) -> None:
    root = make_repo(tmp_path)
    code, _, err = hook(root, monkeypatch, capsys, payload, None)
    assert code == 2
    assert err


@pytest.mark.ac("E03-AC-08")
def test_an_edit_without_a_path_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path)
    code, _, err = hook(root, monkeypatch, capsys, call("Edit"), "operator")
    assert code == 2
    assert err


@pytest.mark.ac("E03-AC-08")
def test_an_unknown_factory_role_blocks_every_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path)
    code, _, err = hook(root, monkeypatch, capsys, call("Read", file_path="x"), "nobody")
    assert code == 2
    assert "unknown role" in err


@pytest.mark.ac("E03-AC-08")
def test_invalid_agent_files_block_and_name_the_fix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path)
    (root / AGENTS_REL / "core" / "broken.md").write_text(role("broken", ["fly"]), "utf-8")
    code, _, err = hook(root, monkeypatch, capsys, call("Read", file_path="x"), None)
    assert code == 2
    assert "agents.py check" in err


@pytest.mark.ac("E03-AC-08")
def test_a_crash_blocks_instead_of_exiting_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path)

    def boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr(agents, "validate", boom)
    code, _, err = hook(root, monkeypatch, capsys, call("Read", file_path="x"), None)
    assert code == 2
    assert "boom" in err


@pytest.mark.ac("E03-AC-08")
def test_the_hook_without_state_py_exits_2(tmp_path: Path) -> None:
    lonely = tmp_path / AGENTS_REL
    lonely.mkdir(parents=True)
    shutil.copyfile(KIT_AGENTS_PY, lonely / "agents.py")
    result = subprocess.run(
        [sys.executable, str(lonely / "agents.py"), "hook", "claude-code"],
        input=json.dumps(call("Read", file_path="x")),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, result
    assert "state.py" in result.stderr


# --- the launcher (ADR 0017) --------------------------------------------------------------------


def installed_repo(root: Path) -> Path:
    make_repo(root)
    for rel in ("state/state.py", "agents/agents.py", "agents/claude-hook"):
        (root / ".factory" / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(KIT / rel, root / ".factory" / rel)
    return root


def launch(root: Path, payload: Mapping[str, object], role_env: str | None) -> int:
    env = {k: v for k, v in os.environ.items() if k != "FACTORY_ROLE"}
    if role_env is not None:
        env["FACTORY_ROLE"] = role_env
    result = subprocess.run(
        ["sh", str(root / ".factory" / "agents" / "claude-hook")],
        input=json.dumps({"cwd": str(root), **payload}),
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode


@POSIX_ONLY
@pytest.mark.ac("E03-AC-06")
def test_the_launcher_runs_the_hook(tmp_path: Path) -> None:
    root = installed_repo(tmp_path)
    assert launch(root, call("Read", file_path="src/app.py"), "reader") == 0
    assert launch(root, call("Bash", command="ls"), "reader") == 2


@POSIX_ONLY
@pytest.mark.ac("E03-AC-08")
def test_the_launcher_without_python_blocks(tmp_path: Path) -> None:
    root = installed_repo(tmp_path)
    result = subprocess.run(
        ["/bin/sh", str(root / ".factory" / "agents" / "claude-hook")],
        input=json.dumps(call("Read", file_path="x")),
        cwd=root,
        env={"PATH": str(tmp_path / "empty-bin")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, result
    assert "Python" in result.stderr


# --- AC-12: the done-when, end to end -----------------------------------------------------------


@POSIX_ONLY
@pytest.mark.ac("E03-AC-12")
def test_done_when_a_role_cannot_call_a_tool_outside_its_list(tmp_path: Path) -> None:
    root = installed_repo(tmp_path)
    assert launch(root, call("Read", file_path="src/app.py"), "reader") == 0
    assert launch(root, call("Grep", pattern="x"), "reader") == 0
    assert launch(root, call("Edit", file_path="src/app.py"), "reader") == 2
    assert launch(root, call("Write", file_path="src/new.py"), "reader") == 2
    assert launch(root, call("Bash", command="ls"), "reader") == 2


@POSIX_ONLY
@pytest.mark.ac("E03-AC-12")
def test_done_when_an_edit_to_a_locked_test_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = gate_repo(
        tmp_path / "repo",
        {
            "py.toml": profile(
                "py", ["marker.txt"], {"format": touches("ran-format.txt"), "lint": PASS}
            )
        },
        files={"marker.txt": "x\n"},
    )
    installed_repo(repo)
    assert launch(repo, call("Edit", file_path=LOCKED_TEST), "implementer") == 2
    assert run_gate(repo, monkeypatch, capsys)[0] == 0
    (repo / LOCKED_TEST).write_text("def test_locked() -> None:\n    assert False\n", "utf-8")
    code, output = run_gate(repo, monkeypatch, capsys)
    assert code == 1, output
    assert f"{LOCKED_TEST}: locked by E03-T3: changed" in output


# --- AC-13: this repo uses the hook and its own locks -------------------------------------------


@pytest.mark.ac("E03-AC-13")
def test_this_repo_registers_the_hook_for_every_mapped_tool() -> None:
    settings = json.loads((REPO_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    entries = settings["hooks"]["PreToolUse"]
    ours = [
        (entry, h)
        for entry in entries
        for h in entry["hooks"]
        if ".factory/agents/claude-hook" in h["command"]
    ]
    assert len(ours) == 1, entries
    entry, command = ours[0]
    assert set(entry["matcher"].split("|")) == set(agents.CLAUDE_CODE_TOOLS)
    assert command["type"] == "command"
    assert command["onFailure"] == "block"
    assert 0 < command["timeout"] <= 10


@pytest.mark.ac("E03-AC-13")
def test_this_repo_locks_every_e03_slices_tests() -> None:
    for task in ("E03-T1", "E03-T2", "E03-T3"):
        assert (REPO_ROOT / ".agentic" / "locks" / f"{task}.toml").is_file(), task
    assert [str(p) for p in agents.validate(REPO_ROOT)] == []
    assert agents.verify_locks(REPO_ROOT) == []


# --- AC-14: standard library only ---------------------------------------------------------------


@pytest.mark.ac("E03-AC-14")
def test_agents_py_imports_only_the_standard_library() -> None:
    tree = ast.parse(KIT_AGENTS_PY.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
    foreign = sorted({n.split(".")[0] for n in names} - set(sys.stdlib_module_names) - {"state"})
    assert not foreign, foreign
