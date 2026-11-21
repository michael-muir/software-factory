"""E08/T4: evidence survives a clean rebase. `evidence.py` records the commit's patch-id, and
`check-pr --commits` matches a PR commit with the same `git patch-id --stable` (ADR 0027).

Covers E08 AC-06 and AC-10 as amended on 20 Nov 2026. Expectations come from the spec's change
note and ADR 0027, not from the implementation. The fixture repos use a made-up epic, E42.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import docs
import evidence
from tests._gate import git

SPEC = """# E42 · Widgets — Spec

Issue: [#42](https://example.com/issues/42) · Milestone: M1 · Depends on: none
Status: **Approved by the product owner** · Next: tests

## Acceptance criteria

- **AC-01** Widgets can be added.
"""
TASK = """+++
id = "E42-T1"
title = "Widgets"
status = "in-review"
review_round = 0
created = 2026-11-20T00:00:00Z
updated = 2026-11-20T00:00:00Z
+++

## Goal

## Acceptance criteria

## Notes
"""
TESTS = 'import pytest\n\n\n@pytest.mark.ac("E42-AC-01")\ndef test_one() -> None:\n    pass\n'
LOCK = (
    'task = "E42-T1"\nlocked = 2026-11-20T00:00:00Z\n\n[[files]]\n'
    f'path = "tests/test_widgets.py"\nsha256 = "{"0" * 64}"\n'
)
FAKE = "0123456789abcdef0123456789abcdef01234567"


def _write(repo: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8", newline="\n")


def _head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").strip()


def patch_id(repo: Path, commit: str) -> str:
    shown = subprocess.run(
        ["git", "show", commit], cwd=repo, capture_output=True, check=True
    ).stdout
    out = subprocess.run(
        ["git", "patch-id", "--stable"], cwd=repo, input=shown, capture_output=True, check=True
    ).stdout.decode()
    return out.split()[0] if out.strip() else ""


def _repo(tmp_path: Path) -> tuple[Path, str]:
    """A repo on main with the task's files, and branch `feature` one commit ahead (returned)."""
    repo = tmp_path / "widgets"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    _write(
        repo,
        {
            "docs/specs/E42-widgets.md": SPEC,
            ".agentic/tasks/E42-T1.md": TASK,
            ".agentic/locks/E42-T1.toml": LOCK,
            "tests/test_widgets.py": TESTS,
            "README.md": "widgets\n",
        },
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    git(repo, "switch", "-q", "-c", "feature")
    _write(repo, {"widgets.py": "def count() -> int:\n    return 2\n"})
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "count widgets")
    return repo, _head(repo)


def _rebase(repo: Path, *, change: bool = False) -> str:
    """Move main on, then put feature's commit on top of it: the new commit's SHA."""
    git(repo, "switch", "-q", "main")
    _write(repo, {"README.md": "widgets, moved on\n"})
    git(repo, "commit", "-q", "-am", "main moves on")
    git(repo, "switch", "-q", "-c", "rebased")
    git(repo, "cherry-pick", "feature")
    if change:
        _write(repo, {"widgets.py": "def count() -> int:\n    return 3\n"})
        git(repo, "commit", "-q", "-a", "--amend", "--no-edit")
    return _head(repo)


def _report(tmp_path: Path, commit: str) -> Path:
    data = {
        "verdict": "pass",
        "root": "/work/widgets",
        "base_ref": "main",
        "commit": commit,
        "dirty": False,
        "profiles": ["python"],
        "changed_files": [],
        "locks": {"locked": 1, "broken": []},
        "docs": {"checked": 1, "problems": []},
        "checks": [
            {
                "profile": "python",
                "check": "tests",
                "status": "pass",
                "reason": "",
                "exit_code": 0,
                "duration_s": 1.5,
                "command": ["pytest"],
                "output_tail": "",
            }
        ],
    }
    path = tmp_path / "gate-report.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _draft(repo: Path, report: Path, capsys: pytest.CaptureFixture[str]) -> str:
    code = evidence.main(["--root", str(repo), "E42-T1", "--gate-report", str(report)])
    out = capsys.readouterr()
    assert (code, out.err) == (0, ""), out.err
    return out.out


def _filled(body: str) -> str:
    return body.replace("TODO(author): what this PR delivers", "Widgets").replace(
        "TODO(author): what each change does, and why.", "A count."
    )


def _evidence_line(body: str) -> str:
    return body.split("## Gate evidence\n\n", 1)[1].split("\n", 1)[0]


def _body(commit: str, recorded: str | None) -> str:
    """A complete body naming `commit`, with a recorded patch-id or none."""
    pid = f" (patch-id `{recorded}`)" if recorded else ""
    return f"""E42/T1: Widgets. Covers E42 **AC-01**. Refs #42.

## What changes

- A count.

## Acceptance criteria

- **AC-01** `tests/test_widgets.py`: `test_one`

## Tests

1 test in 1 file.

## Gate evidence

**PASS** on `{commit[:12]}`{pid} · Locks: 1 locked file, none changed

## Findings

None.
"""


def _check(body: str, root: Path, commits: list[str]) -> list[str]:
    return [str(p) for p in docs.lint_pr_strict(body, "pr.md", root, commits)]


# --- AC-06: the draft records the commit's patch-id ---------------------------------------------


@pytest.mark.ac("E08-AC-06")
def test_the_summary_line_records_the_commits_patch_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, commit = _repo(tmp_path)
    body = _draft(repo, _report(tmp_path, commit), capsys)
    pid = patch_id(repo, commit)
    assert len(pid) == 40
    assert _evidence_line(body) == (
        f"**PASS** on `{commit[:12]}` (patch-id `{pid}`) · Locks: 1 locked file, none changed"
        " · Docs: 1 checked, no problems · python tests pass 1.50 s"
    )


@pytest.mark.ac("E08-AC-06")
def test_a_commit_with_no_diff_records_no_patch_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = _repo(tmp_path)
    git(repo, "commit", "-q", "--allow-empty", "-m", "nothing")
    commit = _head(repo)
    body = _draft(repo, _report(tmp_path, commit), capsys)
    assert _evidence_line(body).startswith(f"**PASS** on `{commit[:12]}` · Locks: ")


@pytest.mark.ac("E08-AC-06")
def test_a_commit_git_does_not_have_records_no_patch_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = _repo(tmp_path)
    body = _draft(repo, _report(tmp_path, FAKE), capsys)
    assert _evidence_line(body).startswith(f"**PASS** on `{FAKE[:12]}` · Locks: ")


@pytest.mark.ac("E08-AC-06")
@pytest.mark.ac("E08-AC-10")
def test_a_drafted_body_passes_on_its_own_commit_and_after_a_clean_rebase(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, commit = _repo(tmp_path)
    body = _filled(_draft(repo, _report(tmp_path, commit), capsys))
    assert _check(body, repo, [commit]) == []
    rebased = _rebase(repo)
    assert rebased != commit
    assert _check(body, repo, [rebased]) == []


# --- AC-10: matching by patch-id ----------------------------------------------------------------


@pytest.mark.ac("E08-AC-10")
def test_a_recorded_patch_id_matches_a_rebased_commit_git_no_longer_has(tmp_path: Path) -> None:
    repo, commit = _repo(tmp_path)
    pid = patch_id(repo, commit)
    rebased = _rebase(repo)
    assert _check(_body(FAKE, pid), repo, [rebased]) == []


@pytest.mark.ac("E08-AC-10")
def test_a_changed_commit_still_fails(tmp_path: Path) -> None:
    repo, commit = _repo(tmp_path)
    pid = patch_id(repo, commit)
    changed = _rebase(repo, change=True)
    for body in (_body(commit, pid), _body(FAKE, pid)):
        found = _check(body, repo, [changed])
        assert len(found) == 1, found
        assert found[0].startswith("pr.md: ## Gate evidence: evidence is for ")
        assert "which is not a commit of this PR" in found[0]
        assert changed[:7] in found[0]


@pytest.mark.ac("E08-AC-10")
def test_the_commits_own_patch_id_wins_over_a_wrong_record(tmp_path: Path) -> None:
    repo, commit = _repo(tmp_path)
    rebased = _rebase(repo)
    assert _check(_body(commit, "f" * 40), repo, [rebased]) == []


@pytest.mark.ac("E08-AC-10")
def test_a_record_that_disagrees_with_the_commit_is_ignored(tmp_path: Path) -> None:
    repo, commit = _repo(tmp_path)
    other = _rebase(repo, change=True)
    found = _check(_body(commit, patch_id(repo, other)), repo, [other])
    assert len(found) == 1, found
    assert "which is not a commit of this PR" in found[0]


@pytest.mark.ac("E08-AC-10")
def test_with_no_record_and_no_commit_only_the_sha_can_match(tmp_path: Path) -> None:
    repo, _ = _repo(tmp_path)
    rebased = _rebase(repo)
    found = _check(_body(FAKE, None), repo, [rebased])
    assert len(found) == 1, found
    assert found[0].startswith(f"pr.md: ## Gate evidence: evidence is for {FAKE[:12]}, ")


@pytest.mark.ac("E08-AC-10")
def test_outside_a_git_repo_only_the_sha_can_match(tmp_path: Path) -> None:
    repo, commit = _repo(tmp_path)
    pid = patch_id(repo, commit)
    rebased = _rebase(repo)
    plain = tmp_path / "plain"
    _write(plain, {"docs/specs/E42-widgets.md": SPEC})
    found = _check(_body(FAKE, pid), plain, [rebased])
    assert len(found) == 1, found
    assert "which is not a commit of this PR" in found[0]
    assert _check(_body(rebased, None), plain, [rebased]) == []


@pytest.mark.ac("E08-AC-10")
def test_the_patch_id_is_not_taken_for_the_commit(tmp_path: Path) -> None:
    repo, commit = _repo(tmp_path)
    other = "a" * 40
    found = _check(_body(FAKE, patch_id(repo, commit)), repo, [other])
    assert len(found) == 1, found
    assert found[0].startswith(f"pr.md: ## Gate evidence: evidence is for {FAKE[:12]}, ")
    assert other[:7] in found[0]


@pytest.mark.ac("E08-AC-10")
def test_check_pr_commits_passes_a_rebased_body_on_the_command_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, commit = _repo(tmp_path)
    body = tmp_path / "pr.md"
    body.write_text(_body(FAKE, patch_id(repo, commit)), encoding="utf-8")
    rebased = _rebase(repo)
    argv = ["--root", str(repo), "check-pr", "--strict", str(body), "--commits", rebased]
    assert docs.main(argv) == 0
    assert capsys.readouterr().out == ""
