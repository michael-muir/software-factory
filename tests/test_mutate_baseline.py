"""E13-T11: a kill test that fails before any mutation fails mutation (E06 AC-10, amended 28 Nov
2026 by the product owner's decision on #120).

In the live run on #82, the gate's tests check passed on the product owner's Windows machine, but
mutation's kill test failed in the copy and in the project. `mutate_python.py` exited 0 and threw
pytest's output away, so mutation passed with no mutant scored and nobody could tell which test
failed. Now:

- a kill test that fails in the copy and in the project exits 1, a mutation failure;
- the helper prints the tail of pytest's output, its short test summary included, so the failing
  test is named;
- a kill test that passes in the project but fails in the copy is still an environment error.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import mutate_python
from tests._repo import git_repo

AC = "E06-AC-10"
FAILING = "    assert add(2, 3) == 6\n"


def project(tmp_path: Path, test_body: str) -> Path:
    """A tiny git project: `calc.add` and a test of it with this body."""
    root = git_repo(tmp_path / "proj")
    files = {
        "pyproject.toml": "[project]\nname = 'p'\nversion = '0'\n",
        "calc.py": "def add(a: int, b: int) -> int:\n    return a + b\n",
        "test_calc.py": "from calc import add\n\n\ndef test_add_sums() -> None:\n" + test_body,
    }
    for rel, text in files.items():
        (root / rel).write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", *files], cwd=root, check=True)
    return root


class NoCosmicRay:
    """cosmic-ray must never run when the kill test fails before any mutation."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *args: str, cwd: Path) -> None:
        self.calls.append(args)
        raise AssertionError(f"cosmic-ray ran: {args}")


@pytest.mark.ac(AC)
def test_a_kill_test_failing_before_any_mutation_is_a_mutation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path, FAILING)
    fake = NoCosmicRay()
    monkeypatch.setattr(mutate_python, "_cosmic_ray", fake)
    code = mutate_python.run(root, ["calc.py"], 60.0)
    out = capsys.readouterr().out
    assert code == 1, out
    assert "the kill test fails before any mutation, so no mutant can be scored" in out
    assert fake.calls == []


@pytest.mark.ac(AC)
def test_the_failure_names_the_failing_test_from_pytests_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path, FAILING)
    monkeypatch.setattr(mutate_python, "_cosmic_ray", NoCosmicRay())
    mutate_python.run(root, ["calc.py"], 60.0)
    out = capsys.readouterr().out
    assert "short test summary info" in out
    assert "FAILED test_calc.py::test_add_sums" in out


@pytest.mark.ac(AC)
def test_only_the_tail_of_pytests_output_is_printed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    noisy = "".join(f"    print('noise line {n}')\n" for n in range(200)) + FAILING
    root = project(tmp_path, noisy)
    monkeypatch.setattr(mutate_python, "_cosmic_ray", NoCosmicRay())
    assert mutate_python.run(root, ["calc.py"], 60.0) == 1
    out = capsys.readouterr().out
    assert "FAILED test_calc.py::test_add_sums" in out
    assert "noise line 0" not in out
    tail = out.split("so no mutant can be scored", 1)[1]
    assert len(tail.strip().splitlines()) <= 30


@pytest.mark.ac(AC)
def test_main_exits_1_on_a_failing_kill_test(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = project(tmp_path, FAILING)
    monkeypatch.setattr(mutate_python, "_cosmic_ray", NoCosmicRay())
    monkeypatch.chdir(root)
    assert mutate_python.main(["--min", "60", "calc.py"]) == 1
    assert "no mutant can be scored" in capsys.readouterr().out


@pytest.mark.ac(AC)
def test_a_copy_that_fails_where_the_project_passes_is_still_an_environment_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    body = "    assert open('ignored.txt').read() == 'secret\\n'\n"
    root = project(tmp_path, body)
    (root / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (root / "ignored.txt").write_text("secret\n", encoding="utf-8")
    monkeypatch.setattr(mutate_python, "_cosmic_ray", NoCosmicRay())
    monkeypatch.chdir(root)
    assert mutate_python.main(["--min", "60", "calc.py"]) == 2
    assert "copy" in capsys.readouterr().err
