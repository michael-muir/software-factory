"""E08/T3: `docs.py check-pr --strict` checks the commit, the trace, the spec and placeholders, and
`--commits` checks the evidence's commit against the PR's commits (ADR 0025).

Covers E08 AC-09 to AC-11. Expectations come from the E08 spec and design note, not from the
implementation. Plain `check-pr` stays E04's check; E04's locked tests pin it. The fixtures use a
made-up epic, E42, so drafting E08's own PRs doesn't trace them.
"""

from __future__ import annotations

import io
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

import docs

SHA = "0123456789abcdef0123456789abcdef01234567"
OTHER = "fedcba9876543210fedcba9876543210fedcba98"
SPEC = """# E42 · Widgets — Spec

Issue: [#42](https://example.com/issues/42) · Milestone: M1 · Depends on: none
Status: **Approved by the product owner** · Next: tests

## Acceptance criteria

- **AC-01** Widgets can be added.
- **AC-02** Widgets can be counted.
- **AC-03** Widgets can be removed.
"""
BODY = """E42/T1: Widgets can be counted. Covers E42 **AC-01** and **AC-02**. Refs #42.

## What changes

- A counter for widgets.

## Acceptance criteria

- **AC-01** `tests/test_widgets.py`: `test_one`
- **AC-02**
  - `tests/test_widgets.py`: `test_two`
  - `web/widgets.test.ts`

## Tests

2 tests in 2 files.

## Gate evidence

**PASS** on `0123456789ab` · Locks: 2 locked files, none changed · python tests pass 1.00 s

<details><summary>Full gate report</summary>

```text
Gate: /work/widgets
Commit: 0123456789abcdef0123456789abcdef01234567
PASS
```

</details>

## Findings

None.
"""
SUMMARY = "**PASS** on `0123456789ab` · Locks: 2 locked files, none changed"


def _root(tmp_path: Path, spec: str | None = SPEC) -> Path:
    root = tmp_path / "repo"
    (root / ".agentic").mkdir(parents=True)
    if spec is not None:
        (root / "docs" / "specs").mkdir(parents=True)
        (root / "docs" / "specs" / "E42-widgets.md").write_text(spec, encoding="utf-8")
    return root


def _strict(text: str, root: Path, commits: Sequence[str] | None = None) -> list[str]:
    return [str(p) for p in docs.lint_pr_strict(text, "pr.md", root, commits)]


def _main(
    argv: list[str], capsys: pytest.CaptureFixture[str], tmp_path: Path, body: str | None = BODY
) -> tuple[int, list[str]]:
    path = tmp_path / "pr.md"
    if body is not None:
        path.write_text(body, encoding="utf-8")
    code = docs.main([a.replace("PR_FILE", str(path)) for a in argv])
    out = capsys.readouterr()
    return code, [line.replace(str(path), "pr.md") for line in out.out.splitlines()]


# --- AC-09: the strict rules --------------------------------------------------------------------


@pytest.mark.ac("E08-AC-09")
def test_a_complete_body_has_no_problems(tmp_path: Path) -> None:
    assert _strict(BODY, _root(tmp_path)) == []


@pytest.mark.ac("E08-AC-09")
@pytest.mark.parametrize(
    "summary",
    [
        "**PASS** on `012345a` · Locks: none",
        f"**PASS** on {SHA}.",
        "**PASS** on commit 9f3e2a1 (local).",
    ],
)
def test_a_commit_of_7_to_40_hex_characters_counts(tmp_path: Path, summary: str) -> None:
    body = BODY.replace(SUMMARY, summary).replace(f"Commit: {SHA}\n", "")
    assert _strict(body, _root(tmp_path)) == []


@pytest.mark.ac("E08-AC-09")
def test_a_commit_in_the_full_report_alone_counts(tmp_path: Path) -> None:
    assert _strict(BODY.replace(SUMMARY, "**PASS**"), _root(tmp_path)) == []


@pytest.mark.ac("E08-AC-09")
@pytest.mark.parametrize(
    "summary",
    [
        "**PASS**, no commit named",
        "**PASS** on `012345`",  # 6 characters
        "**PASS** on `0123456789ABCDEF`",  # uppercase
        "**PASS** on `deadbeef`",  # no digit: a word, not a commit
        f"**PASS** on `{SHA}0`",  # 41 characters
        "**PASS** on `0123456789abz`",  # not a whole hex word
    ],
)
def test_gate_evidence_with_no_commit_is_a_problem(tmp_path: Path, summary: str) -> None:
    body = BODY.replace(SUMMARY, summary).replace(f"Commit: {SHA}\n", "Commit: none\n")
    assert _strict(body, _root(tmp_path)) == ["pr.md: ## Gate evidence: no commit SHA"]


@pytest.mark.ac("E08-AC-09")
def test_a_commit_outside_the_gate_evidence_does_not_count(tmp_path: Path) -> None:
    body = (
        BODY.replace(SUMMARY, "**PASS**")
        .replace(f"Commit: {SHA}\n", "")
        .replace("2 tests in 2 files.", "2 tests in 2 files, locked in 9f3e2a1.")
    )
    assert _strict(body, _root(tmp_path)) == ["pr.md: ## Gate evidence: no commit SHA"]


@pytest.mark.ac("E08-AC-09")
def test_an_ac_line_with_no_test_is_a_problem(tmp_path: Path) -> None:
    body = BODY.replace(
        "- **AC-02**\n  - `tests/test_widgets.py`: `test_two`\n  - `web/widgets.test.ts`\n",
        "- **AC-02** counted by hand\n",
    )
    assert _strict(body, _root(tmp_path)) == ["pr.md: AC-02: lists no test"]


@pytest.mark.ac("E08-AC-09")
def test_a_test_on_an_unindented_line_after_does_not_count(tmp_path: Path) -> None:
    body = BODY.replace(
        "- **AC-02**\n  - `tests/test_widgets.py`: `test_two`\n  - `web/widgets.test.ts`\n",
        "- **AC-02**\n\nSee `tests/test_widgets.py`.\n",
    )
    assert _strict(body, _root(tmp_path)) == ["pr.md: AC-02: lists no test"]


@pytest.mark.ac("E08-AC-09")
def test_the_e04_template_form_of_an_ac_line_is_read(tmp_path: Path) -> None:
    body = BODY.replace(
        "- **AC-01** `tests/test_widgets.py`: `test_one`", "- **AC-01**: the tests that prove it"
    )
    assert _strict(body, _root(tmp_path)) == ["pr.md: AC-01: lists no test"]


@pytest.mark.ac("E08-AC-09")
def test_an_ac_the_spec_does_not_have_is_a_problem(tmp_path: Path) -> None:
    body = BODY.replace("- **AC-01** `tests/", "- **AC-09** `tests/")
    assert _strict(body, _root(tmp_path)) == ["pr.md: AC-09: not in the E42 spec"]


@pytest.mark.ac("E08-AC-09")
def test_a_named_epic_with_no_spec_is_a_problem(tmp_path: Path) -> None:
    assert _strict(BODY, _root(tmp_path, spec=None)) == [
        "pr.md: ## Acceptance criteria: no spec for E42"
    ]


@pytest.mark.ac("E08-AC-09")
def test_a_named_epic_needs_at_least_one_ac_line(tmp_path: Path) -> None:
    trace = BODY.split("## Acceptance criteria\n", 1)[1].split("## Tests", 1)[0]
    body = BODY.replace(trace, "\nSee the spec.\n\n")
    assert _strict(body, _root(tmp_path)) == [
        "pr.md: ## Acceptance criteria: no AC lines (- **AC-nn**)"
    ]


@pytest.mark.ac("E08-AC-09")
def test_covers_names_the_epic_when_the_first_line_has_no_slice(tmp_path: Path) -> None:
    body = BODY.replace("E42/T1: Widgets", "Widgets").replace("**AC-01**", "**AC-07**", 2)
    assert _strict(body, _root(tmp_path)) == ["pr.md: AC-07: not in the E42 spec"]


@pytest.mark.ac("E08-AC-09")
def test_the_epic_comes_from_the_first_non_empty_line(tmp_path: Path) -> None:
    body = "\n\n" + BODY.replace("- **AC-01** `tests/", "- **AC-09** `tests/")
    assert _strict(body, _root(tmp_path)) == ["pr.md: AC-09: not in the E42 spec"]


@pytest.mark.ac("E08-AC-09")
def test_a_body_that_names_no_epic_skips_the_spec_check(tmp_path: Path) -> None:
    body = BODY.replace(
        "E42/T1: Widgets can be counted. Covers E42 **AC-01** and **AC-02**.", "Widgets."
    ).replace("- **AC-01** `tests/", "- **AC-77** `tests/")
    assert _strict(body, _root(tmp_path, spec=None)) == []


@pytest.mark.ac("E08-AC-09")
def test_a_left_placeholder_is_a_problem(tmp_path: Path) -> None:
    body = BODY.replace("Widgets can be counted.", "TODO(author): what this PR delivers.").replace(
        "- A counter for widgets.", "- TODO(author): what each change does, and why."
    )
    assert _strict(body, _root(tmp_path)) == [
        "pr.md: line 1: placeholder left: TODO(author)",
        "pr.md: line 5: placeholder left: TODO(author)",
    ]


@pytest.mark.ac("E08-AC-09")
def test_crlf_line_endings_are_read_as_lf(tmp_path: Path) -> None:
    assert _strict(BODY.replace("\n", "\r\n"), _root(tmp_path)) == []


@pytest.mark.ac("E08-AC-09")
def test_strict_prints_e04_problems_and_its_own_and_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _root(tmp_path)
    body = BODY.replace("## Findings\n", "").replace("- **AC-01** `tests/", "- **AC-09** `tests/")
    code, lines = _main(
        ["--root", str(root), "check-pr", "--strict", "PR_FILE"], capsys, tmp_path, body
    )
    assert code == 1
    assert lines == ["pr.md: ## Findings: missing heading", "pr.md: AC-09: not in the E42 spec"]


@pytest.mark.ac("E08-AC-09")
def test_strict_passes_a_complete_body(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _root(tmp_path)
    assert _main(["--root", str(root), "check-pr", "--strict", "PR_FILE"], capsys, tmp_path) == (
        0,
        [],
    )


@pytest.mark.ac("E08-AC-09")
def test_strict_finds_the_spec_from_the_nearest_agentic_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _root(tmp_path)
    (root / "docs" / "sub").mkdir()
    monkeypatch.chdir(root / "docs" / "sub")
    body = BODY.replace("- **AC-01** `tests/", "- **AC-09** `tests/")
    code, lines = _main(["check-pr", "--strict", "PR_FILE"], capsys, tmp_path, body)
    assert (code, lines) == (1, ["pr.md: AC-09: not in the E42 spec"])


@pytest.mark.ac("E08-AC-09")
def test_without_strict_check_pr_is_e04s_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _root(tmp_path, spec=None)
    body = (
        BODY.replace(SUMMARY, "**PASS**")
        .replace(f"Commit: {SHA}\n", "")
        .replace("Widgets can be counted.", "TODO(author): what this PR delivers.")
        .replace("- **AC-01** `tests/test_widgets.py`: `test_one`", "- **AC-09** by hand")
    )
    assert _main(["--root", str(root), "check-pr", "PR_FILE"], capsys, tmp_path, body) == (0, [])


# --- AC-10: the PR's commits --------------------------------------------------------------------


@pytest.mark.ac("E08-AC-10")
@pytest.mark.parametrize("commits", [[OTHER, SHA], [SHA[:7]], [SHA[:12], OTHER]])
def test_the_evidence_commit_among_the_prs_passes(tmp_path: Path, commits: list[str]) -> None:
    assert _strict(BODY, _root(tmp_path), commits) == []


@pytest.mark.ac("E08-AC-10")
def test_a_full_sha_in_the_evidence_matches_the_prs_commit(tmp_path: Path) -> None:
    body = BODY.replace(SUMMARY, f"**PASS** on `{SHA}`")
    assert _strict(body, _root(tmp_path), [SHA]) == []


@pytest.mark.ac("E08-AC-10")
@pytest.mark.parametrize("commits", [[OTHER], [SHA[:6]], []])
def test_an_evidence_commit_not_in_the_pr_is_a_problem_naming_both(
    tmp_path: Path, commits: list[str]
) -> None:
    found = _strict(BODY, _root(tmp_path), commits)
    assert len(found) == 1, found
    assert found[0].startswith(
        "pr.md: ## Gate evidence: evidence is for 0123456789ab, which is not a commit of this PR"
    )
    for commit in commits:
        assert commit[:7] in found[0]


@pytest.mark.ac("E08-AC-10")
def test_commits_on_the_command_line_after_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _root(tmp_path)
    argv = ["--root", str(root), "check-pr", "--strict", "PR_FILE", "--commits"]
    assert _main([*argv, OTHER, SHA], capsys, tmp_path) == (0, [])
    code, lines = _main([*argv, OTHER], capsys, tmp_path)
    assert code == 1
    assert len(lines) == 1
    assert "evidence is for 0123456789ab, which is not a commit of this PR" in lines[0]


@pytest.mark.ac("E08-AC-10")
def test_commits_without_strict_checks_the_commit_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _root(tmp_path, spec=None)
    argv = ["--root", str(root), "check-pr", "PR_FILE", "--commits"]
    assert _main([*argv, SHA], capsys, tmp_path) == (0, [])
    code, lines = _main([*argv, OTHER], capsys, tmp_path)
    assert code == 1
    assert len(lines) == 1
    assert "which is not a commit of this PR" in lines[0]


@pytest.mark.ac("E08-AC-10")
def test_commits_with_no_commit_in_the_evidence_reports_it_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _root(tmp_path)
    body = BODY.replace(SUMMARY, "**PASS**").replace(f"Commit: {SHA}\n", "")
    argv = ["--root", str(root), "check-pr", "--strict", "PR_FILE", "--commits", SHA]
    assert _main(argv, capsys, tmp_path, body) == (1, ["pr.md: ## Gate evidence: no commit SHA"])


# --- AC-11: empty and missing bodies ------------------------------------------------------------

E04_EMPTY = [
    "pr.md: ## What changes: missing heading",
    "pr.md: ## Acceptance criteria: missing heading",
    "pr.md: ## Gate evidence: missing heading",
    "pr.md: ## Findings: missing heading",
]


@pytest.mark.ac("E08-AC-11")
@pytest.mark.parametrize("body", ["", "\n", "  \r\n\r\n"])
def test_an_empty_body_gives_problems(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], body: str
) -> None:
    root = _root(tmp_path)
    argv = ["--root", str(root), "check-pr", "--strict", "PR_FILE", "--commits", SHA]
    assert _main(argv, capsys, tmp_path, body) == (
        1,
        [*E04_EMPTY, "pr.md: ## Gate evidence: no commit SHA"],
    )


@pytest.mark.ac("E08-AC-11")
def test_empty_stdin_gives_problems(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    code = docs.main(["--root", str(_root(tmp_path)), "check-pr", "--strict"])
    lines = capsys.readouterr().out.splitlines()
    assert code == 1
    assert lines == [
        *(line.replace("pr.md", "stdin") for line in E04_EMPTY),
        "stdin: ## Gate evidence: no commit SHA",
    ]


@pytest.mark.ac("E08-AC-11")
@pytest.mark.parametrize("strict", [["--strict"], []])
def test_a_missing_body_file_is_a_problem_not_a_crash(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], strict: list[str]
) -> None:
    root = _root(tmp_path)
    code, lines = _main(
        ["--root", str(root), "check-pr", *strict, "PR_FILE"], capsys, tmp_path, None
    )
    assert code == 1
    assert len(lines) == 1
    assert lines[0].startswith("pr.md: file: cannot read")
