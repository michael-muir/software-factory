"""E11/T4: the done-when and dogfooding. The `standards-review` fixture is redone against the
kit's real `python` pack; this repo installs the packs, keeps its own `house` pack and sets
`[standards]`; and every E11 AC has a test.

Covers E11 AC-15 to AC-17. Expectations come from the E11 spec, the design note
(`docs/design/E11-standards-design.md`) and ADRs 0034 to 0036, not from the implementation.
"""

from __future__ import annotations

import ast
import re
import shutil
import sys
import tomllib
from pathlib import Path

import pytest

import gate
import standards
import state
from factory_installer import cli
from factory_installer.kit import load_kit
from tests._ac import COLLECTED_AC_IDS, REPO_ROOT, spec_ac_ids
from tests._kits import make_kit
from tests._repo import KIT_FILES, git_repo

KIT = REPO_ROOT / "kit"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "skills" / "standards-review"
PYTHON_PACK = ".factory/standards/python/rules.md"
STANDARDS_PY = ".factory/standards/standards.py"
HOUSE = ".factory/standards/house/rules.md"
PACKS = (
    "python",
    "typescript",
    "javascript",
    "cpp",
    "go",
    "rust",
    "csharp",
    "lua",
    "unreal",
    "shell",
    "tests",
    "docs",
)
LOCATION = re.compile(r"^([\w./-]+\.\w+):(\d+) ")


def findings(root: Path) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    for path in sorted((root / ".agentic" / "tasks").glob("*.md")):
        parsed = state.parse(path.read_text(encoding="utf-8"))
        assert not isinstance(parsed, str), parsed
        listed = parsed[0].get("findings", [])
        assert isinstance(listed, list)
        found += [f for f in listed if isinstance(f, dict)]
    return found


def new_findings() -> list[dict[str, object]]:
    before = findings(FIXTURE / "before")
    added = [f for f in findings(FIXTURE / "after") if f not in before]
    assert added, "the review recorded no finding"
    return added


def kit_python_rules() -> dict[str, standards.Rule]:
    pack, problems = standards.read_pack(KIT / PYTHON_PACK, PYTHON_PACK)
    assert pack is not None and problems == []
    return {r.id: r for r in pack.rules if r.severity != "retired"}


def added_lines() -> dict[str, dict[int, str]]:
    """The reviewed slice's diff (`slice.diff`): file -> {line number: text} of its added lines."""
    added: dict[str, dict[int, str]] = {}
    current = ""
    number = 0
    for line in (FIXTURE / "slice.diff").read_text(encoding="utf-8").split("\n"):
        if line.startswith("+++ "):
            current = line[4:].removeprefix("b/")
            added[current] = {}
        elif line.startswith("@@ "):
            match = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            assert match, line
            number = int(match.group(1))
        elif line.startswith("+") and current:
            added[current][number] = line[1:]
            number += 1
        elif line.startswith(" ") and current:
            number += 1
    return added


# --- AC-15: the done-when -----------------------------------------------------------------------


@pytest.mark.ac("E11-AC-15")
@pytest.mark.parametrize("side", ["before", "after"])
def test_the_fixture_installs_the_kits_python_pack_and_module(side: str) -> None:
    root = FIXTURE / side
    for rel in (PYTHON_PACK, STANDARDS_PY):
        assert (root / rel).read_bytes() == (KIT / rel).read_bytes(), rel


@pytest.mark.ac("E11-AC-15")
def test_every_new_finding_cites_a_rule_in_force_in_the_shipped_python_pack(
    tmp_path: Path,
) -> None:
    rules = kit_python_rules()
    after = shutil.copytree(FIXTURE / "after", tmp_path / "after")
    for finding in new_findings():
        rule = finding.get("rule")
        assert isinstance(rule, str), finding
        assert rule in rules, rule
        assert standards.rule_in_force(after, rule) is None, rule
        assert finding["severity"] == rules[rule].severity, finding


@pytest.mark.ac("E11-AC-15")
def test_each_findings_location_is_an_added_line_of_the_slices_diff() -> None:
    added = added_lines()
    for finding in new_findings():
        match = LOCATION.match(str(finding["summary"]))
        assert match, finding["summary"]
        path, line = match.group(1), int(match.group(2))
        assert line in added.get(path, {}), f"{path}:{line} is not in the slice's diff"


@pytest.mark.ac("E11-AC-15")
def test_the_slices_diff_is_the_change_in_the_before_repo() -> None:
    added = added_lines()
    assert set(added) == {"src/greet.py", "tests/test_greet.py"}
    for path, lines in added.items():
        text = (FIXTURE / "before" / path).read_text(encoding="utf-8")
        assert [lines[n] for n in sorted(lines)] == text.rstrip("\n").split("\n"), path


@pytest.mark.ac("E11-AC-15")
def test_select_on_the_slice_lists_the_python_pack_with_every_cited_rule(
    tmp_path: Path,
) -> None:
    before = shutil.copytree(FIXTURE / "before", tmp_path / "before")
    chosen = standards.select(before, sorted(added_lines()))
    assert [s.pack.name for s in chosen] == ["python"]
    in_force = {r.id for r in chosen[0].rules}
    assert {str(f["rule"]) for f in new_findings()} <= in_force


@pytest.mark.ac("E11-AC-15")
@pytest.mark.parametrize("side", ["before", "after"])
def test_state_check_and_standards_check_pass_on_the_fixture(tmp_path: Path, side: str) -> None:
    root = shutil.copytree(FIXTURE / side, tmp_path / side)
    assert [str(p) for p in state.validate(root)] == []
    assert [str(p) for p in standards.validate(root)] == []


@pytest.mark.ac("E11-AC-15")
def test_the_run_record_follows_the_skill_with_the_real_ids() -> None:
    run = (FIXTURE / "RUN.md").read_text(encoding="utf-8")
    assert "standards.py select" in run
    assert "--rule" in run
    cited = set(re.findall(r"\bPY-\d{3}\b", run))
    assert cited == {str(f["rule"]) for f in new_findings()}


# --- AC-16: installing and dogfooding -----------------------------------------------------------


@pytest.mark.ac("E11-AC-16")
def test_the_packs_and_standards_py_are_kit_files() -> None:
    kit = load_kit(KIT)
    managed = {rel for rel in kit.files if kit.is_kit_managed(rel)}
    expected = {STANDARDS_PY, *(f".factory/standards/{p}/rules.md" for p in PACKS)}
    assert expected <= managed, sorted(expected - managed)
    assert HOUSE not in managed


@pytest.mark.ac("E11-AC-16")
def test_a_fresh_install_holds_every_pack_and_passes_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path / "repo")
    assert cli.main([str(repo)]) == 0
    for name in PACKS:
        rel = f".factory/standards/{name}/rules.md"
        assert (repo / rel).read_bytes() == (KIT / rel).read_bytes(), rel
    assert (repo / HOUSE).is_file()
    assert [str(p) for p in standards.validate(repo)] == []
    capsys.readouterr()
    assert cli.main(["check", str(repo)]) == 0, capsys.readouterr().out


@pytest.mark.ac("E11-AC-16")
def test_a_repos_edit_to_a_kit_pack_is_kept_on_upgrade(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path / "repo")
    assert cli.main([str(repo)]) == 0
    ours = (repo / PYTHON_PACK).read_text(encoding="utf-8") + "\nOur own note.\n"
    (repo / PYTHON_PACK).write_text(ours, encoding="utf-8", newline="\n")
    newer = (KIT / PYTHON_PACK).read_bytes() + b"\nA newer kit note.\n"
    v2 = make_kit(tmp_path, "0.9.0", {PYTHON_PACK: newer})
    assert cli.main([str(repo), "--kit", str(v2)]) == 0
    assert (repo / PYTHON_PACK).read_text(encoding="utf-8") == ours


@pytest.mark.ac("E11-AC-16")
def test_this_repo_installs_every_kit_pack_and_the_module() -> None:
    for rel in (STANDARDS_PY, *(f".factory/standards/{p}/rules.md" for p in PACKS)):
        assert (REPO_ROOT / rel).read_bytes() == (KIT / rel).read_bytes(), rel


@pytest.mark.ac("E11-AC-16")
def test_this_repos_house_pack_has_at_least_five_rules_of_its_own() -> None:
    pack, problems = standards.read_pack(REPO_ROOT / HOUSE, HOUSE)
    assert pack is not None and problems == []
    assert pack.prefix == "HOUSE"
    in_force = [r for r in pack.rules if r.severity != "retired"]
    assert len(in_force) >= 5
    assert (REPO_ROOT / HOUSE).read_bytes() != (KIT / HOUSE).read_bytes()


@pytest.mark.ac("E11-AC-16")
def test_this_repo_sets_the_standards_table() -> None:
    data = tomllib.loads((REPO_ROOT / ".agentic" / "config.toml").read_text(encoding="utf-8"))
    table = data["standards"]
    assert isinstance(table["packs"], dict)
    assert isinstance(table["ignore"], list)


@pytest.mark.ac("E11-AC-16")
def test_this_repos_gate_validates_every_pack() -> None:
    assert (REPO_ROOT / STANDARDS_PY).is_file()
    assert gate.standards_problems(REPO_ROOT) == []
    names = {p.name for p in standards.load(REPO_ROOT).packs}
    assert names == {*PACKS, "house"}


# --- AC-17: quality and coverage ----------------------------------------------------------------


@pytest.mark.ac("E11-AC-17")
def test_standards_py_imports_only_the_standard_library() -> None:
    tree = ast.parse((KIT / STANDARDS_PY).read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
    foreign = sorted({n.split(".")[0] for n in names} - set(sys.stdlib_module_names))
    assert not foreign, foreign


@pytest.mark.ac("E11-AC-17")
def test_the_kit_layout_lists_the_standards_files() -> None:
    expected = {STANDARDS_PY, *(f".factory/standards/{p}/rules.md" for p in PACKS)}
    assert expected <= KIT_FILES, sorted(expected - KIT_FILES)


@pytest.mark.ac("E11-AC-17")
def test_the_e11_spec_defines_ac_01_to_ac_17() -> None:
    assert spec_ac_ids("E11") == {f"E11-AC-{n:02d}" for n in range(1, 18)}


@pytest.mark.ac("E11-AC-17")
def test_every_e11_ac_has_a_test(request: pytest.FixtureRequest) -> None:
    missing = spec_ac_ids("E11") - request.config.stash[COLLECTED_AC_IDS]
    assert not missing, f"E11 ACs with no test: {sorted(missing)}"
