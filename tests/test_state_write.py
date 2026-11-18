"""E02/T2: the state.py write commands.

Covers E02 AC-06 to AC-11 and AC-13. Expectations come from the E02 spec, the design note and
ADR 0014, not from the implementation. The clock is patched through `state._now`.
"""

from __future__ import annotations

import datetime as dt
import io
import os
import tomllib
from pathlib import Path

import pytest

import state

T0 = dt.datetime(2026, 11, 18, 21, 30, 0, tzinfo=dt.UTC)
T1 = dt.datetime(2026, 11, 18, 22, 45, 10, tzinfo=dt.UTC)
STATE = ".agentic/STATE.md"
E01_PLACEHOLDER = state.E01_PLACEHOLDER


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[dt.datetime]:
    """The time `state._now()` returns: the last item of the list (tests append to move on)."""
    times = [T0]
    monkeypatch.setattr(state, "_now", lambda: times[-1])
    return times


def run(root: Path, *args: str) -> int:
    return state.main(["--root", str(root), *args])


def front(root: Path, rel: str) -> dict[str, object]:
    parsed = state.parse((root / rel).read_text(encoding="utf-8"))
    assert not isinstance(parsed, str), parsed
    return parsed[0]


def body(root: Path, rel: str) -> str:
    parsed = state.parse((root / rel).read_text(encoding="utf-8"))
    assert not isinstance(parsed, str), parsed
    return parsed[1]


def assert_valid(root: Path) -> None:
    assert [str(p) for p in state.validate(root)] == []


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def repo(tmp_path: Path, clock: list[dt.datetime], capsys: pytest.CaptureFixture[str]) -> Path:
    """A root with an initialised STATE.md and one task, E02-T1."""
    assert run(tmp_path, "init") == 0
    assert run(tmp_path, "task", "new", "E02-T1", "State file formats") == 0
    capsys.readouterr()
    return tmp_path


TASK = ".agentic/tasks/E02-T1.md"


# --- AC-06: init --------------------------------------------------------------------------------


@pytest.mark.ac("E02-AC-06")
def test_init_writes_a_valid_state(tmp_path: Path, clock: list[dt.datetime]) -> None:
    assert run(tmp_path, "init") == 0
    text = (tmp_path / STATE).read_text(encoding="utf-8")
    assert text.startswith(
        "+++\n"
        'phase = "spec"\n'
        'track = "full"\n'
        'active_task = ""\n'
        "blockers = []\n"
        "updated = 2026-11-18T21:30:00Z\n"
        "+++\n"
    ), text
    assert_valid(tmp_path)


@pytest.mark.ac("E02-AC-06")
def test_init_replaces_the_e01_placeholder(tmp_path: Path, clock: list[dt.datetime]) -> None:
    (tmp_path / ".agentic").mkdir()
    (tmp_path / STATE).write_text(E01_PLACEHOLDER, encoding="utf-8")
    assert run(tmp_path, "init") == 0
    assert front(tmp_path, STATE)["phase"] == "spec"
    assert "Placeholder" not in body(tmp_path, STATE)


@pytest.mark.ac("E02-AC-06")
def test_init_keeps_other_text_without_front_matter_as_the_body(
    tmp_path: Path, clock: list[dt.datetime]
) -> None:
    (tmp_path / ".agentic").mkdir()
    (tmp_path / STATE).write_text("# STATE\n\nmy notes\n", encoding="utf-8")
    assert run(tmp_path, "init") == 0
    assert "my notes" in body(tmp_path, STATE)
    assert_valid(tmp_path)


@pytest.mark.ac("E02-AC-06")
def test_init_refuses_to_overwrite_state_unless_forced(
    tmp_path: Path, clock: list[dt.datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(tmp_path, "init") == 0
    assert run(tmp_path, "start", "--phase", "build") == 2  # start needs a task id
    assert run(tmp_path, "block", "waiting") == 0
    before = (tmp_path / STATE).read_bytes()
    capsys.readouterr()
    assert run(tmp_path, "init") == 1
    assert "--force" in capsys.readouterr().err
    assert (tmp_path / STATE).read_bytes() == before
    clock.append(T1)
    assert run(tmp_path, "init", "--force") == 0
    assert front(tmp_path, STATE)["blockers"] == []
    assert front(tmp_path, STATE)["updated"] == T1


# --- AC-07: task new ----------------------------------------------------------------------------


@pytest.mark.ac("E02-AC-07")
def test_task_new_writes_a_todo_task_with_the_three_headings(
    tmp_path: Path, clock: list[dt.datetime]
) -> None:
    assert run(tmp_path, "init") == 0
    assert run(tmp_path, "task", "new", "E02-T1", "State file formats") == 0
    text = (tmp_path / TASK).read_text(encoding="utf-8")
    assert text == (
        "+++\n"
        'id = "E02-T1"\n'
        'title = "State file formats"\n'
        'status = "todo"\n'
        "review_round = 0\n"
        "created = 2026-11-18T21:30:00Z\n"
        "updated = 2026-11-18T21:30:00Z\n"
        "+++\n"
        "\n"
        "## Goal\n"
        "\n"
        "## Acceptance criteria\n"
        "\n"
        "## Notes\n"
    )
    assert_valid(tmp_path)


@pytest.mark.ac("E02-AC-07")
def test_task_titles_round_trip_quotes_and_unicode(
    tmp_path: Path, clock: list[dt.datetime]
) -> None:
    title = 'Fix "quoted" \\ back-slash – café'
    assert run(tmp_path, "task", "new", "T-1", title) == 0
    assert front(tmp_path, ".agentic/tasks/T-1.md")["title"] == title


@pytest.mark.ac("E02-AC-07")
def test_task_new_refuses_an_existing_id(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    before = (repo / TASK).read_bytes()
    assert run(repo, "task", "new", "E02-T1", "Again") == 1
    assert (repo / TASK).read_bytes() == before
    assert "E02-T1" in capsys.readouterr().err


@pytest.mark.ac("E02-AC-07")
@pytest.mark.parametrize("bad", ["", "a b", "../x", "x/y", "t*", "é"])
def test_task_new_refuses_a_bad_id(
    tmp_path: Path, clock: list[dt.datetime], capsys: pytest.CaptureFixture[str], bad: str
) -> None:
    assert run(tmp_path, "task", "new", bad, "Title") == 1
    assert not (tmp_path / ".agentic" / "tasks").exists() or not list(
        (tmp_path / ".agentic" / "tasks").iterdir()
    )
    capsys.readouterr()


# --- AC-08: task set ----------------------------------------------------------------------------


@pytest.mark.ac("E02-AC-08")
def test_task_set_updates_status_round_and_time_but_not_the_body(
    repo: Path, clock: list[dt.datetime]
) -> None:
    path = repo / TASK
    custom = path.read_text(encoding="utf-8") + "\nSome *notes* with +++ inside.\n\n\n"
    path.write_bytes(custom.encode("utf-8"))
    old_body = custom.split("+++\n", 2)[2]
    clock.append(T1)
    assert run(repo, "task", "set", "E02-T1", "--status", "in-review", "--round", "2") == 0
    data = front(repo, TASK)
    assert data["status"] == "in-review"
    assert data["review_round"] == 2
    assert data["updated"] == T1
    assert data["created"] == T0
    assert path.read_text(encoding="utf-8").split("+++\n", 2)[2] == old_body
    assert_valid(repo)


@pytest.mark.ac("E02-AC-08")
def test_task_set_one_key_leaves_the_other(repo: Path, clock: list[dt.datetime]) -> None:
    assert run(repo, "task", "set", "E02-T1", "--round", "1") == 0
    assert run(repo, "task", "set", "E02-T1", "--status", "blocked") == 0
    data = front(repo, TASK)
    assert (data["status"], data["review_round"]) == ("blocked", 1)


@pytest.mark.ac("E02-AC-08")
@pytest.mark.parametrize(
    "args",
    [
        ["--status", "doing"],
        ["--round", "-1"],
        ["--round", "x"],
        [],
    ],
)
def test_task_set_invalid_values_exit_2_and_change_nothing(
    repo: Path, capsys: pytest.CaptureFixture[str], args: list[str]
) -> None:
    before = snapshot(repo)
    with pytest.raises(SystemExit) as exc:
        code = run(repo, "task", "set", "E02-T1", *args)
        raise SystemExit(code)
    assert exc.value.code == 2
    assert snapshot(repo) == before
    capsys.readouterr()


@pytest.mark.ac("E02-AC-08")
def test_task_set_unknown_task_exits_1(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(repo, "task", "set", "E09-T9", "--status", "done") == 1
    assert "E09-T9" in capsys.readouterr().err


# --- AC-09: findings ----------------------------------------------------------------------------


def _findings(root: Path) -> list[dict[str, object]]:
    value = front(root, TASK).get("findings", [])
    assert isinstance(value, list)
    return value


@pytest.mark.ac("E02-AC-09")
def test_finding_add_numbers_findings_and_opens_them(repo: Path) -> None:
    assert run(repo, "finding", "add", "E02-T1", "--severity", "major", "Missing check") == 0
    assert run(repo, "finding", "add", "E02-T1", "--severity", "minor", 'Typo in "doc"') == 0
    assert _findings(repo) == [
        {"id": "F1", "severity": "major", "status": "open", "summary": "Missing check"},
        {"id": "F2", "severity": "minor", "status": "open", "summary": 'Typo in "doc"'},
    ]
    assert_valid(repo)


@pytest.mark.ac("E02-AC-09")
def test_finding_add_uses_the_next_free_id(repo: Path) -> None:
    text = (repo / TASK).read_text(encoding="utf-8")
    extra = (
        '\n[[findings]]\nid = "F1"\nseverity = "minor"\nstatus = "fixed"\nsummary = "a"\n'
        '\n[[findings]]\nid = "F3"\nseverity = "minor"\nstatus = "open"\nsummary = "b"\n'
    )
    head, rest = text.split("+++\n", 2)[1:]
    (repo / TASK).write_text("+++\n" + head + extra + "+++\n" + rest, encoding="utf-8")
    assert_valid(repo)
    assert run(repo, "finding", "add", "E02-T1", "--severity", "blocker", "c") == 0
    assert [f["id"] for f in _findings(repo)] == ["F1", "F3", "F4"]


@pytest.mark.ac("E02-AC-09")
def test_finding_set_changes_a_findings_status(repo: Path, clock: list[dt.datetime]) -> None:
    assert run(repo, "finding", "add", "E02-T1", "--severity", "major", "x") == 0
    clock.append(T1)
    assert run(repo, "finding", "set", "E02-T1", "F1", "--status", "fixed") == 0
    assert _findings(repo)[0]["status"] == "fixed"
    assert front(repo, TASK)["updated"] == T1


@pytest.mark.ac("E02-AC-09")
def test_finding_errors(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(repo, "finding", "add", "E02-T1", "--severity", "major", "x") == 0
    before = snapshot(repo)
    with pytest.raises(SystemExit) as exc:
        run(repo, "finding", "add", "E02-T1", "--severity", "huge", "x")
    assert exc.value.code == 2
    with pytest.raises(SystemExit) as exc:
        run(repo, "finding", "set", "E02-T1", "F1", "--status", "closed")
    assert exc.value.code == 2
    assert run(repo, "finding", "set", "E02-T1", "F9", "--status", "fixed") == 1
    assert run(repo, "finding", "add", "E09-T9", "--severity", "major", "x") == 1
    assert snapshot(repo) == before
    capsys.readouterr()


# --- AC-10: start, block, unblock ---------------------------------------------------------------


@pytest.mark.ac("E02-AC-10")
def test_start_makes_the_task_active_and_in_progress(repo: Path, clock: list[dt.datetime]) -> None:
    clock.append(T1)
    assert run(repo, "start", "E02-T1", "--phase", "build", "--track", "lite") == 0
    data = front(repo, STATE)
    assert (data["active_task"], data["phase"], data["track"]) == ("E02-T1", "build", "lite")
    assert data["updated"] == T1
    assert front(repo, TASK)["status"] == "in-progress"
    assert front(repo, TASK)["updated"] == T1
    assert_valid(repo)


@pytest.mark.ac("E02-AC-10")
def test_start_without_phase_or_track_keeps_them(repo: Path) -> None:
    assert run(repo, "start", "E02-T1") == 0
    data = front(repo, STATE)
    assert (data["phase"], data["track"]) == ("spec", "full")


@pytest.mark.ac("E02-AC-10")
def test_start_errors(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    before = snapshot(repo)
    assert run(repo, "start", "E09-T9") == 1
    with pytest.raises(SystemExit) as exc:
        run(repo, "start", "E02-T1", "--phase", "coding")
    assert exc.value.code == 2
    assert snapshot(repo) == before
    capsys.readouterr()


@pytest.mark.ac("E02-AC-10")
def test_start_needs_an_initialised_state(
    tmp_path: Path, clock: list[dt.datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(tmp_path, "task", "new", "E02-T1", "x") == 0
    assert run(tmp_path, "start", "E02-T1") == 1
    assert "state.py init" in capsys.readouterr().err


@pytest.mark.ac("E02-AC-10")
def test_block_and_unblock(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(repo, "block", "waiting on review") == 0
    assert run(repo, "block", "CI down") == 0
    assert run(repo, "block", "CI down") == 0  # no duplicates
    assert front(repo, STATE)["blockers"] == ["waiting on review", "CI down"]
    assert run(repo, "unblock", "CI down") == 0
    assert front(repo, STATE)["blockers"] == ["waiting on review"]
    assert run(repo, "unblock", "never added") == 1
    assert run(repo, "block", "again") == 0
    assert run(repo, "unblock") == 0
    assert front(repo, STATE)["blockers"] == []
    assert_valid(repo)
    capsys.readouterr()


# --- AC-11: handoff -----------------------------------------------------------------------------

HANDOFF_BODY = "## Done\n\nParser.\n\n## Next\n\nValidator.\n\n## Open questions\n\nNone.\n"


def _handoffs(root: Path) -> list[str]:
    directory = root / ".agentic" / "handoffs"
    return sorted(p.name for p in directory.glob("*.md")) if directory.is_dir() else []


@pytest.mark.ac("E02-AC-11")
def test_handoff_from_a_body_file(repo: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    source = tmp_path_factory.mktemp("notes") / "handoff.md"
    source.write_text(HANDOFF_BODY, encoding="utf-8")
    assert (
        run(
            repo,
            "handoff",
            "E02-T1",
            "--from",
            "builder",
            "--to",
            "reviewer",
            "--body-file",
            str(source),
        )
        == 0
    )
    assert _handoffs(repo) == ["20261118T213000Z-E02-T1.md"]
    rel = ".agentic/handoffs/20261118T213000Z-E02-T1.md"
    assert front(repo, rel) == {
        "task": "E02-T1",
        "from": "builder",
        "to": "reviewer",
        "created": T0,
    }
    assert HANDOFF_BODY in body(repo, rel)
    assert_valid(repo)


@pytest.mark.ac("E02-AC-11")
def test_handoff_from_stdin_with_no_recipient(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(HANDOFF_BODY))
    assert run(repo, "handoff", "E02-T1", "--from", "builder") == 0
    rel = ".agentic/handoffs/" + _handoffs(repo)[0]
    assert front(repo, rel)["to"] == ""
    assert_valid(repo)


@pytest.mark.ac("E02-AC-11")
def test_handoffs_in_the_same_second_never_overwrite(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for _ in range(3):
        monkeypatch.setattr("sys.stdin", io.StringIO(HANDOFF_BODY))
        assert run(repo, "handoff", "E02-T1", "--from", "builder") == 0
    assert _handoffs(repo) == [
        "20261118T213000Z-E02-T1-2.md",
        "20261118T213000Z-E02-T1-3.md",
        "20261118T213000Z-E02-T1.md",
    ]
    assert_valid(repo)


@pytest.mark.ac("E02-AC-11")
def test_handoff_needs_the_three_headings(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("## Done\n\nx\n\n## Next\n\ny\n"))
    assert run(repo, "handoff", "E02-T1", "--from", "builder") == 2
    assert "## Open questions" in capsys.readouterr().err
    assert _handoffs(repo) == []


@pytest.mark.ac("E02-AC-11")
def test_handoff_for_an_unknown_task_exits_1(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(HANDOFF_BODY))
    assert run(repo, "handoff", "E09-T9", "--from", "builder") == 1
    assert _handoffs(repo) == []
    capsys.readouterr()


# --- AC-13: every write is atomic, LF and valid ----------------------------------------------------


@pytest.mark.ac("E02-AC-13")
def test_written_files_use_lf_only(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert run(repo, "finding", "add", "E02-T1", "--severity", "major", "x") == 0
    assert run(repo, "start", "E02-T1") == 0
    monkeypatch.setattr("sys.stdin", io.StringIO(HANDOFF_BODY.replace("\n", "\r\n")))
    assert run(repo, "handoff", "E02-T1", "--from", "builder") == 0
    for data in snapshot(repo).values():
        assert b"\r" not in data


@pytest.mark.ac("E02-AC-13")
def test_a_failed_rename_changes_nothing_and_leaves_no_temp_file(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = snapshot(repo)

    def fail(src: object, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(state.os, "replace", fail)
    assert run(repo, "task", "set", "E02-T1", "--status", "done") == 1
    assert run(repo, "block", "x") == 1
    assert snapshot(repo) == before
    assert "disk full" in capsys.readouterr().err


@pytest.mark.ac("E02-AC-13")
def test_writes_refuse_to_build_on_invalid_state(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = repo / TASK
    path.write_text(path.read_text(encoding="utf-8").replace('"todo"', '"doing"'), encoding="utf-8")
    before = snapshot(repo)
    assert run(repo, "task", "set", "E02-T1", "--round", "1") == 1
    assert run(repo, "start", "E02-T1") == 1
    assert snapshot(repo) == before
    assert "status" in capsys.readouterr().out


@pytest.mark.ac("E02-AC-13")
def test_root_defaults_to_the_nearest_folder_holding_agentic(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sub = repo / "src" / "deep"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    assert state.main(["block", "from a subfolder"]) == 0
    assert front(repo, STATE)["blockers"] == ["from a subfolder"]
    assert not (sub / ".agentic").exists()


@pytest.mark.ac("E02-AC-13")
def test_front_matter_round_trips_through_tomllib(repo: Path) -> None:
    assert run(repo, "finding", "add", "E02-T1", "--severity", "major", "a\tb\nc") == 0
    text = (repo / TASK).read_text(encoding="utf-8")
    toml = text.split("+++\n")[1]
    assert tomllib.loads(toml)["findings"][0]["summary"] == "a\tb\nc"
    assert os.linesep not in toml or os.linesep == "\n"
