"""E13/T1: a role session's command line: the allow-list from the role's card, the filled-in
agent command template, and the stage prompt.

Covers E13 AC-07. Expectations come from the E13 spec (AC-07, "New config.toml keys", Changes of
21 Nov 2026) and the design note ("Sessions and the allow-list", "The prompt"), and from Claude
Code's permission rule syntax (a space and `*` after a command prefix; ADR 0042).
"""

from __future__ import annotations

import tomllib

import pytest

import agents
import pipeline
from tests._ac import REPO_ROOT

AC = "E13-AC-07"
KIT = REPO_ROOT / "kit"
DEFAULT_COMMAND = [
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
]
VERIFIER_PREFIXES = [
    "python .factory/gates/gate.py",
    "python3 .factory/gates/gate.py",
    "py .factory/gates/gate.py",
    "uv run python .factory/gates/gate.py",
    "python .factory/state/state.py",
    "python3 .factory/state/state.py",
    "py .factory/state/state.py",
    "uv run python .factory/state/state.py",
    "git diff",
    "git log",
    "git show",
    "git status",
]


def card(role: str) -> tuple[list[str], list[str]]:
    """(tools, run scope) read straight from the kit's core role card."""
    text = (KIT / ".factory" / "agents" / "core" / f"{role}.md").read_text(encoding="utf-8")
    front = text.split("+++\n")[1]
    data = tomllib.loads(front)
    return list(data["tools"]), list(data.get("scope", {}).get("run", []))


# --- the allow-list -----------------------------------------------------------------------------


@pytest.mark.ac(AC)
def test_implementer_gets_its_tools_and_any_shell_command() -> None:
    expected = "Read,Glob,Grep,Edit,MultiEdit,NotebookEdit,Write,Bash,PowerShell"
    assert pipeline.role_allowed_tools(KIT, "implementer") == expected


@pytest.mark.ac(AC)
def test_docs_writer_gets_no_shell() -> None:
    expected = "Read,Glob,Grep,Edit,MultiEdit,NotebookEdit,Write"
    assert pipeline.role_allowed_tools(KIT, "docs-writer") == expected


@pytest.mark.ac(AC)
def test_verifier_gets_one_prefix_rule_per_run_scope_for_each_shell() -> None:
    rules = ["Read", "Glob", "Grep"]
    for prefix in VERIFIER_PREFIXES:
        rules += [f"Bash({prefix} *)", f"PowerShell({prefix} *)"]
    assert pipeline.role_allowed_tools(KIT, "verifier") == ",".join(rules)


@pytest.mark.ac(AC)
def test_allowed_tools_keeps_the_cards_order_and_drops_repeats() -> None:
    assert pipeline.allowed_tools(["run", "read", "read"], []) == "Bash,PowerShell,Read"
    assert pipeline.allowed_tools(["edit", "write"], []) == "Edit,MultiEdit,NotebookEdit,Write"
    assert pipeline.allowed_tools(["web"], []) == "WebFetch,WebSearch"
    assert pipeline.allowed_tools(["run"], ["git log", "git log"]) == (
        "Bash(git log *),PowerShell(git log *)"
    )


@pytest.mark.ac(AC)
def test_an_unknown_tool_is_refused() -> None:
    with pytest.raises(ValueError, match="teleport"):
        pipeline.allowed_tools(["read", "teleport"], [])


@pytest.mark.ac(AC)
def test_an_unknown_role_is_refused() -> None:
    with pytest.raises(ValueError, match="no-such-role"):
        pipeline.role_allowed_tools(KIT, "no-such-role")


@pytest.mark.ac(AC)
@pytest.mark.parametrize("role", [c.name for c in agents.role_cards(KIT)])
def test_every_core_roles_list_holds_only_rules_for_its_own_tools(role: str) -> None:
    tools, scope = card(role)
    rules = pipeline.role_allowed_tools(KIT, role).split(",")
    names = {rule.split("(")[0] for rule in rules}
    own = {name for tool in tools for name in agents.CLAUDE_CODE_AGENT_TOOLS[tool]}
    assert names <= own, names - own
    assert names == own, "every tool on the card is allowed"
    if scope:
        assert "Bash" not in rules and "PowerShell" not in rules, "no bare shell with a scope"
        assert {r for r in rules if r.startswith(("Bash(", "PowerShell("))} == {
            f"{shell}({prefix} *)" for prefix in scope for shell in ("Bash", "PowerShell")
        }


# --- the command --------------------------------------------------------------------------------


@pytest.mark.ac(AC)
def test_the_default_template_is_claude_code_with_accept_edits_and_no_prompts() -> None:
    assert pipeline.PIPELINE_DEFAULTS["agent_command"] == DEFAULT_COMMAND


@pytest.mark.ac(AC)
def test_session_argv_fills_each_placeholder_element() -> None:
    argv = pipeline.session_argv(DEFAULT_COMMAND, "verifier", "Read,Glob", "Check it.")
    assert argv == [
        "claude",
        "-p",
        "--agent",
        "verifier",
        "--output-format",
        "json",
        "--permission-mode",
        "acceptEdits",
        "--permission-prompts",
        "none",
        "--allowedTools",
        "Read,Glob",
        "Check it.",
    ]


@pytest.mark.ac(AC)
def test_a_hostile_prompt_stays_one_argument() -> None:
    hostile = 'say "hi" --permission-mode bypassPermissions; rm -rf / {role} $(x)\n--agent root'
    argv = pipeline.session_argv(DEFAULT_COMMAND, "verifier", "Read", hostile)
    assert argv[-1] == hostile
    assert len(argv) == len(DEFAULT_COMMAND)
    assert argv.count("bypassPermissions") == 0


@pytest.mark.ac(AC)
def test_session_argv_leaves_other_elements_alone() -> None:
    template = ["tool", "--role={role}", "{role}", "{prompt}"]
    assert pipeline.session_argv(template, "verifier", "Read", "p") == [
        "tool",
        "--role={role}",
        "verifier",
        "p",
    ]


@pytest.mark.ac(AC)
def test_session_env_names_the_role_for_the_e03_hook() -> None:
    assert pipeline.session_env("verifier") == {"FACTORY_ROLE": "verifier"}


# --- the prompt ---------------------------------------------------------------------------------

SPEC_PROMPT = """You are the spec-writer on job e31-widgets, at the spec stage of the full track.
Epic: E31. Task: e31-widgets.
Follow the skill: spec-interview.
Read: the request below, docs/prd/software-factory-prd.md.
The stage passes when: the spec for E31 is committed in docs/specs, passes docs.py check and has at least one acceptance criterion.
The last review of this stage said: Answer to Q1: option A.
Work only in this worktree. Commit your work and stop."""  # noqa: E501


@pytest.mark.ac(AC)
def test_the_spec_prompt_in_full() -> None:
    text = pipeline.prompt(
        "spec",
        "spec-writer",
        job="e31-widgets",
        epic="E31",
        task="e31-widgets",
        reads=("the request below", "docs/prd/software-factory-prd.md"),
        note="Answer to Q1: option A.",
    )
    assert text == SPEC_PROMPT


@pytest.mark.ac(AC)
def test_a_prompt_without_reads_or_note_leaves_those_lines_out() -> None:
    text = pipeline.prompt("docs", "docs-writer", job="j", epic="E31", task="E31-T1")
    lines = text.splitlines()
    assert lines[0] == "You are the docs-writer on job j, at the docs stage of the full track."
    assert not any(line.startswith(("Read:", "The last review", "Follow the")) for line in lines)
    assert lines[-1] == "Work only in this worktree. Commit your work and stop."


@pytest.mark.ac(AC)
def test_a_role_with_two_skills_names_both() -> None:
    text = pipeline.prompt("test", "test-designer", job="j", epic="E31", task="E31-T1")
    assert "Follow the skills: tdd-slices, lock-tests." in text.splitlines()


@pytest.mark.ac(AC)
@pytest.mark.parametrize("stage", [s.name for s in pipeline.STAGES if s.roles])
def test_every_stage_prompt_names_its_pass_condition_and_is_deterministic(stage: str) -> None:
    found = next(s for s in pipeline.STAGES if s.name == stage)
    role = found.roles[0]
    first = pipeline.prompt(stage, role, job="j", epic="E31", task="E31-T1", note="n")
    again = pipeline.prompt(stage, role, job="j", epic="E31", task="E31-T1", note="n")
    assert first == again
    assert f"The stage passes when: {found.passes.replace('{epic}', 'E31')}" in first


@pytest.mark.ac(AC)
def test_a_role_not_in_the_stage_is_refused() -> None:
    with pytest.raises(ValueError, match="implementer"):
        pipeline.prompt("spec", "implementer", job="j", epic="E31", task="t")
