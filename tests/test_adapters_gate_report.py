"""E12/T3 with E08/T1: Report.from_json keeps the gate's adapters section (ADR 0025).

E08's `Report.from_json` rebuilds a report from its JSON, so one renderer serves every reader.
E12's drift check adds an `adapters` section, `{"files", "problems"}`, with `files` null when
the kit has no build.py. These tests check that the section survives the round trip, in the
text and in the JSON.
"""

from __future__ import annotations

import json

import pytest

import gate


def report(files: int | None, problems: list[str]) -> gate.Report:
    return gate.Report(
        root="/work/repo",
        base_ref="origin/main",
        profiles=["python"],
        changed_files=["a.py"],
        results=[gate.Result("python", "format", "pass", exit_code=0, duration_s=0.2)],
        locked=1,
        docs_checked=2,
        commit="0123456789abcdef0123456789abcdef01234567",
        adapter_files=files,
        adapter_problems=problems,
    )


@pytest.mark.ac("E12-AC-08")
@pytest.mark.parametrize(
    ("files", "problems", "line"),
    [
        (99, [], "Adapters: 99 files, 0 stale"),
        (12, [".claude/agents/verifier.md: stale"], "Adapters: 12 files, 1 stale"),
        (None, [], "Adapters: not checked, no build.py"),
    ],
)
def test_from_json_round_trips_the_adapters_section(
    files: int | None, problems: list[str], line: str
) -> None:
    original = report(files, problems)
    again = gate.Report.from_json(json.loads(original.to_json()))
    assert again.to_text() == original.to_text()
    assert again.to_json() == original.to_json()
    assert line in again.to_text()
    assert again.verdict == original.verdict


@pytest.mark.ac("E12-AC-08")
def test_the_json_says_null_files_when_build_py_is_missing() -> None:
    data = json.loads(report(None, []).to_json())
    assert data["adapters"] == {"files": None, "problems": []}


@pytest.mark.ac("E12-AC-08")
def test_drift_read_back_from_json_still_fails_the_verdict() -> None:
    data = json.loads(report(3, ["x: missing"]).to_json())
    assert gate.Report.from_json(data).verdict == "fail"


@pytest.mark.ac("E12-AC-08")
def test_json_from_before_the_adapters_section_reads_as_not_checked() -> None:
    data = json.loads(report(5, []).to_json())
    del data["adapters"]
    assert "Adapters: not checked, no build.py" in gate.Report.from_json(data).to_text()
