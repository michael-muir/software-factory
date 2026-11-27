"""E13/T8: `agents.py lock --approved-by NAME` records who approved a relock.

Covers E03 AC-09 (amended 26 Nov 2026) and AC-11 for the new key. Expectations come from the
E03 spec's Changes entry of 26 Nov 2026 and ADR 0047: `--approved-by` is optional, writes
`approved_by` into the lock record, refuses a blank name, and `agents.py check` accepts the key
as a non-empty string; a record without it stays valid.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_agents_locks import (
    GOOD_SHA,
    LOCKS_REL,
    OTHER_REL,
    TEST_REL,
    _locked,
    lock_record,
    problems,
    record,
    run,
    write_repo,
)


@pytest.mark.ac("E03-AC-09")
def test_lock_approved_by_writes_approved_by_into_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write_repo(tmp_path)
    args = ("lock", "E03-T1", TEST_REL, OTHER_REL, "--approved-by", "po")
    code, output = run(root, monkeypatch, capsys, *args)
    assert code == 0, output
    data = record(root, "E03-T1")
    assert set(data) == {"task", "locked", "approved_by", "files"}
    assert data["approved_by"] == "po"
    assert problems(root) == []
    assert run(root, monkeypatch, capsys, "check")[0] == 0


@pytest.mark.ac("E03-AC-09")
def test_a_relock_with_replace_records_who_approved_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write_repo(tmp_path)
    assert run(root, monkeypatch, capsys, "lock", "E03-T1", TEST_REL)[0] == 0
    assert "approved_by" not in record(root, "E03-T1")
    args = ("lock", "--replace", "E03-T1", TEST_REL, OTHER_REL, "--approved-by", "  po  ")
    code, output = run(root, monkeypatch, capsys, *args)
    assert code == 0, output
    data = record(root, "E03-T1")
    assert data["approved_by"] == "po"
    assert isinstance(data["files"], list)
    assert [f["path"] for f in data["files"]] == [TEST_REL, OTHER_REL]


@pytest.mark.ac("E03-AC-09")
@pytest.mark.parametrize("name", ["", "   "])
def test_a_blank_approved_by_is_refused_and_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    name: str,
) -> None:
    root = write_repo(tmp_path)
    code, output = run(root, monkeypatch, capsys, "lock", "E03-T1", TEST_REL, "--approved-by", name)
    assert code == 1, output
    assert "--approved-by needs a name" in output
    assert not (root / LOCKS_REL / "E03-T1.toml").exists()


@pytest.mark.ac("E03-AC-09")
def test_lock_without_approved_by_writes_no_approved_by(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write_repo(tmp_path)
    assert run(root, monkeypatch, capsys, "lock", "E03-T1", TEST_REL)[0] == 0
    assert set(record(root, "E03-T1")) == {"task", "locked", "files"}


@pytest.mark.ac("E03-AC-11")
def test_check_accepts_a_record_with_approved_by(tmp_path: Path) -> None:
    text = lock_record("E03-T1", {TEST_REL: GOOD_SHA}, approved_by='"michael-muir"')
    root = _locked(write_repo(tmp_path), text)
    assert problems(root) == []


@pytest.mark.ac("E03-AC-11")
def test_check_accepts_a_record_without_approved_by(tmp_path: Path) -> None:
    root = _locked(write_repo(tmp_path), lock_record("E03-T1", {TEST_REL: GOOD_SHA}))
    assert problems(root) == []


@pytest.mark.ac("E03-AC-11")
@pytest.mark.parametrize("value", ['""', '"   "', "1", "true", '["po"]'])
def test_check_refuses_an_empty_or_non_string_approved_by(tmp_path: Path, value: str) -> None:
    text = lock_record("E03-T1", {TEST_REL: GOOD_SHA}, approved_by=value)
    root = _locked(write_repo(tmp_path), text)
    found = problems(root)
    assert any(p.startswith(f"{LOCKS_REL}/E03-T1.toml: approved_by: ") for p in found), found
