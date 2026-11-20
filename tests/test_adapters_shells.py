"""E12: each generated hook command runs, and answers, in every shell a tool may use.

The hook configs are run by different shells: Claude Code uses sh, or Git Bash on Windows;
Copilot CLI uses bash, or PowerShell on Windows, and reads `.claude/settings.json` too without
setting $CLAUDE_PROJECT_DIR; Cursor uses sh, or PowerShell on Windows, where it pipes the payload
through PowerShell and so prefixes a byte order mark. These tests run each registered command,
as written in the generated config of a freshly installed repo, through every shell that is
present (sh, bash, Windows PowerShell 5.1 and pwsh 7), with a denied and an allowed call, and
Cursor's Windows wrapper as its forum reports describe it. CI runs them on Linux, macOS and
Windows.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from factory_installer import cli

ROLE = (
    "verifier"  # tools: read, search, run; run only the gate, state.py and git diff/log/show/status
)
DENY = f"factory hook: blocked: {ROLE} may only run commands starting with:"
WINDOWS = os.name == "nt"


def _which_bash() -> str | None:
    """bash, unless it's Windows' WSL launcher, which isn't a shell for this repo."""
    bash = shutil.which("bash")
    if bash is None or (WINDOWS and "system32" in bash.lower()):
        return None
    return bash


SHELLS: dict[str, Callable[[str], list[str] | None]] = {
    "sh": lambda cmd: ["sh", "-c", cmd] if shutil.which("sh") else None,
    "bash": lambda cmd: [b, "-c", cmd] if (b := _which_bash()) else None,
    "powershell": lambda cmd: (
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd]
        if shutil.which("powershell")
        else None
    ),
    "pwsh": lambda cmd: (
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", cmd] if shutil.which("pwsh") else None
    ),
}
POWERSHELLS = ("powershell", "pwsh")


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("shells") / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    assert cli.main([str(root)]) == 0
    (root / "src").mkdir()
    return root


def _config(root: Path, rel: str) -> dict[str, object]:
    data: dict[str, object] = json.loads((root / rel).read_text(encoding="utf-8"))
    return data


def commands(root: Path) -> dict[str, str]:
    """Each registered command a shell other than the cloud agent's bash may run."""
    claude = _config(root, ".claude/settings.json")
    copilot = _config(root, ".github/hooks/factory.json")
    cursor = _config(root, ".cursor/hooks.json")
    return {
        "claude-code": claude["hooks"]["PreToolUse"][0]["hooks"][0]["command"],  # type: ignore[index]
        "copilot": copilot["hooks"]["preToolUse"][0]["powershell"],  # type: ignore[index]
        "copilot-bash": copilot["hooks"]["preToolUse"][0]["bash"],  # type: ignore[index]
        "cursor": cursor["hooks"]["preToolUse"][0]["command"],  # type: ignore[index]
    }


def payload(tool: str, root: Path, command: str) -> dict[str, object]:
    """A run call in each tool's own payload form, naming the role where the tool can."""
    if tool == "claude-code":
        return {
            "hook_event_name": "PreToolUse",
            "cwd": str(root),
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "agent_type": ROLE,
        }
    if tool.startswith("copilot"):
        return {
            "timestamp": 1704614600000,
            "cwd": str(root),
            "toolName": "powershell" if WINDOWS else "bash",
            "toolArgs": json.dumps({"command": command}),
            "agentType": ROLE,
        }
    return {
        "conversation_id": "c1",
        "generation_id": "g1",
        "hook_event_name": "preToolUse",
        "workspace_roots": [str(root)],
        "tool_name": "Shell",
        "tool_input": {"command": command},
    }


def environment(tool: str, path: str | None = None) -> dict[str, str]:
    """No $CLAUDE_PROJECT_DIR (Copilot sets none), and FACTORY_ROLE for Cursor."""
    env = {k: v for k, v in os.environ.items() if k not in ("FACTORY_ROLE", "CLAUDE_PROJECT_DIR")}
    if tool == "cursor":
        env["FACTORY_ROLE"] = ROLE
    if path is not None:
        env["PATH"] = path
    return env


def run(
    argv: list[str], cwd: Path, data: bytes, env: dict[str, str]
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(argv, cwd=cwd, input=data, env=env, capture_output=True, timeout=120)


def assert_denied(tool: str, result: subprocess.CompletedProcess[bytes]) -> None:
    out, err = result.stdout.decode(), result.stderr.decode()
    assert result.returncode == 2, (out, err)
    seen = f"stdout {result.stdout!r}, stderr {result.stderr!r}"
    if tool.startswith("copilot"):
        answer = json.loads(out)
        assert answer["permissionDecision"] == "deny", seen
        assert answer["permissionDecisionReason"].startswith(DENY), seen
    elif tool == "cursor":
        answer = json.loads(out)
        assert answer["permission"] == "deny", seen
        assert answer["user_message"].startswith(DENY), seen
    else:
        assert DENY in err, seen


def assert_allowed(tool: str, result: subprocess.CompletedProcess[bytes]) -> None:
    """Exit 0: Cursor with {"permission": "allow"} (it blocks on no output), the others silent."""
    assert result.returncode == 0, (result.stdout.decode(), result.stderr.decode())
    if tool == "cursor":
        assert json.loads(result.stdout) == {"permission": "allow"}, result.stdout
    else:
        assert result.stdout.strip() == b""


def cases() -> list[tuple[str, str]]:
    found = []
    for tool in ("claude-code", "copilot", "copilot-bash", "cursor"):
        for shell in SHELLS:
            if tool == "copilot" and shell not in POWERSHELLS:
                continue  # Copilot runs its powershell command only in PowerShell
            if tool == "copilot-bash" and shell in POWERSHELLS:
                continue
            found.append((tool, shell))
    return found


@pytest.mark.ac("E12-AC-03")
@pytest.mark.parametrize(("tool", "shell"), cases())
def test_each_registered_command_answers_in_each_shell(repo: Path, tool: str, shell: str) -> None:
    command = commands(repo)[tool]
    argv = SHELLS[shell](command)
    if argv is None:
        pytest.skip(f"{shell} isn't installed here")
    env = environment(tool)
    denied = run(argv, repo, json.dumps(payload(tool, repo, "ls")).encode(), env)
    assert_denied(tool, denied)
    allowed = run(argv, repo, json.dumps(payload(tool, repo, "git status")).encode(), env)
    assert_allowed(tool, allowed)


@pytest.mark.ac("E12-AC-03")
@pytest.mark.parametrize("shell", list(SHELLS))
def test_the_claude_code_command_works_from_a_subfolder(repo: Path, shell: str) -> None:
    """Claude Code runs hooks in Claude's current folder, which follows its `cd`."""
    argv = SHELLS[shell](commands(repo)["claude-code"])
    if argv is None:
        pytest.skip(f"{shell} isn't installed here")
    data = json.dumps(payload("claude-code", repo / "src", "ls")).encode()
    assert_denied("claude-code", run(argv, repo / "src", data, environment("claude-code")))


def cursor_wrapper(payload_file: Path, command: str) -> str:
    """Cursor's Windows wrapper, as its forum reports quote it, keeping the exit code."""
    return (
        "$OutputEncoding = [System.Text.Encoding]::UTF8; "
        f"Get-Content -LiteralPath '{payload_file}' -Raw | & {{ $input | {command} }}; "
        "exit $LASTEXITCODE"
    )


@pytest.mark.ac("E12-AC-05")
@pytest.mark.parametrize("shell", POWERSHELLS)
def test_the_cursor_command_answers_through_cursors_powershell_wrapper(
    repo: Path, tmp_path: Path, shell: str
) -> None:
    command = commands(repo)["cursor"]
    for call, check in (("ls", "denied"), ("git status", "allowed")):
        payload_file = tmp_path / f"payload-{check}.json"
        payload_file.write_text(json.dumps(payload("cursor", repo, call)), encoding="utf-8")
        argv = SHELLS[shell](cursor_wrapper(payload_file, command))
        if argv is None:
            pytest.skip(f"{shell} isn't installed here")
        result = run(argv, repo, b"", environment("cursor"))
        if check == "denied":
            assert_denied("cursor", result)
        else:
            assert_allowed("cursor", result)


def path_without_sh() -> str | None:
    """PATH with git but without any folder that holds sh or bash, as on many Windows PCs."""
    git = shutil.which("git")
    if git is None:
        return None
    git_dir = Path(git).parent
    if (git_dir / "sh.exe").exists() or (git_dir / "sh").exists():
        git_dir = git_dir.parent / "cmd"  # Git for Windows: cmd/ holds git.exe and no shell
    kept = [str(git_dir)]
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        folder = Path(entry)
        if not any((folder / name).exists() for name in ("sh", "sh.exe", "bash", "bash.exe")):
            kept.append(entry)
    path = os.pathsep.join(kept)
    if shutil.which("sh", path=path) or not shutil.which("git", path=path):
        return None
    return path


@pytest.mark.ac("E12-AC-03")
@pytest.mark.skipif(not WINDOWS, reason="sh is always on PATH outside Windows")
@pytest.mark.parametrize("tool", ["claude-code", "copilot", "cursor"])
@pytest.mark.parametrize("shell", POWERSHELLS)
def test_powershell_commands_need_no_sh_on_path(repo: Path, tool: str, shell: str) -> None:
    path = path_without_sh()
    if path is None:
        pytest.skip("can't build a PATH with git and without sh here")
    argv = SHELLS[shell](commands(repo)[tool])
    if argv is None or not shutil.which(argv[0], path=os.environ["PATH"]):
        pytest.skip(f"{shell} isn't installed here")
    argv[0] = str(shutil.which(argv[0]))  # the shell itself, found before PATH is narrowed
    env = environment(tool, path)
    assert_denied(tool, run(argv, repo, json.dumps(payload(tool, repo, "ls")).encode(), env))
    allowed = run(argv, repo, json.dumps(payload(tool, repo, "git status")).encode(), env)
    assert_allowed(tool, allowed)


@pytest.mark.ac("E12-AC-05")
@pytest.mark.parametrize("kind", ["claude-code", "copilot", "cursor"])
def test_a_payload_with_a_byte_order_mark_is_read(repo: Path, kind: str) -> None:
    """Straight to agents.py, with raw bytes on stdin, as Cursor's PowerShell sends them."""
    tool = kind
    agents = repo / ".factory" / "agents" / "agents.py"
    env = environment(tool)
    for call, denied, marks in (("ls", True, 1), ("git status", False, 1), ("ls", True, 2)):
        # Windows PowerShell 5.1 sends two marks through Cursor's wrapper (seen on CI)
        data = b"\xef\xbb\xbf" * marks + json.dumps(payload(tool, repo, call)).encode()
        result = run([sys.executable, str(agents), "hook", kind], repo, data, env)
        if denied:
            assert_denied(tool, result)
        else:
            assert_allowed(tool, result)


@pytest.mark.ac("E12-AC-06")
def test_a_payload_that_isnt_utf8_is_denied(repo: Path) -> None:
    agents = repo / ".factory" / "agents" / "agents.py"
    data = b'{"tool_name": "Bash", "tool_input": {"command": "\xff"}}'
    result = run([sys.executable, str(agents), "hook", "claude-code"], repo, data, environment(""))
    assert result.returncode == 2
    assert b"factory hook: blocked:" in result.stderr
