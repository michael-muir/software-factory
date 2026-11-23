"""E18/T3, issue #87: `find_repo` in run.py and jobs.py must not fail when `git worktree list`
fails for a moment, which another process's `git worktree add` can cause.

A regression test for E16 AC-01 and E18 AC-01 ("run anywhere inside a repo, it works on that
repo's git common directory"). Expectations come from issue #87's proposed fix.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

import jobs
import run as runner
from tests._jobs import git, jobs_repo
from tests._jobs_index import real

MODULES = {"run": runner, "jobs": jobs}
MAIN_WORKTREE_ERROR = "cannot find the repository's main worktree"


class FlakyListing:
    """Wraps a module's `_git`: `git worktree list` fails the first `fails` times."""

    def __init__(self, module: Any, fails: int) -> None:
        self.real = module._git
        self.fails = fails
        self.listings = 0

    def __call__(self, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
        if args[:2] == ("worktree", "list"):
            self.listings += 1
            if self.listings <= self.fails:
                return subprocess.CompletedProcess(["git", *args], 128, "", "fatal: busy")
        result: subprocess.CompletedProcess[str] = self.real(cwd, *args)
        return result


def listed_main(repo: Path) -> str:
    """What `git worktree list` names first. For a separate git dir that is the git dir itself,
    a git quirk; the fallback reports what git says."""
    out = git(repo, "worktree", "list", "--porcelain")
    return real(next(ln for ln in out.splitlines() if ln.startswith("worktree "))[9:])


def separate_git_dir_repo(tmp_path: Path) -> Path:
    """A repo whose git directory isn't `<root>/.git`, so its main worktree must be listed."""
    root = tmp_path / "sep"
    subprocess.run(
        [
            "git",
            "init",
            "-q",
            "-b",
            "main",
            "--separate-git-dir",
            str(tmp_path / "gitdir"),
            str(root),
        ],
        check=True,
    )
    (root / "README.md").write_text("x\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "x")
    return root


@pytest.mark.parametrize("name", sorted(MODULES))
@pytest.mark.ac("E16-AC-01")
@pytest.mark.ac("E18-AC-01")
def test_a_normal_repo_needs_no_listing_at_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    module = MODULES[name]
    repo = jobs_repo(tmp_path)
    side = tmp_path / "side"
    git(repo, "worktree", "add", "-q", "-b", "side", str(side))
    flaky = FlakyListing(module, fails=10**6)  # every listing fails
    monkeypatch.setattr(module, "_git", flaky)
    sub = repo / "a" / "b"
    sub.mkdir(parents=True)
    for cwd in (repo, sub, side):
        found = module.find_repo(cwd)
        assert real(found.main) == real(repo)
        assert real(found.store) == real(repo / ".git" / "factory")
    assert flaky.listings == 0


@pytest.mark.parametrize("name", sorted(MODULES))
@pytest.mark.ac("E16-AC-01")
@pytest.mark.ac("E18-AC-01")
def test_a_listing_that_fails_for_a_moment_is_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    module = MODULES[name]
    repo = separate_git_dir_repo(tmp_path)
    flaky = FlakyListing(module, fails=2)
    monkeypatch.setattr(module, "_git", flaky)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    expected = listed_main(repo)
    found = module.find_repo(repo)
    assert real(found.main) == expected
    assert real(found.store) == real(tmp_path / "gitdir" / "factory")
    assert flaky.listings == 3


@pytest.mark.parametrize("name", sorted(MODULES))
@pytest.mark.ac("E16-AC-01")
@pytest.mark.ac("E18-AC-01")
def test_a_listing_that_keeps_failing_is_still_bad_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    module = MODULES[name]
    repo = separate_git_dir_repo(tmp_path)
    flaky = FlakyListing(module, fails=10**6)
    monkeypatch.setattr(module, "_git", flaky)
    pauses: list[float] = []
    monkeypatch.setattr(module.time, "sleep", pauses.append)
    with pytest.raises(module.BadInput, match=MAIN_WORKTREE_ERROR):
        module.find_repo(repo)
    assert flaky.listings >= 3, "it tried more than once"
    assert pauses == sorted(pauses), "with a growing pause between tries"
    assert 0 < sum(pauses) <= 5


@pytest.mark.parametrize("name", sorted(MODULES))
@pytest.mark.ac("E16-AC-01")
@pytest.mark.ac("E18-AC-01")
def test_a_separate_git_dir_repo_gives_one_answer_from_every_worktree(
    tmp_path: Path, name: str
) -> None:
    module = MODULES[name]
    repo = separate_git_dir_repo(tmp_path)
    side = tmp_path / "side"
    git(repo, "worktree", "add", "-q", "-b", "side", str(side))
    from_main, from_side = module.find_repo(repo), module.find_repo(side)
    assert real(from_side.main) == real(from_main.main) == listed_main(repo)
    assert real(from_side.store) == real(from_main.store)
