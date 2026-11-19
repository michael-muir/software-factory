"""REVIEW-T3: changed-lines mutation (E06 AC-05c; E05 placeholders {mutation_scope}, {base_ref}).

Expectations come from the approved AC-05c, not from the implementation.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import changed_lines
import mutate_python
import mutate_ts
from tests._ac import REPO_ROOT
from tests._gate import gate_repo, profile, run_gate
from tests._repo import git_repo

PROFILES = REPO_ROOT / "kit" / ".factory" / "gates" / "profiles"
TEN = "".join(f"line {n}\n" for n in range(1, 11))


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def committed(root: Path, files: dict[str, str], message: str = "base") -> None:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8", newline="\n")
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", message)


def repo_with_base(tmp_path: Path, files: dict[str, str]) -> Path:
    root = git_repo(tmp_path / "repo")
    git(root, "checkout", "-q", "-b", "main")
    committed(root, files)
    git(root, "checkout", "-q", "-b", "work")
    return root


# --- changed line ranges ------------------------------------------------------------------------


@pytest.mark.ac("E06-AC-05c")
def test_added_and_modified_lines_since_the_merge_base_count(tmp_path: Path) -> None:
    root = repo_with_base(tmp_path, {"a.py": TEN, "same.py": TEN})
    lines = TEN.splitlines(keepends=True)
    lines[2] = "changed 3\n"  # modified, committed on the branch
    lines[6:6] = ["new a\n", "new b\n"]  # two lines added after line 6: now lines 7 and 8
    del lines[10]  # old line 9 (now index 10) deleted: no mutants
    committed(root, {"a.py": "".join(lines)}, "work")
    text = (root / "a.py").read_text(encoding="utf-8").replace("line 1\n", "edited 1\n")
    (root / "a.py").write_text(text, encoding="utf-8", newline="\n")  # uncommitted
    found = changed_lines.changed_lines(root, "main", ["a.py", "same.py"])
    assert found == {"a.py": [(1, 1), (3, 3), (7, 8)], "same.py": []}


@pytest.mark.ac("E06-AC-05c")
def test_a_new_untracked_file_counts_in_full(tmp_path: Path) -> None:
    root = repo_with_base(tmp_path, {"a.py": TEN})
    (root / "new.py").write_text("x = 1\ny = 2\nz = 3\n", encoding="utf-8")
    assert changed_lines.changed_lines(root, "main", ["new.py"]) == {"new.py": [(1, 3)]}


@pytest.mark.ac("E06-AC-05c")
def test_a_file_added_on_the_branch_counts_in_full(tmp_path: Path) -> None:
    root = repo_with_base(tmp_path, {"a.py": TEN})
    committed(root, {"b.py": "one\ntwo\n"}, "add b")
    assert changed_lines.changed_lines(root, "main", ["b.py"]) == {"b.py": [(1, 2)]}


@pytest.mark.ac("E06-AC-05c")
def test_an_unknown_base_ref_is_an_error(tmp_path: Path) -> None:
    root = repo_with_base(tmp_path, {"a.py": TEN})
    with pytest.raises(ValueError, match="no-such-branch"):
        changed_lines.changed_lines(root, "no-such-branch", ["a.py"])


@pytest.mark.ac("E06-AC-05c")
def test_in_ranges() -> None:
    ranges = [(1, 1), (3, 5)]
    assert [n for n in range(0, 8) if changed_lines.in_ranges(n, ranges)] == [1, 3, 4, 5]


# --- the gate passes the scope and base ---------------------------------------------------------


ECHO = "import sys; open('ran-args.txt', 'w').write(' '.join(sys.argv[1:]))"


@pytest.mark.ac("E06-AC-05c")
def test_the_gate_fills_mutation_scope_and_base_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    command = [sys.executable, "-c", ECHO, "{mutation_scope}", "{base_ref}"]
    repo = gate_repo(
        tmp_path / "repo",
        {"py.toml": profile("py", ["marker.txt"], {"format": command})},
        files={"marker.txt": "x\n"},
    )
    assert run_gate(repo, monkeypatch, capsys)[0] == 0
    assert (repo / "ran-args.txt").read_text(encoding="utf-8") == "changed-lines main"
    assert run_gate(repo, monkeypatch, capsys, "--base-ref", "HEAD")[0] == 0
    assert (repo / "ran-args.txt").read_text(encoding="utf-8") == "changed-lines HEAD"


@pytest.mark.ac("E06-AC-05c")
@pytest.mark.parametrize("name", ["python.toml", "ts-js.toml"])
def test_the_shipped_profiles_pass_scope_and_base(name: str) -> None:
    profile_data = tomllib.loads((PROFILES / name).read_text(encoding="utf-8"))
    command = profile_data["checks"]["mutation"]["command"]
    text = " ".join(command)
    assert "--scope {mutation_scope} --base-ref {base_ref}" in text, command
    assert command[-1] == "{changed_files}"


# --- Python: mutants outside the changed lines are dropped before sampling ----------------------


CALC = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"


class FakeCosmicRay:
    """Records the jobs exec saw; init lays down one mutant on line 2 and one on line 6."""

    def __init__(self) -> None:
        self.tested: list[str] = []

    def __call__(self, *args: str, cwd: Path) -> None:
        command, _config, session = args
        db = sqlite3.connect(session)
        with db:
            if command == "init":
                db.execute(
                    "CREATE TABLE mutation_specs (job_id, module_path, operator_name, occurrence,"
                    " start_pos_row, start_pos_col)"
                )
                db.execute("CREATE TABLE work_items (job_id)")
                for job, row in (("on2", 2), ("on6", 6)):
                    db.execute(
                        "INSERT INTO mutation_specs VALUES (?, 'calc.py', 'op', 0, ?, 4)",
                        (job, row),
                    )
                    db.execute("INSERT INTO work_items VALUES (?)", (job,))
            else:
                self.tested = [r[0] for r in db.execute("SELECT job_id FROM work_items")]
                db.execute("CREATE TABLE work_results (job_id, test_outcome)")
                db.executemany(
                    "INSERT INTO work_results VALUES (?, 'KILLED')", [(j,) for j in self.tested]
                )
        db.close()


def python_repo(tmp_path: Path) -> Path:
    test = (
        "from calc import add, sub\n\n\ndef test_calc() -> None:\n"
        "    assert add(2, 3) == 5\n    assert sub(5, 3) == 2\n"
    )
    root = repo_with_base(
        tmp_path,
        {
            "pyproject.toml": "[project]\nname = 'p'\nversion = '0'\n",
            "calc.py": CALC,
            "test_calc.py": test,
        },
    )
    return root


@pytest.mark.ac("E06-AC-05c")
def test_only_mutants_on_changed_lines_are_tested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = python_repo(tmp_path)
    (root / "calc.py").write_text(CALC.replace("return a + b", "return b + a"), encoding="utf-8")
    fake = FakeCosmicRay()
    monkeypatch.setattr(mutate_python, "_cosmic_ray", fake)
    code = mutate_python.run(root, ["calc.py"], 60.0, scope="changed-lines", base_ref="main")
    assert code == 0, capsys.readouterr()
    assert fake.tested == ["on2"]
    assert "1 mutant on changed lines (of 2 in 1 file)" in capsys.readouterr().out


@pytest.mark.ac("E06-AC-05c")
def test_no_mutants_on_changed_lines_is_nothing_to_mutate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = python_repo(tmp_path)
    (root / "calc.py").write_text("# a comment\n" + CALC, encoding="utf-8")  # shifts rows by one
    fake = FakeCosmicRay()
    monkeypatch.setattr(mutate_python, "_cosmic_ray", fake)
    code = mutate_python.run(root, ["calc.py"], 60.0, scope="changed-lines", base_ref="main")
    assert code == 0
    assert "no mutants on changed lines" in capsys.readouterr().out
    assert fake.tested == []


@pytest.mark.ac("E06-AC-05c")
def test_scope_all_and_older_profiles_mutate_whole_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = python_repo(tmp_path)
    (root / "calc.py").write_text(CALC.replace("return a + b", "return b + a"), encoding="utf-8")
    for scope in ("all", None):
        fake = FakeCosmicRay()
        monkeypatch.setattr(mutate_python, "_cosmic_ray", fake)
        assert mutate_python.run(root, ["calc.py"], 60.0, scope=scope, base_ref="main") == 0
        assert sorted(fake.tested) == ["on2", "on6"]


@pytest.mark.ac("E06-AC-05c")
def test_changed_lines_needs_a_base_ref(capsys: pytest.CaptureFixture[str]) -> None:
    assert mutate_python.main(["--min", "60", "--scope", "changed-lines", "calc.py"]) == 2
    assert "--base-ref" in capsys.readouterr().err


# --- TS/JS: Stryker gets the changed ranges -----------------------------------------------------


@pytest.mark.ac("E06-AC-05c")
def test_stryker_mutates_changed_ranges_only() -> None:
    lines = {"src/a.ts": [(3, 3), (7, 9)], "src/b.ts": [], "src/c.ts": [(1, 4)]}
    assert mutate_ts.mutate_entries(["src/a.ts", "src/b.ts", "src/c.ts"], lines) == [
        "src/a.ts:3-3",
        "src/a.ts:7-9",
        "src/c.ts:1-4",
    ]
    assert mutate_ts.mutate_entries(["src/a.ts", "src/b.ts"], None) == ["src/a.ts", "src/b.ts"]
