"""E12/T4: Claude Code agent files list PowerShell for roles that may run commands.

The product owner's decision of 20 Nov 2026: on Windows, Claude Code treats its PowerShell tool
as the primary shell, so a role with `run` gets both `Bash` and `PowerShell` in its agent
file's `tools`. The hook holds both to the same `run` scope (tests/test_adapters_powershell.py).
A role without `run` gets neither.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import agents
from factory_installer import cli
from tests._ac import REPO_ROOT


def claude_tools(path: Path) -> list[str]:
    """The `tools` line of a generated Claude Code agent file, as a list."""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("tools: "):
            return [name.strip() for name in line[len("tools: ") :].strip('"').split(",")]
    raise AssertionError(f"{path} has no tools line")


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("powershell-agents") / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    assert cli.main([str(root)]) == 0
    return root


@pytest.mark.ac("E12-AC-01")
def test_run_maps_to_bash_and_powershell() -> None:
    assert agents.CLAUDE_CODE_AGENT_TOOLS["run"] == ["Bash", "PowerShell"]


@pytest.mark.ac("E12-AC-01")
def test_every_agent_tool_name_is_one_the_hook_maps_to_the_same_neutral_tool() -> None:
    for tool, names in agents.CLAUDE_CODE_AGENT_TOOLS.items():
        for name in names:
            assert agents.CLAUDE_CODE_TOOLS[name] == tool, name


@pytest.mark.ac("E12-AC-01")
@pytest.mark.parametrize("where", ["installed", "this repo"])
def test_the_verifiers_agent_file_lists_bash_and_powershell(repo: Path, where: str) -> None:
    root = repo if where == "installed" else REPO_ROOT
    assert claude_tools(root / ".claude" / "agents" / "verifier.md") == [
        "Read",
        "Glob",
        "Grep",
        "Bash",
        "PowerShell",
    ]


@pytest.mark.ac("E12-AC-01")
@pytest.mark.parametrize("where", ["installed", "this repo"])
def test_powershell_is_listed_exactly_where_bash_is(repo: Path, where: str) -> None:
    root = repo if where == "installed" else REPO_ROOT
    files = sorted((root / ".claude" / "agents").glob("*.md"))
    assert files
    for path in files:
        tools = claude_tools(path)
        assert ("Bash" in tools) == ("PowerShell" in tools), path.name
        if "Bash" in tools:
            assert tools.index("PowerShell") == tools.index("Bash") + 1, path.name


@pytest.mark.ac("E12-AC-01")
def test_a_role_without_run_gets_no_shell(repo: Path) -> None:
    tools = claude_tools(repo / ".claude" / "agents" / "spec-writer.md")
    assert "Bash" not in tools
    assert "PowerShell" not in tools
