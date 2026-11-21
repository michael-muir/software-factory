"""E08/T2: `evidence.py` drafts a task's PR body from the gate's JSON report, the task file, the
spec's ACs and the lock record, with `TODO(author)` placeholders for the author (ADR 0025).

Covers E08 AC-03 to AC-08. Expectations come from the E08 spec and design note, not from the
implementation. The fixture repos use a made-up epic, E42, so that drafting E08's own PRs
doesn't trace the tags these fixtures hold.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path

import pytest

import docs
import evidence
import gate
from tests._ac import REPO_ROOT
from tests._gate import git

TASK = "E42-T1"
SHA = "0123456789abcdef0123456789abcdef01234567"
SPEC = """# E42 · Widgets — Spec

Issue: [#42](https://example.com/issues/42) · Milestone: M1 · Depends on: none
Status: **Approved by the product owner** · Next: tests

## Acceptance criteria

- **AC-01** Widgets can be added.
- **AC-02** Widgets can be counted.
- **AC-03** Widgets can be removed.
- **AC-04** Widgets can be renamed.
- **AC-05** Widgets can be listed.
- **AC-05b** Widgets can be listed in order.
"""
PY_TESTS = """import pytest


@pytest.mark.ac("E42-AC-01")
def test_one() -> None:
    assert True


@pytest.mark.ac("E42-AC-01")
@pytest.mark.ac("E42-AC-02")
async def test_two() -> None:
    assert True


def test_untagged() -> None:
    assert True
"""
TS_TESTS = """import { it, test } from "vitest";

// E42-AC-02
test("adds two widgets", () => {});

it.skip('E42-AC-03 removes a widget', () => {});

// E42-AC-05
"""
FINDINGS = [
    {"id": "F1", "severity": "major", "status": "fixed", "summary": "The count was off by one."},
    {"id": "F2", "severity": "minor", "status": "wont-fix", "summary": "Widgets aren't sorted."},
]
CHECKS = [
    ("format", "pass", 0.21),
    ("build", "n/a", None),
    ("tests", "pass", 12.5),
]
FULL_REPORT = f"""Gate: /work/widgets
Base: main
Commit: {SHA}
Locks: 2 locked files, none changed
Docs: 3 checked, no problems
  python  format    pass        0.21s
  python  build     n/a             -
  python  tests     pass       12.50s
PASS"""
SUMMARY = (
    "**PASS** on `0123456789ab` · Locks: 2 locked files, none changed"
    " · Docs: 3 checked, no problems"
    " · python format pass 0.21 s · python build n/a · python tests pass 12.50 s"
)


def _task_file(findings: list[dict[str, str]]) -> str:
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
        lines += ["", "[[findings]]"] + [f'{key} = "{value}"' for key, value in finding.items()]
    lines += ["+++", "", "## Goal", "", "Widgets.", "", "## Acceptance criteria", "", "## Notes"]
    return "\n".join(lines) + "\n"


def _lock_record(paths: list[str]) -> str:
    lines = [f'task = "{TASK}"', "locked = 2026-11-20T00:00:00Z"]
    for path in paths:
        lines += ["", "[[files]]", f'path = "{path}"', f'sha256 = "{"0" * 64}"']
    return "\n".join(lines) + "\n"


def _repo(
    tmp_path: Path,
    tests: Mapping[str, str] | None = None,
    *,
    spec: str | None = SPEC,
    findings: list[dict[str, str]] | None = None,
    lock: bool = True,
    commit_lock: bool = True,
) -> Path:
    """A git repo holding E42's spec, task E42-T1, its locked test files and their record."""
    repo = tmp_path / "widgets"
    files = dict(tests if tests is not None else {"tests/test_widgets.py": PY_TESTS})
    if tests is None:
        files["web/widgets.test.ts"] = TS_TESTS
    written = {
        ".agentic/tasks/E42-T1.md": _task_file(FINDINGS if findings is None else findings),
        **files,
    }
    if spec is not None:
        written["docs/specs/E42-widgets.md"] = spec
    for rel, text in written.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8", newline="\n")
    record = repo / ".agentic" / "locks" / "E42-T1.toml"
    record.parent.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", "main")
    if lock and commit_lock:
        record.write_text(_lock_record(list(files)), encoding="utf-8", newline="\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "fixture")
    if lock and not commit_lock:
        record.write_text(_lock_record(list(files)), encoding="utf-8", newline="\n")
    return repo


def _lock_commit(repo: Path) -> str:
    return git(repo, "log", "-1", "--format=%h", "--", ".agentic/locks/E42-T1.toml").strip()


def _report_data(
    *,
    commit: str | None = SHA,
    dirty: bool = False,
    checks: list[tuple[str, str, float | None]] | None = None,
) -> dict[str, object]:
    rows = CHECKS if checks is None else checks
    return {
        "verdict": "fail" if any(status == "fail" for _, status, _ in rows) else "pass",
        "root": "/work/widgets",
        "base_ref": "main",
        "commit": commit,
        "dirty": dirty,
        "profiles": ["python"],
        "changed_files": [],
        "locks": {"locked": 2, "broken": []},
        "docs": {"checked": 3, "problems": []},
        "checks": [
            {
                "profile": "python",
                "check": check,
                "status": status,
                "reason": "",
                "exit_code": None if took is None else (1 if status == "fail" else 0),
                "duration_s": took,
                "command": None if took is None else [check],
                "output_tail": "",
            }
            for check, status, took in rows
        ],
    }


def _report(
    tmp_path: Path,
    *,
    commit: str | None = SHA,
    dirty: bool = False,
    checks: list[tuple[str, str, float | None]] | None = None,
) -> Path:
    path = tmp_path / "gate-report.json"
    data = _report_data(commit=commit, dirty=dirty, checks=checks)
    path.write_text(json.dumps(data) + "\n", encoding="utf-8")
    return path


def _draft(
    repo: Path, report: Path, capsys: pytest.CaptureFixture[str], *extra: str
) -> tuple[int, str, str]:
    code = evidence.main(["--root", str(repo), TASK, "--gate-report", str(report), *extra])
    out = capsys.readouterr()
    return code, out.out, out.err


FIRST_LINE = (
    "E42/T1: TODO(author): what this PR delivers."
    " Covers E42 **AC-01** to **AC-03** and **AC-05**. Refs #42."
)


def _expected(lock_commit: str) -> str:
    return f"""{FIRST_LINE}

## What changes

- TODO(author): what each change does, and why.

## Acceptance criteria

- **AC-01** `tests/test_widgets.py`: `test_one`, `test_two`
- **AC-02**
  - `tests/test_widgets.py`: `test_two`
  - `web/widgets.test.ts`: `adds two widgets`
- **AC-03** `web/widgets.test.ts`: `E42-AC-03 removes a widget`
- **AC-05** `web/widgets.test.ts`

## Tests

5 tests in 2 files, locked in `.agentic/locks/E42-T1.toml` ({lock_commit}).

## Gate evidence

{SUMMARY}

<details><summary>Full gate report</summary>

```text
{FULL_REPORT}
```

</details>

## Findings

- F1 [major] (fixed) The count was off by one.
- F2 [minor] (wont-fix) Widgets aren't sorted.
"""


def _section(text: str, heading: str) -> str:
    return text.split(f"{heading}\n", 1)[1].split("\n## ", 1)[0]


# --- AC-03: the body and its first line ---------------------------------------------------------


@pytest.mark.ac("E08-AC-03")
@pytest.mark.ac("E08-AC-04")
@pytest.mark.ac("E08-AC-05")
@pytest.mark.ac("E08-AC-06")
@pytest.mark.ac("E08-AC-07")
def test_the_whole_draft(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path)
    code, out, err = _draft(repo, _report(tmp_path), capsys)
    assert (code, err) == (0, "")
    assert out == _expected(_lock_commit(repo))


@pytest.mark.ac("E08-AC-03")
def test_the_draft_follows_the_templates_headings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    template = (REPO_ROOT / "kit/.factory/workflow/templates/pr-evidence.md").read_text("utf-8")
    _, out, _ = _draft(_repo(tmp_path), _report(tmp_path), capsys)
    headings = [line for line in out.splitlines() if line.startswith("## ")]
    assert headings == [line for line in template.splitlines() if line.startswith("## ")]


@pytest.mark.ac("E08-AC-03")
@pytest.mark.parametrize(
    ("tags", "covers"),
    [
        (["AC-02"], "**AC-02**"),
        (["AC-01", "AC-02"], "**AC-01** and **AC-02**"),
        (["AC-01", "AC-03", "AC-05"], "**AC-01**, **AC-03** and **AC-05**"),
        (["AC-01", "AC-02", "AC-03"], "**AC-01** to **AC-03**"),
        (["AC-04", "AC-05", "AC-05b"], "**AC-04** to **AC-05b**"),
        (["AC-01", "AC-02", "AC-03", "AC-05"], "**AC-01** to **AC-03** and **AC-05**"),
    ],
)
def test_the_first_line_names_the_traced_acs_in_spec_order(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], tags: list[str], covers: str
) -> None:
    text = "".join(
        f'@pytest.mark.ac("E42-{tag}")\ndef test_{n}() -> None:\n    pass\n\n\n'
        for n, tag in enumerate(reversed(tags))
    )
    repo = _repo(tmp_path, {"tests/test_widgets.py": "import pytest\n\n\n" + text})
    _, out, _ = _draft(repo, _report(tmp_path), capsys)
    first = out.split("\n", 1)[0]
    assert first == (f"E42/T1: TODO(author): what this PR delivers. Covers E42 {covers}. Refs #42.")


@pytest.mark.ac("E08-AC-03")
def test_the_issue_comes_from_the_specs_issue_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, spec=SPEC.replace("[#42](https://example.com/issues/42)", "[#7](x)"))
    _, out, _ = _draft(repo, _report(tmp_path), capsys)
    assert out.split("\n", 1)[0].endswith(" Refs #7.")


@pytest.mark.ac("E08-AC-03")
def test_out_writes_the_same_body_with_lf_line_endings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, report = _repo(tmp_path), _report(tmp_path)
    _, printed, _ = _draft(repo, report, capsys)
    body = tmp_path / "body.md"
    code, out, _ = _draft(repo, report, capsys, "--out", str(body))
    assert (code, out) == (0, "")
    data = body.read_bytes()
    assert b"\r\n" not in data
    assert data.decode("utf-8") == printed == _expected(_lock_commit(repo))


@pytest.mark.ac("E08-AC-03")
def test_the_draft_is_deterministic(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo, report = _repo(tmp_path), _report(tmp_path)
    assert _draft(repo, report, capsys) == _draft(repo, report, capsys)


@pytest.mark.ac("E08-AC-03")
def test_the_root_defaults_to_the_nearest_agentic_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, report = _repo(tmp_path), _report(tmp_path)
    monkeypatch.chdir(repo / "web")
    assert evidence.main([TASK, "--gate-report", str(report)]) == 0
    assert capsys.readouterr().out == _expected(_lock_commit(repo))


# --- AC-04: the AC trace ------------------------------------------------------------------------


@pytest.mark.ac("E08-AC-04")
def test_a_tag_the_spec_does_not_have_stops_the_draft(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = PY_TESTS + '\n\n@pytest.mark.ac("E42-AC-99")\ndef test_odd() -> None:\n    pass\n'
    repo = _repo(tmp_path, {"tests/test_widgets.py": text})
    code, out, err = _draft(repo, _report(tmp_path), capsys)
    assert (code, out) == (1, "")
    assert "E42-AC-99" in err
    assert "tests/test_widgets.py" in err


@pytest.mark.ac("E08-AC-04")
def test_tags_of_other_epics_are_not_traced(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = PY_TESTS.replace('@pytest.mark.ac("E42-AC-02")', '@pytest.mark.ac("E43-AC-02")')
    repo = _repo(tmp_path, {"tests/test_widgets.py": text})
    _, out, _ = _draft(repo, _report(tmp_path), capsys)
    assert _section(out, "## Acceptance criteria").strip().splitlines() == [
        "- **AC-01** `tests/test_widgets.py`: `test_one`, `test_two`"
    ]


@pytest.mark.ac("E08-AC-04")
def test_python_methods_and_ts_forms_are_named(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    py = (
        "import pytest\n\n\nclass TestWidgets:\n"
        '    @pytest.mark.ac("E42-AC-01")\n'
        "    def test_in_a_class(self) -> None:\n        pass\n"
    )
    ts = (
        "// E42-AC-02\n"
        'it("adds", () => {});\n'
        "// E42-AC-02\n"
        "test.only(`counts`, () => {});\n"
        "describe('widgets', () => {\n"
        '  test( "E42-AC-03 in a title", () => {});\n'
        "});\n"
    )
    repo = _repo(tmp_path, {"tests/test_widgets.py": py, "web/widgets.spec.js": ts})
    _, out, _ = _draft(repo, _report(tmp_path), capsys)
    assert _section(out, "## Acceptance criteria").strip().splitlines() == [
        "- **AC-01** `tests/test_widgets.py`: `test_in_a_class`",
        "- **AC-02** `web/widgets.spec.js`: `adds`, `counts`",
        "- **AC-03** `web/widgets.spec.js`: `E42-AC-03 in a title`",
    ]
    assert "4 tests in 2 files" in _section(out, "## Tests")


@pytest.mark.ac("E08-AC-04")
def test_a_test_in_a_stack_it_cannot_name_is_listed_by_its_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    go = "package widgets\n\n// E42-AC-04\nfunc TestRename(t *testing.T) {}\n"
    repo = _repo(tmp_path, {"tests/test_widgets.py": PY_TESTS, "widgets_test.go": go})
    _, out, _ = _draft(repo, _report(tmp_path), capsys)
    trace = _section(out, "## Acceptance criteria").strip().splitlines()
    assert trace[-1] == "- **AC-04** `widgets_test.go`"
    assert "3 tests in 2 files" in _section(out, "## Tests")


# --- AC-05: tests and the lock record -----------------------------------------------------------


@pytest.mark.ac("E08-AC-05")
def test_the_tests_line_counts_files_and_tests_and_names_the_lock_commit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, {"tests/test_widgets.py": PY_TESTS})
    _, out, _ = _draft(repo, _report(tmp_path), capsys)
    assert _section(out, "## Tests").strip() == (
        f"3 tests in 1 file, locked in `.agentic/locks/E42-T1.toml` ({_lock_commit(repo)})."
    )


@pytest.mark.ac("E08-AC-05")
def test_one_test_is_singular(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    text = 'import pytest\n\n\n@pytest.mark.ac("E42-AC-01")\ndef test_one() -> None:\n    pass\n'
    repo = _repo(tmp_path, {"tests/test_widgets.py": text})
    _, out, _ = _draft(repo, _report(tmp_path), capsys)
    assert _section(out, "## Tests").strip().startswith("1 test in 1 file, locked in ")


@pytest.mark.ac("E08-AC-05")
def test_a_lock_record_not_yet_committed_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, commit_lock=False)
    _, out, _ = _draft(repo, _report(tmp_path), capsys)
    assert _section(out, "## Tests").strip() == (
        "5 tests in 2 files, locked in `.agentic/locks/E42-T1.toml` (not committed)."
    )


@pytest.mark.ac("E08-AC-05")
@pytest.mark.ac("E08-AC-08")
def test_a_task_with_no_lock_record_leaves_the_trace_as_a_placeholder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, lock=False)
    code, out, _ = _draft(repo, _report(tmp_path), capsys)
    assert code == 0
    assert _section(out, "## Tests").strip() == "No locked tests."
    assert _section(out, "## Acceptance criteria").strip() == (
        "- TODO(author): each **AC-nn** and the tests that prove it."
    )
    assert out.split("\n", 1)[0] == (
        "E42/T1: TODO(author): what this PR delivers."
        " Covers E42 TODO(author): the ACs it covers. Refs #42."
    )


@pytest.mark.ac("E08-AC-05")
def test_a_locked_file_that_is_missing_stops_the_draft(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    (repo / "web" / "widgets.test.ts").unlink()
    code, out, err = _draft(repo, _report(tmp_path), capsys)
    assert (code, out) == (1, "")
    assert "web/widgets.test.ts" in err


# --- AC-06: gate evidence -----------------------------------------------------------------------


@pytest.mark.ac("E08-AC-06")
def test_the_details_block_is_the_gates_own_text_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = _report(tmp_path)
    data = json.loads(report.read_text(encoding="utf-8"))
    _, out, _ = _draft(_repo(tmp_path), report, capsys)
    block = out.split("```text\n", 1)[1].split("\n```\n", 1)[0]
    assert block == gate.Report.from_json(data).to_text() == FULL_REPORT


@pytest.mark.ac("E08-AC-06")
def test_a_failing_report_is_drafted_with_its_verdict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    checks = [("format", "pass", 0.21), ("tests", "fail", 3.0), ("mutation", "skipped", None)]
    _, out, _ = _draft(_repo(tmp_path), _report(tmp_path, checks=checks), capsys)
    assert _section(out, "## Gate evidence").strip().split("\n", 1)[0] == (
        "**FAIL** on `0123456789ab` · Locks: 2 locked files, none changed"
        " · Docs: 3 checked, no problems"
        " · python format pass 0.21 s · python tests fail 3.00 s · python mutation skipped"
    )


@pytest.mark.ac("E08-AC-06")
def test_a_report_from_a_dirty_tree_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = _draft(_repo(tmp_path), _report(tmp_path, dirty=True), capsys)
    assert (code, out) == (1, "")
    assert "uncommitted changes" in err


@pytest.mark.ac("E08-AC-06")
def test_a_report_with_no_commit_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = _draft(_repo(tmp_path), _report(tmp_path, commit=None), capsys)
    assert (code, out) == (1, "")
    assert "no commit" in err


@pytest.mark.ac("E08-AC-06")
def test_summary_prints_the_summary_line_and_a_table(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert evidence.main(["--summary", str(_report(tmp_path))]) == 0
    assert capsys.readouterr().out == (
        f"{SUMMARY}\n"
        "\n"
        "| Profile | Check | Status | Time |\n"
        "| --- | --- | --- | --- |\n"
        "| python | format | pass | 0.21 s |\n"
        "| python | build | n/a | - |\n"
        "| python | tests | pass | 12.50 s |\n"
    )


@pytest.mark.ac("E08-AC-06")
@pytest.mark.parametrize("content", [None, "{not json", "[]"])
def test_summary_of_a_missing_or_unreadable_report_says_so_and_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], content: str | None
) -> None:
    path = tmp_path / "gate-report.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    assert evidence.main(["--summary", str(path)]) == 0
    assert capsys.readouterr().out == "No gate report.\n"


@pytest.mark.ac("E08-AC-06")
def test_the_template_shows_a_commit_and_the_details_block() -> None:
    template = (REPO_ROOT / "kit/.factory/workflow/templates/pr-evidence.md").read_text("utf-8")
    evidence_section = _section(template, "## Gate evidence")
    assert re.search(r"\*\*PASS\*\* on `[0-9a-f]{7,40}`", evidence_section)
    assert "<details><summary>Full gate report</summary>" in evidence_section
    assert "</details>" in evidence_section
    assert docs.lint_pr(template, "pr-evidence.md") == []


# --- AC-07: findings ----------------------------------------------------------------------------


@pytest.mark.ac("E08-AC-07")
def test_a_task_with_no_findings_says_none(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, out, _ = _draft(_repo(tmp_path, findings=[]), _report(tmp_path), capsys)
    assert _section(out, "## Findings").strip() == "None."


# --- AC-08: placeholders and errors -------------------------------------------------------------


@pytest.mark.ac("E08-AC-08")
def test_only_the_authors_parts_are_placeholders(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, out, _ = _draft(_repo(tmp_path), _report(tmp_path), capsys)
    marked = [line for line in out.splitlines() if "TODO(author)" in line]
    assert marked == [out.split("\n", 1)[0], "- TODO(author): what each change does, and why."]
    assert marked[0].startswith("E42/T1: TODO(author): what this PR delivers. Covers E42 ")


@pytest.mark.ac("E08-AC-08")
def test_a_filled_in_draft_passes_the_pr_evidence_rules(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, out, _ = _draft(_repo(tmp_path), _report(tmp_path), capsys)
    filled = out.replace("TODO(author): what this PR delivers", "Widgets can be counted").replace(
        "TODO(author): what each change does, and why.", "A counter for widgets."
    )
    assert "TODO(author)" not in filled
    assert docs.lint_pr(filled, "pr.md") == []
    # The rules check-pr --strict adds (AC-09): a commit, a test per AC, and ACs from the spec.
    assert re.match(r"\*\*PASS\*\* on `[0-9a-f]{7,40}`", _section(filled, "## Gate evidence")[1:])
    trace = _section(filled, "## Acceptance criteria").strip().splitlines()
    starts = [i for i, line in enumerate(trace) if line.startswith("- **AC-")]
    assert starts
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(trace)
        assert "`" in "\n".join(trace[start:end]), trace[start]
    spec_ids = set(docs.AC_ID.findall(SPEC))
    assert {line.split("**")[1] for line in trace if line.startswith("- **")} <= spec_ids


@pytest.mark.ac("E08-AC-08")
def test_a_missing_task_is_an_error_naming_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    code = evidence.main(["--root", str(repo), "E42-T9", "--gate-report", str(_report(tmp_path))])
    out = capsys.readouterr()
    assert (code, out.out) == (1, "")
    assert "E42-T9" in out.err


@pytest.mark.ac("E08-AC-08")
def test_a_missing_gate_report_is_an_error_naming_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "nowhere.json"
    code, out, err = _draft(_repo(tmp_path), missing, capsys)
    assert (code, out) == (1, "")
    assert "nowhere.json" in err


@pytest.mark.ac("E08-AC-08")
def test_an_unreadable_gate_report_is_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = tmp_path / "gate-report.json"
    report.write_text("{not json", encoding="utf-8")
    code, out, err = _draft(_repo(tmp_path), report, capsys)
    assert (code, out) == (1, "")
    assert "gate-report.json" in err


@pytest.mark.ac("E08-AC-08")
def test_a_missing_spec_is_an_error_naming_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = _draft(_repo(tmp_path, spec=None), _report(tmp_path), capsys)
    assert (code, out) == (1, "")
    assert "spec" in err
    assert "E42" in err


@pytest.mark.ac("E08-AC-08")
def test_a_spec_with_no_issue_line_is_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = SPEC.replace("Issue: [#42](https://example.com/issues/42) · ", "")
    code, out, err = _draft(_repo(tmp_path, spec=spec), _report(tmp_path), capsys)
    assert (code, out) == (1, "")
    assert "Issue:" in err


@pytest.mark.ac("E08-AC-08")
def test_a_task_id_with_no_epic_is_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    code = evidence.main(["--root", str(repo), "widgets", "--gate-report", str(_report(tmp_path))])
    out = capsys.readouterr()
    assert (code, out.out) == (1, "")
    assert "widgets" in out.err


@pytest.mark.ac("E08-AC-08")
@pytest.mark.parametrize(
    "argv",
    [
        [],
        [TASK],
        ["--gate-report", "r.json"],
        [TASK, "--gate-report", "r.json", "--summary", "r.json"],
        ["--summary", "r.json", "--out", "body.md"],
        [TASK, "--gate-report", "r.json", "--bogus"],
    ],
)
def test_usage_errors_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    assert evidence.main(argv) == 2
    assert capsys.readouterr().out == ""
