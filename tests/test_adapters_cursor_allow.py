"""E12/T3: Cursor's hook answers an allowed call with JSON, as its permission-hook protocol needs.

The product owner's Cursor CLI live check (20 Nov 2026) blocked `git log -1` for the verifier:
"Tool blocked because this hook is configured to fail closed ... returned no output". Cursor's
hooks docs (cursor.com/docs/hooks) say that with `failClosed`, "hook failures (crash, timeout,
non-zero exit code, no output) block the action", that exit 0 means "use the JSON output", and
that `preToolUse` outputs `"permission": "allow" | "deny"`, with `user_message` and
`agent_message` for a deny. Exit 2 blocks, "equivalent to returning permission: deny".
So an allowed Cursor call prints `{"permission": "allow"}` and exits 0. Claude Code and Copilot
still allow with exit 0 and no output.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import agents
from factory_installer import cli
from tests.test_adapters_shells import SHELLS, commands, cursor_wrapper, environment, run

ROLE = "verifier"
ALLOW = {"permission": "allow"}


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("cursor-allow") / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    assert cli.main([str(root)]) == 0
    return root


def cursor_call(root: Path, tool: str, **args: object) -> dict[str, object]:
    """Cursor's preToolUse payload, as its hooks docs describe it."""
    return {
        "conversation_id": "c1",
        "generation_id": "g1",
        "hook_event_name": "preToolUse",
        "workspace_roots": [str(root)],
        "tool_name": tool,
        "tool_input": args,
    }


def judge(
    capsys: pytest.CaptureFixture[str], entry: str, payload: dict[str, object], role: str | None
) -> tuple[int, str, str]:
    env = {"FACTORY_ROLE": role} if role else {}
    code = agents.hook(entry, json.dumps(payload), env)
    out = capsys.readouterr()
    return code, out.out, out.err


def allow_answer(out: str) -> object:
    lines = out.splitlines()
    assert len(lines) == 1, out
    return json.loads(lines[0])


@pytest.mark.ac("E12-AC-05")
@pytest.mark.parametrize(
    ("tool", "args", "role"),
    [
        ("Shell", {"command": "git log -1"}, ROLE),
        ("Read", {"file_path": "README.md"}, ROLE),
        ("Grep", {"pattern": "x"}, ROLE),
        ("Shell", {"command": "ls"}, None),
        ("Write", {"file_path": "notes.txt", "content": "hello"}, None),
        ("Task", {"prompt": "x"}, None),  # unmapped, with no role: allowed
    ],
)
def test_an_allowed_cursor_call_prints_permission_allow(
    repo: Path,
    capsys: pytest.CaptureFixture[str],
    tool: str,
    args: dict[str, object],
    role: str | None,
) -> None:
    code, out, err = judge(capsys, "cursor", cursor_call(repo, tool, **args), role)
    assert code == 0, err
    assert allow_answer(out) == ALLOW
    assert err == ""


@pytest.mark.ac("E12-AC-05")
def test_a_cursor_payload_through_another_entry_still_answers_in_cursors_form(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Cursor imports .claude/settings.json, so its payload can arrive at `hook claude-code`."""
    payload = cursor_call(repo, "Shell", command="git log -1")
    code, out, _ = judge(capsys, "claude-code", payload, ROLE)
    assert (code, allow_answer(out)) == (0, ALLOW)


@pytest.mark.ac("E12-AC-05")
def test_a_denied_cursor_call_matches_the_docs_schema(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = judge(capsys, "cursor", cursor_call(repo, "Shell", command="ls"), ROLE)
    assert code == 2
    answer = json.loads(out)
    assert set(answer) == {"permission", "user_message", "agent_message"}
    assert answer["permission"] == "deny"
    assert answer["user_message"].startswith("factory hook: blocked: ")
    assert answer["agent_message"] == answer["user_message"]


@pytest.mark.ac("E12-AC-06")
@pytest.mark.parametrize("stdin", ["", "not json", "[]", "{}"])
def test_a_bad_cursor_payload_is_denied_with_json(
    capsys: pytest.CaptureFixture[str], stdin: str
) -> None:
    code = agents.hook("cursor", stdin, {"FACTORY_ROLE": ROLE})
    out = capsys.readouterr().out
    assert code == 2
    assert json.loads(out)["permission"] == "deny"


@pytest.mark.ac("E12-AC-04")
@pytest.mark.parametrize("entry", ["claude-code", "copilot"])
def test_claude_code_and_copilot_still_allow_with_no_output(
    repo: Path, capsys: pytest.CaptureFixture[str], entry: str
) -> None:
    if entry == "copilot":
        payload: dict[str, object] = {
            "timestamp": 1704614600000,
            "cwd": str(repo),
            "toolName": "bash",
            "toolArgs": json.dumps({"command": "git log -1"}),
        }
    else:
        payload = {
            "hook_event_name": "PreToolUse",
            "cwd": str(repo),
            "tool_name": "Bash",
            "tool_input": {"command": "git log -1"},
        }
    assert judge(capsys, entry, payload, ROLE) == (0, "", "")


# --- the registered command, in each shell Cursor may run it in ----------------------------------


@pytest.mark.ac("E12-AC-05")
@pytest.mark.parametrize("shell", list(SHELLS))
def test_the_registered_cursor_command_prints_allow_in_each_shell(repo: Path, shell: str) -> None:
    argv = SHELLS[shell](commands(repo)["cursor"])
    if argv is None:
        pytest.skip(f"{shell} isn't installed here")
    data = json.dumps(cursor_call(repo, "Shell", command="git log -1")).encode()
    result = run(argv, repo, data, environment("cursor"))
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert allow_answer(result.stdout.decode()) == ALLOW


@pytest.mark.ac("E12-AC-05")
@pytest.mark.parametrize("shell", ["powershell", "pwsh"])
def test_cursors_powershell_wrapper_gets_the_allow_json(
    repo: Path, tmp_path: Path, shell: str
) -> None:
    payload_file = tmp_path / "payload.json"
    payload_file.write_text(
        json.dumps(cursor_call(repo, "Shell", command="git log -1")), encoding="utf-8"
    )
    argv = SHELLS[shell](cursor_wrapper(payload_file, commands(repo)["cursor"]))
    if argv is None:
        pytest.skip(f"{shell} isn't installed here")
    result = run(argv, repo, b"", environment("cursor"))
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert allow_answer(result.stdout.decode()) == ALLOW
