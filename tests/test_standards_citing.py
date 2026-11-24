"""E11/T3: citing rules. `standards.py select` and `rule_in_force`, `state.py finding add --rule`
and the findings' `rule` field, the rule in `resume` and `evidence.py`, and the reviewer's skill
and card.

Covers E11 AC-07, AC-08 and AC-12 to AC-14. Expectations come from the E11 spec, the design note
(`docs/design/E11-standards-design.md`) and ADRs 0034 and 0035, not from the implementation. The
packs here are small fixture packs; the kit's real packs are T2's and T4's.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import agents
import evidence
import standards
import state
from tests._ac import REPO_ROOT
from tests._gate import PASS, gate_repo, git, profile, run_gate
from tests._standards import pack, rows, write_packs

KIT = REPO_ROOT / "kit"
STANDARDS_PY = KIT / ".factory" / "standards" / "standards.py"
GATE_PY = KIT / ".factory" / "gates" / "gate.py"
STATE_PY = KIT / ".factory" / "state" / "state.py"
SKILL = ".factory/skills/standards-review/SKILL.md"
CARD = ".factory/agents/core/standards-reviewer.md"
PYTHONS = ("python", "python3", "py", "uv run python")
URL = "https://example.com/alpha/"
TASK = "E42-T1"
TASK_REL = f".agentic/tasks/{TASK}.md"

ALPHA_ROWS = [
    *rows("AL"),
    ("AL-004", "retired", "An old rule.", "No longer in force.", f"[s4]({URL}#4)"),
]


def fixture_packs() -> dict[str, str]:
    """Five packs: by extension, a C++ pair where `ue` replaces `cee`, and one for every path."""
    return {
        "alpha": pack("alpha", prefix="AL", applies_to=("*.py",), table=ALPHA_ROWS),
        "beta": pack("beta", title="Beta pack", prefix="BE", applies_to=("*.ts",)),
        "cee": pack("cee", title="Cee pack", prefix="CE", applies_to=("*.cc", "*.h")),
        "ue": pack(
            "ue",
            title="Ue pack",
            prefix="UE",
            applies_to=("*.cc", "*.h"),
            extra='detect = ["*.uproject"]\nreplaces = ["cee"]',
        ),
        "every": pack("every", title="Every pack", prefix="EV", applies_to=("*",)),
    }


def config(packs: str = "{}", ignore: str = "[]", gates: str = "") -> str:
    return f"{gates}[standards]\npacks = {packs}\nignore = {ignore}\n"


def standards_repo(root: Path, conf: str | None = None) -> Path:
    write_packs(root, fixture_packs(), config() if conf is None else conf)
    assert [str(p) for p in standards.validate(root)] == []
    return root


def chosen(root: Path, files: list[str]) -> dict[str, tuple[list[str], list[str]]]:
    """pack name -> (its files, the ids of its rules in force), in the order select gives."""
    return {s.pack.name: (s.files, [r.id for r in s.rules]) for s in standards.select(root, files)}


def run_select(root: Path, capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str]:
    code = standards.main(["--root", str(root), "select", *args])
    out = capsys.readouterr()
    return code, out.out + out.err


AL_RULES = ["AL-001", "AL-002", "AL-003"]


# --- AC-07: select ------------------------------------------------------------------------------


@pytest.mark.ac("E11-AC-07")
@pytest.mark.ac("E11-AC-08")
def test_select_lists_each_pack_that_applies_with_its_files_and_rules(tmp_path: Path) -> None:
    root = standards_repo(tmp_path)
    found = chosen(root, ["src/a.py", "web/b.ts", "README.md"])
    assert list(found) == ["alpha", "beta", "every"]
    assert found["alpha"] == (["src/a.py"], AL_RULES)
    assert found["beta"] == (["web/b.ts"], ["BE-001", "BE-002", "BE-003"])
    assert found["every"] == (["README.md", "src/a.py", "web/b.ts"], ["EV-001", "EV-002", "EV-003"])


@pytest.mark.ac("E11-AC-07")
def test_select_carries_the_whole_pack_and_rule(tmp_path: Path) -> None:
    root = standards_repo(tmp_path)
    first = standards.select(root, ["a.py"])[0]
    assert (first.pack.name, first.pack.title, first.pack.prefix) == ("alpha", "Alpha pack", "AL")
    rule = first.rules[1]
    assert (rule.id, rule.severity, rule.text) == ("AL-002", "major", rows("AL")[1][2])


@pytest.mark.ac("E11-AC-07")
def test_select_is_deterministic_whatever_the_order_of_the_files(tmp_path: Path) -> None:
    root = standards_repo(tmp_path)
    one = chosen(root, ["z.py", "a.ts", "m.py"])
    two = chosen(root, ["m.py", "a.ts", "z.py", "m.py"])
    assert one == two
    assert one["alpha"][0] == ["m.py", "z.py"]


@pytest.mark.ac("E11-AC-07")
def test_select_takes_paths_as_repo_relative_posix_paths(tmp_path: Path) -> None:
    root = standards_repo(tmp_path)
    assert chosen(root, ["./src/a.py", "src\\b.py"])["alpha"][0] == ["src/a.py", "src/b.py"]


@pytest.mark.ac("E11-AC-07")
def test_no_files_means_no_packs(tmp_path: Path) -> None:
    assert standards.select(standards_repo(tmp_path), []) == []


@pytest.mark.ac("E11-AC-07")
def test_the_text_output_shows_each_packs_files_and_rules_in_force(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = standards_repo(tmp_path)
    code, out = run_select(root, capsys, "web/b.ts", "a.py")
    al, be, ev = rows("AL"), rows("BE"), rows("EV")
    assert code == 0
    assert out == (
        "alpha (Alpha pack): 1 file\n"
        "  files: a.py\n"
        f"  AL-001 [blocker] {al[0][2]}\n"
        f"  AL-002 [major] {al[1][2]}\n"
        f"  AL-003 [minor] {al[2][2]}\n"
        "\n"
        "beta (Beta pack): 1 file\n"
        "  files: web/b.ts\n"
        f"  BE-001 [blocker] {be[0][2]}\n"
        f"  BE-002 [major] {be[1][2]}\n"
        f"  BE-003 [minor] {be[2][2]}\n"
        "\n"
        "every (Every pack): 2 files\n"
        "  files: a.py, web/b.ts\n"
        f"  EV-001 [blocker] {ev[0][2]}\n"
        f"  EV-002 [major] {ev[1][2]}\n"
        f"  EV-003 [minor] {ev[2][2]}\n"
    )


@pytest.mark.ac("E11-AC-07")
def test_the_text_output_says_when_no_pack_applies(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = standards_repo(tmp_path, config(packs="{every = false}"))
    assert run_select(root, capsys, "notes.txt") == (0, "no packs apply to these files\n")


@pytest.mark.ac("E11-AC-07")
def test_json_gives_the_same_as_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = standards_repo(tmp_path, config(packs="{every = false}"))
    code, out = run_select(root, capsys, "--json", "a.py")
    assert code == 0
    al = rows("AL")
    assert json.loads(out) == {
        "packs": [
            {
                "name": "alpha",
                "title": "Alpha pack",
                "files": ["a.py"],
                "rules": [{"id": r[0], "severity": r[1], "rule": r[2]} for r in al],
            }
        ]
    }
    assert run_select(root, capsys, "--json", "a.py") == (0, out)
    assert run_select(root, capsys, "--json", "notes.txt") == (0, '{\n  "packs": []\n}\n')


def changed_repo(root: Path, conf: str | None = None, branch: str = "main") -> Path:
    """A git repo whose `branch` holds the packs, gate.py and two files, then a branch `work`
    with a commit (a new file, a deletion), an unstaged edit and an untracked file."""
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", branch)
    standards_repo(root, conf)
    (root / ".factory" / "gates").mkdir(parents=True)
    shutil.copyfile(GATE_PY, root / ".factory" / "gates" / "gate.py")
    (root / "old.py").write_text("x = 1\n", encoding="utf-8")
    (root / "gone.py").write_text("y = 1\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    git(root, "switch", "-q", "-c", "work")
    (root / "src").mkdir()
    (root / "src" / "new.py").write_text("z = 1\n", encoding="utf-8")
    (root / "gone.py").unlink()
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "work")
    (root / "old.py").write_text("x = 2\n", encoding="utf-8")
    (root / "web").mkdir()
    (root / "web" / "x.ts").write_text("let x = 1;\n", encoding="utf-8")
    return root


CHANGED = {
    "alpha": ["old.py", "src/new.py"],
    "beta": ["web/x.ts"],
    "every": ["old.py", "src/new.py", "web/x.ts"],
}


def files_by_pack(out: str) -> dict[str, list[str]]:
    return {p["name"]: p["files"] for p in json.loads(out)["packs"]}


@pytest.mark.ac("E11-AC-07")
def test_base_ref_selects_for_the_files_changed_since_the_merge_base(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = changed_repo(tmp_path / "repo")
    code, out = run_select(root, capsys, "--base-ref", "main", "--json")
    assert code == 0, out
    assert files_by_pack(out) == CHANGED


@pytest.mark.ac("E11-AC-07")
def test_without_files_the_base_ref_is_gates_base_ref(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    conf = config(gates='[gates]\nbase_ref = "trunk"\n\n')
    root = changed_repo(tmp_path / "repo", conf, branch="trunk")
    code, out = run_select(root, capsys, "--json")
    assert code == 0, out
    assert files_by_pack(out) == CHANGED


@pytest.mark.ac("E11-AC-07")
def test_without_a_config_the_base_ref_is_main(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = changed_repo(tmp_path / "repo")
    (root / ".agentic" / "config.toml").unlink()
    code, out = run_select(root, capsys, "--json")
    assert code == 0, out
    assert files_by_pack(out) == CHANGED


@pytest.mark.ac("E11-AC-07")
def test_no_changed_files_says_so(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = changed_repo(tmp_path / "repo")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "rest")
    git(root, "switch", "-q", "main")
    code, out = run_select(root, capsys, "--base-ref", "main")
    assert (code, out) == (0, "no changed files, so no packs apply\n")


@pytest.mark.ac("E11-AC-07")
def test_an_unknown_base_ref_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = changed_repo(tmp_path / "repo")
    code, out = run_select(root, capsys, "--base-ref", "no-such-ref")
    assert code == 2
    assert "no-such-ref" in out


@pytest.mark.ac("E11-AC-07")
def test_without_a_gate_select_needs_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = standards_repo(tmp_path)
    code, out = run_select(root, capsys)
    assert code == 2
    assert "gate.py" in out and "FILE" in out
    assert run_select(root, capsys, "a.py")[0] == 0


@pytest.mark.ac("E11-AC-07")
def test_files_and_base_ref_together_are_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = standards_repo(tmp_path)
    with pytest.raises(SystemExit) as raised:
        standards.main(["--root", str(root), "select", "--base-ref", "main", "a.py"])
    assert raised.value.code == 2
    assert "--base-ref" in capsys.readouterr().err


@pytest.mark.ac("E11-AC-07")
def test_select_runs_as_a_script_and_prints_utf8_in_any_locale(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    table = [("NA-001", "major", "Prefer naïve code, never café.", "Ünïcode.", f"[s]({URL}#1)")]
    write_packs(root, {"nonascii": pack("nonascii", prefix="NA", table=table)})
    target = root / ".factory" / "standards" / "standards.py"
    shutil.copyfile(STANDARDS_PY, target)
    env = {**os.environ, "LC_ALL": "C", "PYTHONUTF8": "0"}
    env.pop("PYTHONIOENCODING", None)
    result = subprocess.run(
        [sys.executable, str(target), "select", "a.py"],
        cwd=root,
        capture_output=True,
        encoding="utf-8",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == (
        "nonascii (Alpha pack): 1 file\n"
        "  files: a.py\n"
        "  NA-001 [major] Prefer naïve code, never café.\n"
    )


# --- AC-08: when a pack applies ------------------------------------------------------------------


@pytest.mark.ac("E11-AC-08")
def test_a_pack_with_detect_markers_applies_only_when_they_are_at_the_root(
    tmp_path: Path,
) -> None:
    root = standards_repo(tmp_path)
    assert list(chosen(root, ["src/a.cc"])) == ["cee", "every"]
    (root / "src").mkdir()
    (root / "src" / "nested.uproject").write_text("{}\n", encoding="utf-8")
    assert list(chosen(root, ["src/a.cc"])) == ["cee", "every"]
    (root / "Game.uproject").write_text("{}\n", encoding="utf-8")
    assert list(chosen(root, ["src/a.cc"])) == ["every", "ue"]


@pytest.mark.ac("E11-AC-08")
def test_a_marker_folder_is_not_a_marker_file(tmp_path: Path) -> None:
    root = standards_repo(tmp_path)
    (root / "Game.uproject").mkdir()
    assert list(chosen(root, ["a.h"])) == ["cee", "every"]


@pytest.mark.ac("E11-AC-08")
def test_a_pack_that_is_not_matched_does_not_replace(tmp_path: Path) -> None:
    root = standards_repo(tmp_path)
    (root / "Game.uproject").write_text("{}\n", encoding="utf-8")
    assert list(chosen(root, ["a.py"])) == ["alpha", "every"]


@pytest.mark.ac("E11-AC-08")
def test_replaces_is_resolved_in_one_pass(tmp_path: Path) -> None:
    def chain(name: str, prefix: str, replaces: str) -> str:
        extra = f'replaces = ["{replaces}"]' if replaces else ""
        return pack(name, title=name, prefix=prefix, applies_to=("*.x",), extra=extra)

    write_packs(tmp_path, {"aa": chain("aa", "AA", "bb"), "bb": chain("bb", "BB", "cc")})
    write_packs(tmp_path, {"cc": chain("cc", "CC", "")})
    assert standards.validate(tmp_path) == []
    assert list(chosen(tmp_path, ["f.x"])) == ["aa", "cc"]


@pytest.mark.ac("E11-AC-08")
def test_config_switches_a_pack_off(tmp_path: Path) -> None:
    root = standards_repo(tmp_path, config(packs="{alpha = false, beta = true}"))
    assert list(chosen(root, ["a.py", "b.ts"])) == ["beta", "every"]


@pytest.mark.ac("E11-AC-08")
def test_the_every_change_packs_can_be_switched_off(tmp_path: Path) -> None:
    root = standards_repo(tmp_path, config(packs="{every = false}"))
    assert list(chosen(root, ["a.py"])) == ["alpha"]


@pytest.mark.ac("E11-AC-08")
def test_a_pack_switched_off_replaces_nothing(tmp_path: Path) -> None:
    root = standards_repo(tmp_path, config(packs="{ue = false}"))
    (root / "Game.uproject").write_text("{}\n", encoding="utf-8")
    assert list(chosen(root, ["a.cc"])) == ["cee", "every"]


@pytest.mark.ac("E11-AC-08")
def test_retired_and_ignored_rules_are_not_in_force(tmp_path: Path) -> None:
    root = standards_repo(tmp_path)
    assert chosen(root, ["a.py"])["alpha"][1] == AL_RULES
    write_packs(root, {}, config(ignore='["AL-002", "EV-003"]'))
    found = chosen(root, ["a.py"])
    assert found["alpha"][1] == ["AL-001", "AL-003"]
    assert found["every"][1] == ["EV-001", "EV-002"]


@pytest.mark.ac("E11-AC-08")
def test_a_pack_with_every_rule_out_of_force_still_applies(tmp_path: Path) -> None:
    root = standards_repo(tmp_path, config(ignore='["BE-001", "BE-002", "BE-003"]'))
    assert chosen(root, ["b.ts"])["beta"] == (["b.ts"], [])


# --- AC-12: rule_in_force, and finding add --rule ------------------------------------------------


@pytest.mark.ac("E11-AC-12")
def test_rule_in_force_gives_none_for_a_rule_in_force(tmp_path: Path) -> None:
    root = standards_repo(tmp_path)
    assert standards.rule_in_force(root, "AL-001") is None
    assert standards.rule_in_force(root, "UE-003") is None


@pytest.mark.ac("E11-AC-12")
@pytest.mark.parametrize(
    ("rule", "conf", "reason"),
    [
        ("AL-009", config(), "not a rule in an installed pack"),
        ("py-2", config(), "not a rule in an installed pack"),
        ("AL-004", config(), "retired"),
        ("AL-002", config(ignore='["AL-002"]'), "[standards].ignore"),
        ("BE-001", config(packs="{beta = false}"), "switched off in [standards].packs"),
    ],
    ids=["unknown", "malformed", "retired", "ignored", "switched-off"],
)
def test_rule_in_force_gives_the_reason_a_rule_is_not(
    tmp_path: Path, rule: str, conf: str, reason: str
) -> None:
    root = standards_repo(tmp_path, conf)
    why = standards.rule_in_force(root, rule)
    assert why is not None and reason in why


@pytest.mark.ac("E11-AC-12")
def test_the_switched_off_reason_names_the_pack(tmp_path: Path) -> None:
    root = standards_repo(tmp_path, config(packs="{beta = false}"))
    assert "beta" in str(standards.rule_in_force(root, "BE-002"))


@pytest.mark.ac("E11-AC-12")
def test_rule_in_force_with_no_packs_installed(tmp_path: Path) -> None:
    assert "not a rule" in str(standards.rule_in_force(tmp_path, "AL-001"))


def state_repo(root: Path, conf: str | None = None, *, module: bool = True) -> Path:
    """A root with STATE.md, task E42-T1, the fixture packs and (by default) standards.py."""
    assert state.main(["--root", str(root), "init"]) == 0
    assert state.main(["--root", str(root), "task", "new", TASK, "Widgets"]) == 0
    standards_repo(root, conf)
    if module:
        shutil.copyfile(STANDARDS_PY, root / ".factory" / "standards" / "standards.py")
    return root


def add(root: Path, *args: str) -> int:
    return state.main(["--root", str(root), "finding", "add", TASK, *args])


def task_findings(root: Path) -> list[dict[str, object]]:
    parsed = state.parse((root / TASK_REL).read_text(encoding="utf-8"))
    assert not isinstance(parsed, str), parsed
    value = parsed[0].get("findings", [])
    assert isinstance(value, list)
    return value


@pytest.mark.ac("E11-AC-12")
def test_finding_add_with_a_rule_stores_it_after_the_severity(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = state_repo(tmp_path)
    assert add(root, "--severity", "minor", "--rule", "AL-002", "src/a.py:3 names a type") == 0
    assert task_findings(root) == [
        {
            "id": "F1",
            "severity": "minor",
            "rule": "AL-002",
            "status": "open",
            "summary": "src/a.py:3 names a type",
        }
    ]
    text = (root / TASK_REL).read_text(encoding="utf-8")
    assert (
        '[[findings]]\nid = "F1"\nseverity = "minor"\nrule = "AL-002"\nstatus = "open"\n'
        'summary = "src/a.py:3 names a type"\n'
    ) in text
    assert [str(p) for p in state.validate(root)] == []
    assert "added F1" in capsys.readouterr().out


@pytest.mark.ac("E11-AC-12")
@pytest.mark.parametrize(
    ("rule", "conf", "reason"),
    [
        ("ZZ-001", config(), "not a rule"),
        ("AL-004", config(), "retired"),
        ("AL-001", config(ignore='["AL-001"]'), "ignore"),
        ("BE-001", config(packs="{beta = false}"), "switched off"),
    ],
    ids=["unknown", "retired", "ignored", "switched-off"],
)
def test_finding_add_refuses_a_rule_not_in_force(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], rule: str, conf: str, reason: str
) -> None:
    root = state_repo(tmp_path, conf)
    assert add(root, "--severity", "major", "a.py:1 first") == 0
    before = (root / TASK_REL).read_bytes()
    capsys.readouterr()
    assert add(root, "--severity", "major", "--rule", rule, "a.py:2 second") == 1
    err = capsys.readouterr().err
    assert rule in err and reason in err
    assert (root / TASK_REL).read_bytes() == before


@pytest.mark.ac("E11-AC-12")
def test_finding_add_refuses_a_rule_when_no_standards_module_is_installed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = state_repo(tmp_path, module=False)
    before = (root / TASK_REL).read_bytes()
    capsys.readouterr()
    assert add(root, "--severity", "minor", "--rule", "AL-001", "a.py:1 x") == 1
    assert "no standards packs installed" in capsys.readouterr().err
    assert (root / TASK_REL).read_bytes() == before


@pytest.mark.ac("E11-AC-12")
def test_finding_add_without_a_rule_works_as_before(tmp_path: Path) -> None:
    root = state_repo(tmp_path, module=False)
    assert add(root, "--severity", "minor", "a.py:1 x") == 0
    assert task_findings(root) == [
        {"id": "F1", "severity": "minor", "status": "open", "summary": "a.py:1 x"}
    ]
    assert "rule" not in (root / TASK_REL).read_text(encoding="utf-8")


@pytest.mark.ac("E11-AC-12")
def test_other_writes_keep_a_findings_rule(tmp_path: Path) -> None:
    root = state_repo(tmp_path)
    assert add(root, "--severity", "minor", "--rule", "AL-003", "a.py:1 x") == 0
    assert add(root, "--severity", "major", "a.py:2 y") == 0
    assert state.main(["--root", str(root), "finding", "set", TASK, "F1", "--status", "fixed"]) == 0
    assert state.main(["--root", str(root), "task", "set", TASK, "--round", "1"]) == 0
    found = task_findings(root)
    assert found[0] == {
        "id": "F1",
        "severity": "minor",
        "rule": "AL-003",
        "status": "fixed",
        "summary": "a.py:1 x",
    }
    assert "rule" not in found[1]


# --- AC-13: the findings schema, resume and evidence.py -----------------------------------------


def task_with(findings: list[dict[str, object]]) -> str:
    lines = [
        "+++",
        f'id = "{TASK}"',
        'title = "Widgets"',
        'status = "in-review"',
        "review_round = 1",
        "created = 2026-11-20T00:00:00Z",
        "updated = 2026-11-20T00:00:00Z",
    ]
    for finding in findings:
        lines += ["", "[[findings]]"]
        lines += [f"{key} = {json.dumps(value)}" for key, value in finding.items()]
    lines += ["+++", "", "## Goal", "", "Widgets.", "", "## Acceptance criteria", "", "## Notes"]
    return "\n".join(lines) + "\n"


RULED: dict[str, object] = {
    "id": "F1",
    "severity": "minor",
    "rule": "AL-002",
    "status": "open",
    "summary": "a.py:3 x",
}
PLAIN: dict[str, object] = {
    "id": "F2",
    "severity": "major",
    "status": "open",
    "summary": "a.py:4 y",
}


def tasked(root: Path, findings: list[dict[str, object]]) -> Path:
    assert state.main(["--root", str(root), "init"]) == 0
    (root / TASK_REL).parent.mkdir(parents=True, exist_ok=True)
    (root / TASK_REL).write_text(task_with(findings), encoding="utf-8", newline="\n")
    return root


@pytest.mark.ac("E11-AC-13")
def test_a_finding_with_or_without_a_rule_is_valid(tmp_path: Path) -> None:
    root = tasked(tmp_path, [RULED, PLAIN])
    assert [str(p) for p in state.validate(root)] == []
    assert state.main(["check", str(root)]) == 0


@pytest.mark.ac("E11-AC-13")
@pytest.mark.parametrize("bad", ["py-2", "PY-02", "PY-0002", "TOOLONG-001", "P-001", "", 7])
def test_a_malformed_rule_is_a_problem(tmp_path: Path, bad: object) -> None:
    root = tasked(tmp_path, [PLAIN, {**RULED, "id": "F3", "rule": bad}])
    found = [str(p) for p in state.validate(root)]
    assert len(found) == 1
    assert found[0].startswith(f"{TASK_REL}: findings[1].rule: ")
    assert state.main(["check", str(root)]) == 1


@pytest.mark.ac("E11-AC-13")
def test_state_check_accepts_a_retired_rule(tmp_path: Path) -> None:
    root = standards_repo(tasked(tmp_path, [{**RULED, "rule": "AL-004"}]))
    assert [str(p) for p in state.validate(root)] == []


@pytest.mark.ac("E11-AC-13")
@pytest.mark.parametrize(("rule", "code"), [("AL-002", 0), ("al-2", 2)])
def test_the_gate_accepts_a_rule_and_stops_on_a_malformed_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    rule: str,
    code: int,
) -> None:
    repo = gate_repo(
        tmp_path / "repo",
        {"py.toml": profile("py", ["marker.txt"], {"format": PASS})},
        files={
            "marker.txt": "x\n",
            TASK_REL: task_with([{**RULED, "rule": rule}]),
            ".factory/state/state.py": STATE_PY.read_text(encoding="utf-8"),
        },
    )
    exit_code, output = run_gate(repo, monkeypatch, capsys, "--checks", "format")
    assert exit_code == code, output
    if code:
        assert "findings[0].rule" in output


@pytest.mark.ac("E11-AC-13")
def test_resume_shows_the_rule_beside_the_severity(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tasked(tmp_path, [RULED, PLAIN])
    assert state.main(["--root", str(root), "start", TASK]) == 0
    capsys.readouterr()
    assert state.main(["--root", str(root), "resume"]) == 0
    out = capsys.readouterr().out
    assert "Open findings:\n  F1 [minor] AL-002 a.py:3 x\n  F2 [major] a.py:4 y\n" in out
    assert state.main(["--root", str(root), "resume", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["task"]["open_findings"] == [RULED, PLAIN]


SPEC = """# E42 · Widgets — Spec

Issue: [#42](https://example.com/issues/42) · Milestone: M1 · Depends on: none
Status: **Approved by the product owner** · Next: tests

## Acceptance criteria

- **AC-01** Widgets can be added.
"""
TESTS = """import pytest


@pytest.mark.ac("E42-AC-01")
def test_one() -> None:
    assert True
"""


def report(tmp_path: Path) -> Path:
    data = {
        "verdict": "pass",
        "root": "/work/widgets",
        "base_ref": "main",
        "commit": "0123456789abcdef0123456789abcdef01234567",
        "dirty": False,
        "profiles": ["python"],
        "changed_files": [],
        "locks": {"locked": 1, "broken": []},
        "docs": {"checked": 1, "problems": []},
        "checks": [],
    }
    path = tmp_path / "gate-report.json"
    path.write_text(json.dumps(data) + "\n", encoding="utf-8")
    return path


@pytest.mark.ac("E11-AC-13")
def test_evidence_shows_the_rule_in_the_findings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "widgets"
    fixed = {**RULED, "status": "fixed"}
    for rel, text in {
        TASK_REL: task_with([fixed, PLAIN]),
        "docs/specs/E42-widgets.md": SPEC,
        "tests/test_widgets.py": TESTS,
    }.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8", newline="\n")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "fixture")
    path = report(tmp_path)
    code = evidence.main(["--root", str(repo), TASK, "--gate-report", str(path)])
    out = capsys.readouterr().out
    assert code == 0
    assert out.endswith(
        "## Findings\n\n- F1 [minor] (fixed) AL-002 a.py:3 x\n- F2 [major] (open) a.py:4 y\n"
    )


# --- AC-14: the reviewer's skill and card -------------------------------------------------------


def skill_steps(text: str) -> list[str]:
    body = text.split("## Steps\n", 1)[1].split("\n## ", 1)[0]
    return [line for line in body.split("\n") if re.match(r"\d+\. ", line)]


@pytest.mark.ac("E11-AC-14")
def test_the_skill_finds_the_rules_in_force_with_select() -> None:
    text = (KIT / SKILL).read_text(encoding="utf-8")
    steps = skill_steps(text)
    assert any("python .factory/standards/standards.py select" in step for step in steps[:2])
    assert "--base-ref" in text


@pytest.mark.ac("E11-AC-14")
def test_the_skill_requires_a_rule_on_every_finding() -> None:
    text = (KIT / SKILL).read_text(encoding="utf-8")
    adds = re.findall(r"state\.py finding add[^`\n]*", text)
    assert adds, "no state.py finding add"
    assert all("--rule <id>" in line for line in adds), adds
    done = text.split("## Done when\n", 1)[1]
    assert "--rule" in done


@pytest.mark.ac("E11-AC-14")
def test_the_skill_says_what_no_rule_covers_is_not_a_finding() -> None:
    text = (KIT / SKILL).read_text(encoding="utf-8").lower()
    assert re.search(r"no rule in force[^.]*isn't a finding", text), "no 'no rule' sentence"


def card_front() -> tuple[dict[str, object], str]:
    text = (KIT / CARD).read_text(encoding="utf-8")
    _, front, body = text.split("+++\n", 2)
    return tomllib.loads(front), body


@pytest.mark.ac("E11-AC-14")
def test_the_cards_run_scope_includes_standards_py() -> None:
    data, _ = card_front()
    scope = data["scope"]
    assert isinstance(scope, dict)
    run = scope["run"]
    for python in PYTHONS:
        assert f"{python} .factory/standards/standards.py" in run
    for python in PYTHONS:
        assert f"{python} .factory/state/state.py" in run


@pytest.mark.ac("E11-AC-14")
def test_the_card_lists_the_rules_in_force_with_select() -> None:
    _, body = card_front()
    does = body.split("Does:\n", 1)[1].split("Must not:", 1)[0]
    assert "`standards.py select`" in does
    assert "`--rule`" in does


@pytest.mark.ac("E11-AC-14")
def test_the_kit_skill_and_card_pass_e09_and_e10s_checks(tmp_path: Path) -> None:
    for rel in (".factory/agents/core", ".factory/skills"):
        shutil.copytree(KIT / rel, tmp_path / rel, ignore=shutil.ignore_patterns("__pycache__"))
    assert [str(p) for p in agents.validate(tmp_path)] == []


@pytest.mark.ac("E11-AC-14")
def test_this_repo_installs_the_skill_and_card_and_rebuilds_the_tool_files() -> None:
    for rel in (SKILL, CARD):
        assert (REPO_ROOT / rel).read_bytes() == (KIT / rel).read_bytes(), rel
    for tool in (".claude", ".cursor"):
        agent = (REPO_ROOT / tool / "agents" / "standards-reviewer.md").read_text("utf-8")
        assert "`standards.py select`" in agent, tool
        skill = (REPO_ROOT / tool / "skills" / "standards-review" / "SKILL.md").read_text("utf-8")
        assert "--rule <id>" in skill, tool
