"""Mutation-score helper for the Python gate profile (E06, ADR 0010). Standard library only.

Usage:
    python .factory/gates/tools/mutate_python.py --min PERCENT [--scope S --base-ref REF] FILE...

Runs cosmic-ray on the given non-test files with the interpreter running this script, in a copy
of the project (never the working tree), then compares the share of killed mutants to PERCENT.
Exit codes: 0 at or above PERCENT, nothing to mutate, or tests that already fail (the tests check
reports those); 1 below; 2 a missing tool, bad settings in [tool.software-factory.mutation], or a
copy whose tests fail where the project's pass.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import random
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

# The shared changed_lines.py beside this file, found even under `python -I`, and imported
# without writing __pycache__ into the repo (the gate fails a check that modifies it, ADR 0008).
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.dont_write_bytecode = True
from changed_lines import Ranges, changed_lines, in_ranges  # noqa: E402

DEFAULT_MAX_MUTANTS = 100
MUTANT_TIMEOUT_S = 300.0
SECTION = "[tool.software-factory.mutation]"


class HelperError(Exception):
    """A missing tool or invalid setting: exit 2."""


@contextlib.contextmanager
def _db(path: Path) -> Iterator[sqlite3.Connection]:
    """Commit on success and always close: an open handle blocks deleting the file on Windows."""
    db = sqlite3.connect(path)
    try:
        with db:
            yield db
    finally:
        db.close()


@dataclass(frozen=True)
class Settings:
    max_mutants: int = DEFAULT_MAX_MUTANTS
    test_args: list[str] = field(default_factory=list)


def load_settings(root: Path) -> Settings:
    path = root / "pyproject.toml"
    if not path.is_file():
        return Settings()
    with path.open("rb") as f:
        data = tomllib.load(f)
    section = data.get("tool", {}).get("software-factory", {}).get("mutation", {})
    max_mutants = section.get("max-mutants", DEFAULT_MAX_MUTANTS)
    if not isinstance(max_mutants, int) or isinstance(max_mutants, bool) or max_mutants < 1:
        raise HelperError(f"{SECTION} max-mutants must be a positive integer")
    test_args = section.get("test-args", [])
    if not isinstance(test_args, list) or not all(isinstance(a, str) for a in test_args):
        raise HelperError(f"{SECTION} test-args must be a list of strings")
    return Settings(max_mutants, list(test_args))


def is_test_file(path: str) -> bool:
    parts = PurePosixPath(path.replace("\\", "/")).parts
    name = parts[-1]
    if name == "conftest.py" or name.endswith("_test.py"):
        return True
    if name.startswith("test_") and name.endswith(".py"):
        return True
    return any(part in ("tests", "test") for part in parts[:-1])


def is_installed_kit(path: str) -> bool:
    return PurePosixPath(path.replace("\\", "/")).parts[0] == ".factory"


def select_sources(paths: Sequence[str]) -> list[str]:
    """The given Python files that are project code, in the order given (spec AC-05).

    Tests are excluded, and so is the installed kit under .factory/ (factory machinery).
    """
    return [
        p for p in paths if p.endswith(".py") and not is_test_file(p) and not is_installed_kit(p)
    ]


def test_command(python: str, extra: Sequence[str]) -> list[str]:
    """The kill test: the pinned interpreter running pytest, stopping at the first failure."""
    return [python, "-m", "pytest", "-q", "-x", *extra]


def sample(ids: Sequence[str], seed: bytes, limit: int) -> list[str]:
    """A deterministic sample of at most `limit` ids: same ids and seed give the same sample."""
    ordered = sorted(ids)
    if len(ordered) <= limit:
        return ordered
    rng = random.Random(int.from_bytes(hashlib.sha256(seed).digest(), "big"))
    return sorted(rng.sample(ordered, limit))


def content_seed(root: Path, files: Sequence[str]) -> bytes:
    digest = hashlib.sha256()
    for rel in sorted(files):
        digest.update(rel.encode("utf-8") + b"\0")
        digest.update((root / rel).read_bytes() + b"\0")
    return digest.digest()


def project_copy(root: Path, dest: Path) -> None:
    """A shared clone of the repo at HEAD (history, index, file modes), with the files git sees
    (tracked, and untracked but not ignored) copied over it as they are now.

    cosmic-ray swaps each mutant into the files it mutates, so it runs here: a killed or
    interrupted run can never leave a mutant in the working tree.
    """

    def git(*args: str, cwd: Path = root, check: bool = True) -> bytes:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=check).stdout

    git("clone", "--quiet", "--shared", "--no-checkout", str(root), str(dest))
    git(
        "reset", "--quiet", cwd=dest, check=False
    )  # the index at HEAD; a repo with no commits has none
    listed = git("ls-files", "-z", "--cached", "--others", "--exclude-standard")
    for rel in filter(None, listed.decode("utf-8", errors="surrogateescape").split("\0")):
        source = root / rel
        if source.is_file():
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest / rel)


TAIL_LINES = 30


def kill_test(command: Sequence[str], cwd: Path) -> tuple[bool, str]:
    """Run the kill test once: whether it passed, and its output (stdout, then stderr)."""
    done = subprocess.run(
        list(command), cwd=cwd, capture_output=True, text=True, errors="replace", check=False
    )
    return done.returncode == 0, done.stdout + done.stderr


def tests_pass(command: Sequence[str], cwd: Path) -> bool:
    return kill_test(command, cwd)[0]


def tail(output: str, n: int = TAIL_LINES) -> str:
    """The last `n` lines of pytest's output, where its short test summary is."""
    return "\n".join(output.rstrip().splitlines()[-n:])


def _require(module: str, name: str) -> None:
    if importlib.util.find_spec(module) is None:
        raise HelperError(f"{name} is not installed in this environment ({sys.executable})")


def _cosmic_ray(*args: str, cwd: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "cosmic_ray.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise HelperError(f"cosmic-ray {args[0]} failed:\n{result.stdout}{result.stderr}")


def _write_config(path: Path, sources: Sequence[str], command: Sequence[str]) -> None:
    # cosmic-ray splits test-command with shlex, so pass posix-style paths, safely quoted.
    posix = [Path(command[0]).as_posix(), *command[1:]]
    lines = [
        "[cosmic-ray]",
        f"module-path = {json.dumps(list(sources))}",
        f"timeout = {MUTANT_TIMEOUT_S}",
        "excluded-modules = []",
        f"test-command = {json.dumps(shlex.join(posix))}",
        "",
        "[cosmic-ray.distributor]",
        'name = "local"',
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _stable_keys(session: Path) -> dict[str, str]:
    """job_id -> a key that is the same on every init (job ids are random UUIDs)."""
    with _db(session) as db:
        rows = db.execute(
            "SELECT job_id, module_path, operator_name, occurrence, start_pos_row, start_pos_col "
            "FROM mutation_specs"
        ).fetchall()
    return {row[0]: "|".join(str(part) for part in row[1:]) for row in rows}


def _keep_only(session: Path, keep_jobs: set[str]) -> None:
    with _db(session) as db:
        jobs = [row[0] for row in db.execute("SELECT job_id FROM work_items")]
        drop = [(job,) for job in jobs if job not in keep_jobs]
        db.executemany("DELETE FROM mutation_specs WHERE job_id = ?", drop)
        db.executemany("DELETE FROM work_items WHERE job_id = ?", drop)


def _on_lines(session: Path, lines: dict[str, Ranges]) -> set[str]:
    """The jobs whose mutant starts on a changed line."""
    with _db(session) as db:
        rows = db.execute(
            "SELECT job_id, module_path, start_pos_row FROM mutation_specs"
        ).fetchall()
    return {job for job, path, row in rows if in_ranges(row, lines.get(Path(path).as_posix(), []))}


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def _score(session: Path) -> tuple[int, int]:
    with _db(session) as db:
        rows = db.execute("SELECT test_outcome FROM work_results").fetchall()
    outcomes = [str(row[0]).upper() for row in rows]
    return outcomes.count("KILLED"), outcomes.count("SURVIVED")


def run(
    root: Path,
    files: Sequence[str],
    minimum: float,
    *,
    scope: str | None = None,
    base_ref: str | None = None,
) -> int:
    """Mutate `files`: whole files, or with scope "changed-lines" only lines changed since
    `base_ref` (E06 AC-05c)."""
    settings = load_settings(root)
    sources = select_sources(files)
    if not sources:
        print("no source files to mutate")
        return 0
    lines: dict[str, Ranges] | None = None
    if scope == "changed-lines":
        try:
            lines = changed_lines(root, base_ref or "", sources)
        except ValueError as exc:
            raise HelperError(str(exc)) from exc
    _require("cosmic_ray", "cosmic-ray")
    _require("pytest", "pytest")

    workdir = Path(tempfile.mkdtemp(prefix="factory-mutate-"))
    try:
        copy, config, session = (
            workdir / "project",
            workdir / "cosmic-ray.toml",
            workdir / "session.sqlite",
        )
        command = test_command(sys.executable, settings.test_args)
        project_copy(root, copy)
        passed, _ = kill_test(command, copy)
        if not passed:
            passed, output = kill_test(command, root)
            if passed:
                raise HelperError(
                    "the tests pass in the project but fail in the copy that mutation runs in; "
                    "do they need a git-ignored file or the git history?"
                )
            # A mutation failure, whatever the tests check says (E06 AC-10, 28 Nov 2026).
            print(f"kill test: {shlex.join(['python', *command[1:]])}")
            print("the kill test fails before any mutation, so no mutant can be scored")
            print(tail(output))
            return 1
        _write_config(config, sources, command)
        _cosmic_ray("init", str(config), str(session), cwd=copy)

        keys = _stable_keys(session)
        if not keys:
            print(f"mutating {len(sources)} file(s): no mutants generated")
            return 0
        if lines is not None:
            on_lines = _on_lines(session, lines)
            every = f"of {len(keys)} in {_count(len(sources), 'file')}"
            if not on_lines:
                print(f"no mutants on changed lines ({every})")
                return 0
            print(f"{_count(len(on_lines), 'mutant')} on changed lines ({every})")
            keys = {job: key for job, key in keys.items() if job in on_lines}
            _keep_only(session, on_lines)
        total = len(keys)
        chosen = set(sample(list(keys.values()), content_seed(root, sources), settings.max_mutants))
        if len(chosen) < total:
            _keep_only(session, {job for job, key in keys.items() if key in chosen})
            print(f"sampled {len(chosen)} of {total} mutants")
        else:
            print(f"testing all {total} mutants")

        _cosmic_ray("exec", str(config), str(session), cwd=copy)
        killed, survived = _score(session)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    tested = killed + survived
    score = 100.0 if tested == 0 else 100.0 * killed / tested
    print(f"mutation score: {killed} killed of {tested} = {score:.1f}% (minimum {minimum:g}%)")
    return 0 if score >= minimum else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mutate_python.py", description=__doc__)
    parser.add_argument("--min", type=float, required=True, help="minimum kill percentage")
    parser.add_argument(
        "--scope",
        choices=["changed-lines", "all"],
        help="changed-lines: mutate only lines changed since --base-ref (default: whole files)",
    )
    parser.add_argument("--base-ref", help="the ref changed lines are measured from")
    parser.add_argument("files", nargs="*", help="changed files, repo-relative")
    args = parser.parse_args(argv)
    if args.scope == "changed-lines" and not args.base_ref:
        print("mutate_python: --scope changed-lines needs --base-ref", file=sys.stderr)
        return 2
    try:
        return run(Path.cwd(), args.files, args.min, scope=args.scope, base_ref=args.base_ref)
    except HelperError as exc:
        print(f"mutate_python: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
