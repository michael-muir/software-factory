"""E12/T3: Claude Code's PowerShell tool goes through the hook, and PowerShell syntax can't chain.

The product owner's live check on Windows (20 Nov 2026) let a verifier run `ls`: Claude Code's
`PowerShell` tool wasn't in the hook's matcher or tool table, so the hook never saw the call.
Claude Code's hooks docs (code.claude.com/docs/en/hooks) say:
- the matcher `Bash|PowerShell` covers both shells; the PowerShell tool's `tool_input` has the
  same fields as Bash's, with the command in `command`;
- when a subagent calls a tool, `PreToolUse` carries `agent_id` and `agent_type`, and
  `agent_type` is the subagent's name (or the `--agent` session's).
A role's `run` scope is a list of command prefixes, and the check refuses shell control text so
that a prefix can't be chained. PowerShell has control syntax that POSIX shells don't: `(...)`,
`@(...)`, `$var` and `$x.Method()` all evaluate in a command's arguments. These tests use the
real verifier role (it may run only the gate, state.py and git diff/log/show/status), from a
freshly installed repo.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

import agents
from factory_installer import cli
from tests._ac import REPO_ROOT
from tests.test_adapters_shells import SHELLS, commands, environment, run

ROLE = "verifier"
DENY = f"factory hook: blocked: {ROLE} may only run commands starting with:"
CONTROL = f"factory hook: blocked: {ROLE} may not run commands with shell control characters"


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("powershell") / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    assert cli.main([str(root)]) == 0
    return root


def powershell_call(
    root: Path, command: str, *, subagent: bool = True, tool: str = "PowerShell"
) -> dict[str, object]:
    """Claude Code's PreToolUse payload for a PowerShell call, as the hooks docs show it."""
    payload: dict[str, object] = {
        "session_id": "abc123",
        "transcript_path": str(root / "transcript.jsonl"),
        "cwd": str(root),
        "permission_mode": "default",
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": {
            "command": command,
            "description": "A call from the test",
            "timeout": 120000,
            "run_in_background": False,
        },
        "tool_use_id": "toolu_01ABC123",
    }
    if subagent:
        payload["agent_id"] = "a1b2c3"
        payload["agent_type"] = ROLE
    return payload


def judge(
    capsys: pytest.CaptureFixture[str],
    payload: Mapping[str, object],
    env: Mapping[str, str] | None = None,
) -> tuple[int, str, str]:
    """`agents.py hook claude-code` in-process: (exit code, stdout, stderr)."""
    code = agents.hook("claude-code", json.dumps(payload), env or {})
    out = capsys.readouterr()
    return code, out.out, out.err


# --- the tool table and the matcher --------------------------------------------------------------


@pytest.mark.ac("E03-AC-06")
def test_claude_codes_powershell_tool_maps_to_run() -> None:
    assert agents.CLAUDE_CODE_TOOLS["PowerShell"] == "run"
    assert agents.CLAUDE_CODE_TOOLS["Bash"] == "run"


@pytest.mark.ac("E12-AC-03")
@pytest.mark.parametrize("where", ["installed", "this repo"])
def test_the_generated_matcher_covers_bash_and_powershell(repo: Path, where: str) -> None:
    root = repo if where == "installed" else REPO_ROOT
    settings = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))
    ours = [
        entry
        for entry in settings["hooks"]["PreToolUse"]
        if any(".factory/agents/claude-hook" in h["command"] for h in entry["hooks"])
    ]
    assert len(ours) == 1, settings
    matcher = ours[0]["matcher"]
    # Letters and | only: Claude Code reads it as a list of exact names, not a regex.
    assert all(c.isalpha() or c == "|" for c in matcher), matcher
    names = matcher.split("|")
    assert {"Bash", "PowerShell"} <= set(names)
    assert set(names) == set(agents.CLAUDE_CODE_TOOLS)


# --- a PowerShell call is held to the role -------------------------------------------------------


@pytest.mark.ac("E12-AC-10")
@pytest.mark.parametrize("command", ["ls", "Get-ChildItem", "Remove-Item notes.txt"])
def test_a_subagents_powershell_call_outside_its_scope_is_denied(
    repo: Path, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    code, out, err = judge(capsys, powershell_call(repo, command))
    assert (code, out) == (2, ""), err
    assert DENY in err


@pytest.mark.ac("E12-AC-10")
@pytest.mark.parametrize(
    "command", ["git log -1", "git status --short", "uv run python .factory/gates/gate.py"]
)
def test_a_subagents_powershell_call_in_its_scope_is_allowed(
    repo: Path, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    assert judge(capsys, powershell_call(repo, command)) == (0, "", "")


@pytest.mark.ac("E12-AC-10")
def test_a_powershell_call_under_factory_role_is_denied(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A whole session run as the role, with no agent_type: FACTORY_ROLE decides."""
    payload = powershell_call(repo, "ls", subagent=False)
    code, _, err = judge(capsys, payload, {"FACTORY_ROLE": ROLE})
    assert code == 2
    assert DENY in err


@pytest.mark.ac("E12-AC-06")
def test_the_main_session_without_a_role_may_run_powershell(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No agent_type and no FACTORY_ROLE: only locks apply, as for Bash (E03 ADR 0017)."""
    assert judge(capsys, powershell_call(repo, "ls", subagent=False)) == (0, "", "")


@pytest.mark.ac("E12-AC-10")
def test_a_subagent_is_named_by_agent_type_whatever_the_session_role(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The docs: a subagent's type takes precedence over the session's own agent."""
    payload = powershell_call(repo, "ls")
    code, _, err = judge(capsys, payload, {"FACTORY_ROLE": "implementer"})
    assert code == 2
    assert DENY in err


@pytest.mark.ac("E12-AC-10")
def test_a_subagents_write_is_denied_by_its_tools(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = powershell_call(repo, "unused")
    payload.update(
        tool_name="Write",
        tool_input={"file_path": str(repo / "notes.txt"), "content": "hello"},
    )
    code, _, err = judge(capsys, payload)
    assert code == 2
    assert f"{ROLE} may not use write" in err


# --- PowerShell syntax counts as shell control ---------------------------------------------------

CHAINED = [
    "git log -1; Remove-Item notes.txt",
    "git log -1 && Remove-Item notes.txt",
    "git log -1 || Remove-Item notes.txt",
    "git log -1 | Out-File notes.txt",
    "git log -1 & Remove-Item notes.txt",
    "git log -1 > notes.txt",
    "git log -1 2> notes.txt",
    "git log -1 *> notes.txt",
    "git log -1 `nRemove-Item notes.txt",
    "git log $(Remove-Item notes.txt)",
    "git log (Remove-Item notes.txt)",
    "git log -1 (Set-Content notes.txt hello)",
    "git log @(Remove-Item notes.txt)",
    "git log -1 @args",
    "git log -1 $env:USERPROFILE",
    "git log ${env:USERPROFILE}",
    "git log $ExecutionContext.InvokeCommand.InvokeScript('Remove-Item notes.txt')",
    "git log -1\nRemove-Item notes.txt",
    "git log -1\rRemove-Item notes.txt",
    "git log -1\u0085Remove-Item notes.txt",
    "git log -1" + chr(0x2028) + "Remove-Item notes.txt",
    "git log -1" + chr(0x2029) + "Remove-Item notes.txt",
]


@pytest.mark.ac("E03-AC-05")
@pytest.mark.parametrize("command", CHAINED)
def test_powershell_control_syntax_is_denied_in_a_powershell_call(
    repo: Path, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    code, _, err = judge(capsys, powershell_call(repo, command))
    assert code == 2, (command, err)
    assert CONTROL in err, (command, err)


@pytest.mark.ac("E03-AC-05")
@pytest.mark.parametrize("command", CHAINED)
def test_powershell_control_syntax_is_denied_by_allow(repo: Path, command: str) -> None:
    """The shared check, as Copilot's powershell tool and Cursor's Shell reach it on Windows."""
    decision = agents.allow(repo, ROLE, "run", command=command)
    assert decision.allowed is False, command
    assert decision.reason == f"{ROLE} may not run commands with shell control characters"


@pytest.mark.ac("E03-AC-05")
@pytest.mark.parametrize(
    "command",
    [
        "git log -1",
        "git log --author=me@example.com",
        "git log --format=%H -1",
        "git diff --stat HEAD~1",
        "git show HEAD:README.md",
        "uv run python .factory/state/state.py resume",
    ],
)
def test_plain_in_scope_commands_stay_allowed(repo: Path, command: str) -> None:
    assert agents.allow(repo, ROLE, "run", command=command).allowed is True, command


# --- the registered command, in each shell Claude Code may run it in -----------------------------


@pytest.mark.ac("E12-AC-03")
@pytest.mark.parametrize("shell", list(SHELLS))
def test_the_registered_command_judges_a_powershell_call_in_each_shell(
    repo: Path, shell: str
) -> None:
    argv = SHELLS[shell](commands(repo)["claude-code"])
    if argv is None:
        pytest.skip(f"{shell} isn't installed here")
    env = environment("claude-code")
    denied = run(argv, repo, json.dumps(powershell_call(repo, "ls")).encode(), env)
    assert denied.returncode == 2, (denied.stdout, denied.stderr)
    assert DENY in denied.stderr.decode(), denied.stderr
    data = json.dumps(powershell_call(repo, "git log -1")).encode()
    allowed = run(argv, repo, data, env)
    assert allowed.returncode == 0, (allowed.stdout, allowed.stderr)


@pytest.mark.ac("E12-AC-10")
def test_stdin_is_read_by_the_cli_for_a_powershell_call(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("FACTORY_ROLE", raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(powershell_call(repo, "ls"))))
    assert agents.main(["hook", "claude-code"]) == 2
    assert DENY in capsys.readouterr().err
