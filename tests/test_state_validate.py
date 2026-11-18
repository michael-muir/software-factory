"""E02/T1: state file formats, the validator, `state.py check`, the gate and `install.py check`.

Covers E02 AC-01 to AC-05. Expectations come from the E02 spec, the design note and ADRs
0014-0015, not from the implementation.
"""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from pathlib import Path

import pytest

import gate
import state
from factory_installer import cli
from tests._ac import REPO_ROOT
from tests._gate import PASS, gate_repo, profile, run_gate, touches

KIT_STATE = REPO_ROOT / "kit" / ".factory" / "state" / "state.py"
E01_PLACEHOLDER = (
    "# STATE\n\n_Placeholder. E02 defines this file: current phase, track, active task and "
    "blockers._\n"
)
STATE_REL = ".agentic/STATE.md"
TASK_REL = ".agentic/tasks/E02-T1.md"
HANDOFF_REL = ".agentic/handoffs/20261118T213000Z-E02-T1.md"

VALID_STATE = """+++
phase = "build"
track = "full"
active_task = "E02-T1"
blockers = []
updated = 2026-11-18T21:30:00Z
+++

Notes.
"""

VALID_TASK = """+++
id = "E02-T1"
title = "State file formats and validator"
status = "in-progress"
review_round = 1
created = 2026-11-18T21:30:00Z
updated = 2026-11-18T21:30:00Z

[[findings]]
id = "F1"
severity = "major"
status = "open"
summary = "One line"
+++

## Goal

Validate.

## Acceptance criteria

AC-01.

## Notes
"""

VALID_HANDOFF = """+++
task = "E02-T1"
from = "builder"
to = ""
created = 2026-11-18T21:30:00Z
+++

## Done

Parser.

## Next

Validator.

## Open questions

None.
"""


def write_state(root: Path, files: Mapping[str, str | None] | None = None) -> Path:
    """A repo-like root with a valid STATE.md, one task and one handoff, then overrides."""
    contents: dict[str, str | None] = {
        STATE_REL: VALID_STATE,
        TASK_REL: VALID_TASK,
        HANDOFF_REL: VALID_HANDOFF,
    }
    contents.update(files or {})
    for rel, text in contents.items():
        if text is None:
            continue
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return root


def problems(root: Path) -> list[str]:
    return [str(p) for p in state.validate(root)]


def _replace(text: str, old: str, new: str) -> str:
    assert old in text, old
    return text.replace(old, new, 1)


# --- AC-01: what a valid file is ----------------------------------------------------------------


@pytest.mark.ac("E02-AC-01")
def test_valid_files_have_no_problems(tmp_path: Path) -> None:
    assert problems(write_state(tmp_path)) == []


@pytest.mark.ac("E02-AC-01")
def test_crlf_files_are_valid(tmp_path: Path) -> None:
    root = write_state(tmp_path)
    for rel in (STATE_REL, TASK_REL, HANDOFF_REL):
        path = root / rel
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    assert problems(root) == []


@pytest.mark.ac("E02-AC-01")
def test_a_task_without_findings_is_valid(tmp_path: Path) -> None:
    task = VALID_TASK.split("[[findings]]")[0] + "+++\n" + VALID_TASK.split("+++\n", 2)[2]
    assert problems(write_state(tmp_path, {TASK_REL: task})) == []


@pytest.mark.ac("E02-AC-01")
def test_no_agentic_folder_means_no_state_and_no_problems(tmp_path: Path) -> None:
    assert problems(tmp_path) == []


INVALID: list[tuple[str, str, str, str]] = [
    # (case id, file, new text, text the problem must contain besides the file)
    ("no opening fence", STATE_REL, VALID_STATE.replace("+++\n", "", 1), "front matter"),
    ("no closing fence", STATE_REL, VALID_STATE.replace("+++\n\nNotes", "\nNotes"), "front matter"),
    ("bad toml", STATE_REL, _replace(VALID_STATE, 'track = "full"', "track = full"), "TOML"),
    ("missing key", STATE_REL, _replace(VALID_STATE, "blockers = []\n", ""), "blockers"),
    (
        "unknown key",
        STATE_REL,
        _replace(VALID_STATE, "blockers = []", "blockers = []\nowner = 'x'"),
        "owner",
    ),
    ("bad phase", STATE_REL, _replace(VALID_STATE, '"build"', '"coding"'), "phase"),
    ("bad track", STATE_REL, _replace(VALID_STATE, '"full"', '"fast"'), "track"),
    (
        "blockers not list",
        STATE_REL,
        _replace(VALID_STATE, "blockers = []", 'blockers = "x"'),
        "blockers",
    ),
    (
        "blockers not strings",
        STATE_REL,
        _replace(VALID_STATE, "blockers = []", "blockers = [1]"),
        "blockers",
    ),
    (
        "updated string",
        STATE_REL,
        _replace(VALID_STATE, "updated = 2026-11-18T21:30:00Z", 'updated = "today"'),
        "updated",
    ),
    ("updated local", STATE_REL, _replace(VALID_STATE, "21:30:00Z", "21:30:00"), "updated"),
    ("updated not utc", STATE_REL, _replace(VALID_STATE, "21:30:00Z", "21:30:00+02:00"), "updated"),
    (
        "active task string",
        STATE_REL,
        _replace(VALID_STATE, 'active_task = "E02-T1"', "active_task = 3"),
        "active_task",
    ),
    (
        "task bad status",
        TASK_REL,
        _replace(VALID_TASK, 'status = "in-progress"', 'status = "doing"'),
        "status",
    ),
    (
        "task round string",
        TASK_REL,
        _replace(VALID_TASK, "review_round = 1", 'review_round = "1"'),
        "review_round",
    ),
    (
        "task round bool",
        TASK_REL,
        _replace(VALID_TASK, "review_round = 1", "review_round = true"),
        "review_round",
    ),
    (
        "task round negative",
        TASK_REL,
        _replace(VALID_TASK, "review_round = 1", "review_round = -1"),
        "review_round",
    ),
    ("task id mismatch", TASK_REL, _replace(VALID_TASK, 'id = "E02-T1"', 'id = "E02-T9"'), "id"),
    (
        "task unknown key",
        TASK_REL,
        _replace(VALID_TASK, "review_round = 1", "review_round = 1\nowner = 'x'"),
        "owner",
    ),
    (
        "finding severity",
        TASK_REL,
        _replace(VALID_TASK, 'severity = "major"', 'severity = "huge"'),
        "severity",
    ),
    (
        "finding status",
        TASK_REL,
        _replace(VALID_TASK, 'status = "open"', 'status = "closed"'),
        "status",
    ),
    ("finding id", TASK_REL, _replace(VALID_TASK, 'id = "F1"', 'id = "X1"'), "id"),
    (
        "finding missing summary",
        TASK_REL,
        _replace(VALID_TASK, 'summary = "One line"\n', ""),
        "summary",
    ),
    (
        "finding unknown key",
        TASK_REL,
        _replace(VALID_TASK, 'summary = "One line"', 'summary = "One line"\nby = "x"'),
        "by",
    ),
    (
        "findings not tables",
        TASK_REL,
        _replace(
            VALID_TASK.split("[[findings]]")[0],
            "review_round = 1",
            'review_round = 1\nfindings = ["F1"]',
        )
        + "+++\n"
        + VALID_TASK.split("+++\n", 2)[2],
        "findings",
    ),
    ("task missing heading", TASK_REL, VALID_TASK.replace("## Notes\n", ""), "## Notes"),
    (
        "handoff missing heading",
        HANDOFF_REL,
        VALID_HANDOFF.replace("## Next\n", "## next\n"),
        "## Next",
    ),
    (
        "handoff unknown task",
        HANDOFF_REL,
        _replace(VALID_HANDOFF, 'task = "E02-T1"', 'task = "E09-T4"'),
        "task",
    ),
    (
        "handoff missing from",
        HANDOFF_REL,
        _replace(VALID_HANDOFF, 'from = "builder"\n', ""),
        "from",
    ),
    ("handoff to not string", HANDOFF_REL, _replace(VALID_HANDOFF, 'to = ""', "to = []"), "to"),
]


@pytest.mark.ac("E02-AC-01")
@pytest.mark.parametrize(
    ("rel", "text", "expected"), [c[1:] for c in INVALID], ids=[c[0] for c in INVALID]
)
def test_each_invalid_file_is_reported_naming_the_file_and_key(
    tmp_path: Path, rel: str, text: str, expected: str
) -> None:
    found = problems(write_state(tmp_path, {rel: text}))
    assert found, "expected a problem"
    assert any(line.startswith(f"{rel}: ") and expected in line for line in found), found


@pytest.mark.ac("E02-AC-01")
def test_duplicate_finding_ids_are_reported(tmp_path: Path) -> None:
    second = '\n[[findings]]\nid = "F1"\nseverity = "minor"\nstatus = "fixed"\nsummary = "Two"\n'
    task = _replace(VALID_TASK, 'summary = "One line"\n', 'summary = "One line"\n' + second)
    found = problems(write_state(tmp_path, {TASK_REL: task}))
    assert any(line.startswith(TASK_REL) and "F1" in line for line in found), found


@pytest.mark.ac("E02-AC-01")
def test_the_body_is_otherwise_free(tmp_path: Path) -> None:
    task = VALID_TASK + "\n### Anything\n\n+++\nnot front matter\n+++\n"
    assert problems(write_state(tmp_path, {TASK_REL: task})) == []


# --- AC-02: state.py check ----------------------------------------------------------------------


@pytest.mark.ac("E02-AC-02")
def test_check_exits_0_on_valid_state(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = write_state(tmp_path)
    assert state.main(["check", str(root)]) == 0
    capsys.readouterr()


@pytest.mark.ac("E02-AC-02")
def test_check_prints_one_line_per_problem_and_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write_state(
        tmp_path,
        {
            STATE_REL: _replace(VALID_STATE, '"build"', '"coding"'),
            TASK_REL: _replace(VALID_TASK, 'severity = "major"', 'severity = "huge"'),
        },
    )
    assert state.main(["check", str(root)]) == 1
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.startswith(".agentic/")]
    assert len(lines) == 2, out
    assert any(line.startswith(f"{STATE_REL}: phase: ") for line in lines), out
    assert any(line.startswith(f"{TASK_REL}: ") and "severity" in line for line in lines), out


@pytest.mark.ac("E02-AC-02")
def test_check_reports_an_active_task_without_a_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write_state(tmp_path, {STATE_REL: _replace(VALID_STATE, '"E02-T1"', '"E02-T7"')})
    assert state.main(["check", str(root)]) == 1
    out = capsys.readouterr().out
    assert any(
        line.startswith(f"{STATE_REL}: active_task: ") and "E02-T7" in line
        for line in out.splitlines()
    ), out


@pytest.mark.ac("E02-AC-02")
def test_an_empty_active_task_needs_no_file(tmp_path: Path) -> None:
    root = write_state(
        tmp_path,
        {STATE_REL: _replace(VALID_STATE, '"E02-T1"', '""'), HANDOFF_REL: None, TASK_REL: None},
    )
    assert problems(root) == []


@pytest.mark.ac("E02-AC-02")
def test_check_defaults_to_the_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write_state(tmp_path, {STATE_REL: _replace(VALID_STATE, '"build"', '"coding"')})
    monkeypatch.chdir(root)
    assert state.main(["check"]) == 1
    assert STATE_REL in capsys.readouterr().out


# --- AC-03: install.py check --------------------------------------------------------------------


def _with_config(root: Path) -> Path:
    shutil.copyfile(
        REPO_ROOT / "kit" / ".agentic" / "config.toml", root / ".agentic" / "config.toml"
    )
    return root


@pytest.mark.ac("E02-AC-03")
def test_install_check_passes_valid_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _with_config(write_state(tmp_path))
    assert cli.main(["check", str(root)]) == 0, capsys.readouterr()


@pytest.mark.ac("E02-AC-03")
def test_install_check_reports_state_problems_in_the_same_format(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _with_config(
        write_state(
            tmp_path, {TASK_REL: _replace(VALID_TASK, "review_round = 1", "review_round = -1")}
        )
    )
    assert cli.main(["check", str(root)]) == 1
    out = capsys.readouterr()
    text = out.out + out.err
    assert any(line.startswith(f"{TASK_REL}: review_round: ") for line in text.splitlines()), text


# --- AC-04: the gate ----------------------------------------------------------------------------


def _gated(
    tmp_path: Path, files: Mapping[str, str | None] | None = None, *, kit_state: bool = True
) -> Path:
    repo = gate_repo(
        tmp_path / "repo",
        {
            "py.toml": profile(
                "py", ["marker.txt"], {"format": touches("ran-format.txt"), "lint": PASS}
            )
        },
        files={"marker.txt": "x\n"},
    )
    write_state(repo, files)
    if kit_state:
        (repo / ".factory" / "state").mkdir(parents=True)
        shutil.copyfile(KIT_STATE, repo / ".factory" / "state" / "state.py")
    return repo


@pytest.mark.ac("E02-AC-04")
def test_gate_exits_2_on_invalid_state_and_runs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _gated(tmp_path, {STATE_REL: _replace(VALID_STATE, '"full"', '"fast"')})
    code, output = run_gate(repo, monkeypatch, capsys)
    assert code == 2, output
    assert f"{STATE_REL}: track: " in output, output
    assert not (repo / "ran-format.txt").exists()


@pytest.mark.ac("E02-AC-04")
def test_gate_validates_state_even_with_checks_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _gated(tmp_path, {HANDOFF_REL: VALID_HANDOFF.replace("## Done\n", "")})
    code, output = run_gate(repo, monkeypatch, capsys, "--checks", "format")
    assert code == 2, output
    assert HANDOFF_REL in output
    assert not (repo / "ran-format.txt").exists()


@pytest.mark.ac("E02-AC-04")
def test_gate_runs_normally_with_valid_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _gated(tmp_path)
    code, output = run_gate(repo, monkeypatch, capsys)
    assert code == 0, output
    assert (repo / "ran-format.txt").exists()


@pytest.mark.ac("E02-AC-04")
def test_gate_without_the_state_module_skips_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _gated(tmp_path, {STATE_REL: "not valid\n"}, kit_state=False)
    code, output = run_gate(repo, monkeypatch, capsys)
    assert code == 0, output


@pytest.mark.ac("E02-AC-04")
def test_the_gate_and_check_agree(tmp_path: Path) -> None:
    root = write_state(tmp_path, {TASK_REL: _replace(VALID_TASK, '"in-progress"', '"doing"')})
    loaded = gate.load_state_module(KIT_STATE)
    assert loaded is not None
    assert [str(p) for p in loaded.validate(root)] == problems(root)


# --- AC-05: the E01 placeholder -----------------------------------------------------------------


@pytest.mark.ac("E02-AC-05")
def test_the_e01_placeholder_means_no_state_yet(tmp_path: Path) -> None:
    root = write_state(tmp_path, {STATE_REL: E01_PLACEHOLDER, TASK_REL: None, HANDOFF_REL: None})
    assert problems(root) == []


@pytest.mark.ac("E02-AC-05")
def test_the_e01_placeholder_with_crlf_is_still_the_placeholder(tmp_path: Path) -> None:
    crlf = E01_PLACEHOLDER.replace("\n", "\r\n")
    root = write_state(tmp_path, {TASK_REL: None, HANDOFF_REL: None})
    (root / STATE_REL).write_bytes(crlf.encode("utf-8"))
    assert problems(root) == []


@pytest.mark.ac("E02-AC-05")
def test_the_e01_placeholder_is_the_old_seed() -> None:
    assert state.E01_PLACEHOLDER == E01_PLACEHOLDER


@pytest.mark.ac("E02-AC-05")
def test_other_state_without_front_matter_names_state_py_init(tmp_path: Path) -> None:
    root = write_state(
        tmp_path, {STATE_REL: "# STATE\n\nmy notes\n", TASK_REL: None, HANDOFF_REL: None}
    )
    found = problems(root)
    assert len(found) == 1, found
    assert found[0].startswith(f"{STATE_REL}: ") and "state.py init" in found[0], found


@pytest.mark.ac("E02-AC-05")
def test_the_placeholder_with_an_active_task_reference_is_impossible(tmp_path: Path) -> None:
    # A placeholder STATE.md has no active task, so a lone task file is fine.
    root = write_state(tmp_path, {STATE_REL: E01_PLACEHOLDER})
    assert problems(root) == []
