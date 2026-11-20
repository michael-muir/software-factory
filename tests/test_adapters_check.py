"""E12/T3: the drift check, in build.py, the gate and install.py check; the done-when; dogfooding.

Covers E12 AC-08, AC-09 (the check), AC-10 and AC-12. AC-11 is the product owner's live check,
recorded in the PR. Expectations come from the E12 spec, the design note and ADR 0023, not from
the implementation.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import agents
import build
import gate
from factory_installer import cli
from tests._ac import REPO_ROOT
from tests._gate import PASS, gate_repo, profile, run_gate, touches
from tests._repo import git_repo
from tests.test_adapters_build import CLAUDE, COPILOT, front, repo_with
from tests.test_adapters_hooks import (
    claude,
    copilot,
    copilot_denied,
    cursor,
    cursor_denied,
    run_hook,
)
from tests.test_agents_hook import AGENTS_REL, make_repo, role

KIT = REPO_ROOT / "kit" / ".factory"
BUILD_PY = KIT / "adapters" / "build.py"
MANIFEST = ".factory/adapters/generated.json"
POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="the launcher tests run sh")


def built(tmp_path: Path, roles: list[str] | None = None) -> Path:
    """A repo whose tool files were built and are current."""
    root = repo_with(tmp_path, ["verifier", "retro"] if roles is None else roles)
    build.write(root)
    return root


def check(root: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, list[str]]:
    capsys.readouterr()
    code = build.main(["--root", str(root), "--check"])
    return code, capsys.readouterr().out.splitlines()


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def drift(lines: list[str], kind: str) -> list[str]:
    """The paths of the lines that report `kind`, as `<path>: <kind>...`."""
    return [line.split(": ")[0] for line in lines if line.split(": ")[1:2] == [kind]]


# --- AC-08: build.py --check --------------------------------------------------------------------


@pytest.mark.ac("E12-AC-08")
def test_check_exits_0_when_every_file_is_current(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, lines = check(built(tmp_path), capsys)
    assert code == 0, lines
    assert not any(": " in line for line in lines), lines


@pytest.mark.ac("E12-AC-08")
def test_a_missing_file_is_named(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = built(tmp_path)
    (root / ".github" / "agents" / "retro.agent.md").unlink()
    code, lines = check(root, capsys)
    assert code == 1
    assert drift(lines, "missing") == [".github/agents/retro.agent.md"]
    assert len([line for line in lines if ": " in line]) == 1, lines


@pytest.mark.ac("E12-AC-08")
def test_a_stale_file_is_named(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = built(tmp_path)
    target = root / ".claude" / "agents" / "verifier.md"
    target.write_text(target.read_text(encoding="utf-8") + "hand edit\n", encoding="utf-8")
    code, lines = check(root, capsys)
    assert code == 1
    assert drift(lines, "stale") == [".claude/agents/verifier.md"]


@pytest.mark.ac("E12-AC-08")
def test_an_edited_source_makes_its_files_stale(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = built(tmp_path)
    source = root / ".factory" / "skills" / "handoff" / "SKILL.md"
    source.write_text(source.read_text(encoding="utf-8") + "\nOne more line.\n", encoding="utf-8")
    code, lines = check(root, capsys)
    assert code == 1
    assert sorted(drift(lines, "stale")) == [
        ".claude/skills/handoff/SKILL.md",
        ".cursor/skills/handoff/SKILL.md",
        MANIFEST,
        ".github/skills/handoff/SKILL.md",
    ]


@pytest.mark.ac("E12-AC-08")
def test_a_file_no_longer_produced_is_named_as_extra(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = built(tmp_path)
    (root / ".factory" / "agents" / "core" / "retro.md").unlink()
    code, lines = check(root, capsys)
    assert code == 1
    assert sorted(drift(lines, "extra")) == [
        ".claude/agents/retro.md",
        ".cursor/agents/retro.md",
        ".github/agents/retro.agent.md",
    ]


@pytest.mark.ac("E12-AC-08")
def test_a_dropped_tool_makes_its_files_extra(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = built(tmp_path)
    (root / ".agentic").mkdir(exist_ok=True)
    (root / ".agentic" / "config.toml").write_text(
        '[adapters]\ntools = ["claude-code", "copilot"]\n', encoding="utf-8"
    )
    code, lines = check(root, capsys)
    assert code == 1
    extra = drift(lines, "extra")
    assert extra and all(path.startswith(".cursor/") for path in extra), extra


@pytest.mark.ac("E12-AC-08")
def test_a_missing_manifest_is_named(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = built(tmp_path)
    (root / MANIFEST).unlink()
    code, lines = check(root, capsys)
    assert code == 1
    assert drift(lines, "missing") == [MANIFEST]


@pytest.mark.ac("E12-AC-08")
def test_check_writes_nothing_even_when_files_drift(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = built(tmp_path)
    (root / ".github" / "agents" / "retro.agent.md").unlink()
    (root / ".factory" / "agents" / "core" / "verifier.md").write_text(
        (root / ".factory" / "agents" / "core" / "verifier.md").read_text(encoding="utf-8")
        + "\nNew line.\n",
        encoding="utf-8",
    )
    before = snapshot(root)
    code, _ = check(root, capsys)
    assert code == 1
    assert snapshot(root) == before


@pytest.mark.ac("E12-AC-08")
def test_check_never_names_a_repos_own_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = built(tmp_path)
    (root / ".claude" / "agents" / "my-own.md").write_text("hand written\n", encoding="utf-8")
    (root / ".github" / "skills" / "mine").mkdir()
    (root / ".github" / "skills" / "mine" / "SKILL.md").write_text("mine\n", encoding="utf-8")
    assert check(root, capsys)[0] == 0


@pytest.mark.ac("E12-AC-08")
def test_a_crlf_checkout_of_a_current_file_is_not_stale(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Git on Windows may check text files out with CRLF; the manifest's hashes are LF-normalised.
    root = built(tmp_path)
    target = root / ".cursor" / "agents" / "verifier.md"
    target.write_bytes(target.read_bytes().replace(b"\n", b"\r\n"))
    assert check(root, capsys)[0] == 0


@pytest.mark.ac("E12-AC-08")
def test_check_with_a_bad_config_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = built(tmp_path)
    (root / ".agentic").mkdir(exist_ok=True)
    (root / ".agentic" / "config.toml").write_text(
        '[adapters]\ntools = ["vim"]\n', encoding="utf-8"
    )
    capsys.readouterr()
    assert build.main(["--root", str(root), "--check"]) == 2
    assert "adapters.tools" in capsys.readouterr().err


@pytest.mark.ac("E12-AC-08")
def test_check_runs_as_a_script(tmp_path: Path) -> None:
    root = built(tmp_path)
    (root / ".cursor" / "agents" / "retro.md").unlink()
    result = subprocess.run(
        [sys.executable, str(BUILD_PY), "--root", str(root), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result
    assert ".cursor/agents/retro.md: missing" in result.stdout


# --- AC-08: the gate step -----------------------------------------------------------------------

STATE = """+++
phase = "build"
track = "full"
active_task = ""
blockers = []
updated = 2026-11-19T08:00:00Z
+++
"""


def gate_repo_with_adapters(tmp_path: Path, *, with_build_py: bool = True) -> Path:
    """A gate fixture repo with the kit's state, agents and adapter modules, one role and skill."""
    root = gate_repo(
        tmp_path / "repo",
        {
            "py.toml": profile(
                "py", ["marker.txt"], {"format": touches("ran-format.txt"), "lint": PASS}
            )
        },
        files={"marker.txt": "x\n", ".agentic/STATE.md": STATE},
    )
    modules = ["state/state.py", "agents/agents.py"]
    modules += ["adapters/build.py"] if with_build_py else []
    for rel in [*modules, "agents/core/verifier.md", "skills/handoff/SKILL.md"]:
        (root / ".factory" / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(KIT / rel, root / ".factory" / rel)
    if with_build_py:
        build.write(root)
    return root


def gate_json(
    root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *args: str
) -> tuple[int, dict[str, object]]:
    capsys.readouterr()
    monkeypatch.chdir(root)
    code = gate.main(["--json", *args])
    return code, json.loads(capsys.readouterr().out)


def adapters_of(report: dict[str, object]) -> dict[str, object]:
    section = report["adapters"]
    assert isinstance(section, dict)
    return section


@pytest.mark.ac("E12-AC-08")
def test_the_gate_reports_current_tool_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = gate_repo_with_adapters(tmp_path)
    code, report = gate_json(root, monkeypatch, capsys)
    assert code == 0, report
    assert adapters_of(report) == {"files": len(build.build(root)), "problems": []}
    assert report["verdict"] == "pass"


@pytest.mark.ac("E12-AC-08")
def test_drift_fails_the_verdict_but_the_checks_still_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = gate_repo_with_adapters(tmp_path)
    (root / ".cursor" / "agents" / "verifier.md").unlink()
    code, report = gate_json(root, monkeypatch, capsys)
    assert code == 1
    assert report["verdict"] == "fail"
    problems = adapters_of(report)["problems"]
    assert problems == [".cursor/agents/verifier.md: missing"]
    assert (root / "ran-format.txt").exists(), "the checks still run (ADR 0020)"


@pytest.mark.ac("E12-AC-08")
def test_the_text_report_shows_adapter_status_after_the_docs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = gate_repo_with_adapters(tmp_path)
    files = len(build.build(root))
    code, output = run_gate(root, monkeypatch, capsys)
    assert code == 0, output
    assert f"Adapters: {files} files, 0 stale" in output
    stale = root / ".github" / "agents" / "verifier.agent.md"
    stale.write_text("edited\n", encoding="utf-8")
    code, output = run_gate(root, monkeypatch, capsys)
    assert code == 1, output
    assert f"Adapters: {files} files, 1 stale" in output
    assert "  .github/agents/verifier.agent.md: stale" in output
    lines = output.splitlines()
    docs = next(i for i, line in enumerate(lines) if line.startswith("Docs: "))
    adapters = next(i for i, line in enumerate(lines) if line.startswith("Adapters: "))
    assert docs < adapters
    assert output.rstrip().endswith("FAIL")


@pytest.mark.ac("E12-AC-08")
def test_the_drift_check_runs_with_checks_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = gate_repo_with_adapters(tmp_path)
    (root / ".claude" / "agents" / "verifier.md").unlink()
    code, report = gate_json(root, monkeypatch, capsys, "--checks", "lint")
    assert code == 1
    assert adapters_of(report)["problems"] == [".claude/agents/verifier.md: missing"]


@pytest.mark.ac("E12-AC-08")
def test_a_kit_without_build_py_skips_the_drift_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = gate_repo_with_adapters(tmp_path, with_build_py=False)
    code, report = gate_json(root, monkeypatch, capsys)
    assert code == 0, report
    assert adapters_of(report)["problems"] == []
    assert not (root / ".claude").exists()


@pytest.mark.ac("E12-AC-08")
def test_a_bad_adapters_config_stops_the_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = gate_repo_with_adapters(tmp_path)
    (root / ".agentic" / "config.toml").write_text(
        '[adapters]\ntools = ["vim"]\n', encoding="utf-8"
    )
    code, output = run_gate(root, monkeypatch, capsys)
    assert code == 2, output
    assert "adapters.tools" in output
    assert not (root / "ran-format.txt").exists()


# --- AC-09: install.py check reports drift ------------------------------------------------------


@pytest.mark.ac("E12-AC-09")
def test_install_check_reports_drift(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = git_repo(tmp_path / "repo")
    assert cli.main([str(repo)]) == 0
    capsys.readouterr()
    assert cli.main(["check", str(repo)]) == 0, capsys.readouterr()
    (repo / ".github" / "agents" / "verifier.agent.md").unlink()
    stale = repo / ".cursor" / "skills" / "handoff" / "SKILL.md"
    stale.write_text("edited\n", encoding="utf-8")
    assert cli.main(["check", str(repo)]) == 1
    out = capsys.readouterr().out
    assert ".github/agents/verifier.agent.md: missing" in out
    assert ".cursor/skills/handoff/SKILL.md: stale" in out
    assert "2 errors" in out


@pytest.mark.ac("E12-AC-09")
def test_install_check_skips_drift_without_build_py(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path / "repo")
    assert cli.main([str(repo)]) == 0
    (repo / ".factory" / "adapters" / "build.py").unlink()
    shutil.rmtree(repo / ".cursor")
    capsys.readouterr()
    assert cli.main(["check", str(repo)]) == 0, capsys.readouterr()


@pytest.mark.ac("E12-AC-09")
def test_reinstalling_clears_the_drift(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = git_repo(tmp_path / "repo")
    assert cli.main([str(repo)]) == 0
    (repo / ".claude" / "agents" / "verifier.md").unlink()
    assert cli.main([str(repo)]) == 0
    capsys.readouterr()
    assert cli.main(["check", str(repo)]) == 0, capsys.readouterr()


# --- AC-10: done-when: one role, three tools ----------------------------------------------------

ONE_ROLE = "checker"
ONE_ROLE_TOOLS = ["read", "search"]


def one_role_repo(root: Path) -> Path:
    """E03's fixture repo with a single role source, built for all three tools."""
    make_repo(root)
    for path in (root / AGENTS_REL / "core").glob("*.md"):
        path.unlink()
    (root / AGENTS_REL / "core" / f"{ONE_ROLE}.md").write_text(
        role(ONE_ROLE, ONE_ROLE_TOOLS), encoding="utf-8", newline="\n"
    )
    for rel in ("agents.py", "claude-hook", "copilot-hook", "cursor-hook"):
        shutil.copyfile(KIT / "agents" / rel, root / AGENTS_REL / rel)
    (root / ".factory" / "state").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(KIT / "state" / "state.py", root / ".factory" / "state" / "state.py")
    build.write(root)
    return root


@pytest.mark.ac("E12-AC-10")
def test_done_when_one_role_source_builds_for_all_three_tools(tmp_path: Path) -> None:
    root = one_role_repo(tmp_path / "repo")
    claude_data, claude_body = front(
        (root / ".claude" / "agents" / f"{ONE_ROLE}.md").read_text(encoding="utf-8")
    )
    assert claude_data == {
        "name": ONE_ROLE,
        "description": "A fixture role.",
        "tools": ", ".join(t for tool in ONE_ROLE_TOOLS for t in CLAUDE[tool]),
    }
    copilot_data, copilot_body = front(
        (root / ".github" / "agents" / f"{ONE_ROLE}.agent.md").read_text(encoding="utf-8")
    )
    assert copilot_data == {
        "name": ONE_ROLE,
        "description": "A fixture role.",
        "tools": [COPILOT[tool] for tool in ONE_ROLE_TOOLS],
    }
    cursor_data, cursor_body = front(
        (root / ".cursor" / "agents" / f"{ONE_ROLE}.md").read_text(encoding="utf-8")
    )
    assert cursor_data == {"name": ONE_ROLE, "description": "A fixture role."}
    assert claude_body == copilot_body == cursor_body
    source = f"{AGENTS_REL}/core/{ONE_ROLE}.md"
    assert claude_body.startswith(f"<!-- Generated by .factory/adapters/build.py from {source}.")
    assert [str(p) for p in agents.validate(root)] == []


@pytest.mark.ac("E12-AC-10")
def test_done_when_an_out_of_list_call_is_denied_by_all_three_hooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = one_role_repo(tmp_path / "repo")
    monkeypatch.chdir(root)
    as_claude = {**claude(root, "Bash", command="ls"), "agent_type": ONE_ROLE}
    code, out, err = run_hook(monkeypatch, capsys, "claude-code", as_claude)
    assert (code, out) == (2, "")
    assert f"{ONE_ROLE} may not use run" in err
    as_copilot = {**copilot(root, "bash", command="ls"), "agentType": ONE_ROLE}
    code, out, _ = run_hook(monkeypatch, capsys, "copilot", as_copilot)
    assert f"{ONE_ROLE} may not use run" in copilot_denied(code, out)
    code, out, _ = run_hook(
        monkeypatch, capsys, "cursor", cursor(root, "Shell", command="ls"), ONE_ROLE
    )
    assert f"{ONE_ROLE} may not use run" in cursor_denied(code, out)


@pytest.mark.ac("E12-AC-10")
def test_done_when_an_in_list_call_is_allowed_by_all_three_hooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = one_role_repo(tmp_path / "repo")
    monkeypatch.chdir(root)
    as_claude = {**claude(root, "Read", file_path="src/app.py"), "agent_type": ONE_ROLE}
    assert run_hook(monkeypatch, capsys, "claude-code", as_claude) == (0, "", "")
    as_copilot = {**copilot(root, "view", path="src/app.py"), "agentType": ONE_ROLE}
    assert run_hook(monkeypatch, capsys, "copilot", as_copilot) == (0, "", "")
    as_cursor = cursor(root, "Read", file_path="src/app.py")
    assert run_hook(monkeypatch, capsys, "cursor", as_cursor, ONE_ROLE) == (0, "", "")


def config_command(root: Path, tool: str) -> list[str]:
    """The command each tool's generated hook config runs, as argv."""
    if tool == "claude-code":
        data = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))
        command = data["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        command = command.replace('"$CLAUDE_PROJECT_DIR/', "").rstrip('"')
    elif tool == "copilot":
        data = json.loads((root / ".github" / "hooks" / "factory.json").read_text("utf-8"))
        command = data["hooks"]["preToolUse"][0]["bash"]
    else:
        data = json.loads((root / ".cursor" / "hooks.json").read_text(encoding="utf-8"))
        command = data["hooks"]["preToolUse"][0]["command"]
    return str(command).split()


@POSIX_ONLY
@pytest.mark.ac("E12-AC-10")
@pytest.mark.parametrize("tool", ["claude-code", "copilot", "cursor"])
def test_done_when_each_generated_hook_config_runs_and_answers(tmp_path: Path, tool: str) -> None:
    root = one_role_repo(tmp_path / "repo")
    env = {k: v for k, v in os.environ.items() if k not in ("FACTORY_ROLE", "CLAUDE_PROJECT_DIR")}
    if tool == "cursor":
        env["FACTORY_ROLE"] = ONE_ROLE
    payloads = {
        "claude-code": (
            {**claude(root, "Bash", command="ls"), "agent_type": ONE_ROLE},
            {**claude(root, "Read", file_path="src/app.py"), "agent_type": ONE_ROLE},
        ),
        "copilot": (
            {**copilot(root, "bash", command="ls"), "agentType": ONE_ROLE},
            {**copilot(root, "view", path="src/app.py"), "agentType": ONE_ROLE},
        ),
        "cursor": (
            cursor(root, "Shell", command="ls"),
            cursor(root, "Read", file_path="src/app.py"),
        ),
    }
    denied_call, allowed_call = payloads[tool]
    argv = config_command(root, tool)

    def run(payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            argv,
            cwd=root,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    no = run(denied_call)
    assert no.returncode == 2, no
    if tool == "copilot":
        copilot_denied(no.returncode, no.stdout)
    elif tool == "cursor":
        cursor_denied(no.returncode, no.stdout)
    else:
        assert f"{ONE_ROLE} may not use run" in no.stderr
    yes = run(allowed_call)
    assert (yes.returncode, yes.stdout) == (0, ""), yes


# --- AC-12: dogfooding and quality --------------------------------------------------------------


@pytest.mark.ac("E12-AC-12")
def test_this_repos_drift_check_passes(capsys: pytest.CaptureFixture[str]) -> None:
    code, lines = check(REPO_ROOT, capsys)
    assert code == 0, lines


@pytest.mark.ac("E12-AC-12")
def test_this_repos_installed_build_py_is_the_kits() -> None:
    installed = REPO_ROOT / ".factory" / "adapters" / "build.py"
    assert installed.read_bytes() == BUILD_PY.read_bytes()


@pytest.mark.ac("E12-AC-12")
def test_ci_runs_the_full_gate_and_so_the_drift_check_on_three_oses() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "factory-gate.yml").read_text("utf-8")
    assert "os: [ubuntu-latest, windows-latest, macos-latest]" in workflow
    runs = [line for line in workflow.splitlines() if ".factory/gates/gate.py" in line]
    assert runs and all("--checks" not in line for line in runs), runs


@pytest.mark.ac("E12-AC-12")
def test_build_py_imports_only_the_standard_library() -> None:
    tree = ast.parse(BUILD_PY.read_text(encoding="utf-8"))
    top: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            top |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            top.add(node.module.split(".")[0])
    assert sorted(n for n in top if n not in sys.stdlib_module_names) == []
