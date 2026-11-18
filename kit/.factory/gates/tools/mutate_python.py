"""Mutation-score helper for the Python gate profile (E06, ADR 0010). Standard library only.

Usage:
    python .factory/gates/tools/mutate_python.py --min PERCENT FILE...

Runs cosmic-ray on the given non-test files with the interpreter running this script, then
compares the share of killed mutants to PERCENT.
Exit codes: 0 at or above PERCENT, or nothing to mutate; 1 below; 2 a missing tool or bad
settings in [tool.software-factory.mutation].
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


def _score(session: Path) -> tuple[int, int]:
    with _db(session) as db:
        rows = db.execute("SELECT test_outcome FROM work_results").fetchall()
    outcomes = [str(row[0]).upper() for row in rows]
    return outcomes.count("KILLED"), outcomes.count("SURVIVED")


def run(root: Path, files: Sequence[str], minimum: float) -> int:
    settings = load_settings(root)
    sources = select_sources(files)
    if not sources:
        print("no source files to mutate")
        return 0
    _require("cosmic_ray", "cosmic-ray")
    _require("pytest", "pytest")

    workdir = Path(tempfile.mkdtemp(prefix="factory-mutate-"))
    try:
        config, session = workdir / "cosmic-ray.toml", workdir / "session.sqlite"
        _write_config(config, sources, test_command(sys.executable, settings.test_args))
        _cosmic_ray("init", str(config), str(session), cwd=root)

        keys = _stable_keys(session)
        total = len(keys)
        if total == 0:
            print(f"mutating {len(sources)} file(s): no mutants generated")
            return 0
        chosen = set(sample(list(keys.values()), content_seed(root, sources), settings.max_mutants))
        if len(chosen) < total:
            _keep_only(session, {job for job, key in keys.items() if key in chosen})
            print(f"sampled {len(chosen)} of {total} mutants")
        else:
            print(f"testing all {total} mutants")

        _cosmic_ray("exec", str(config), str(session), cwd=root)
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
    parser.add_argument("files", nargs="*", help="changed files, repo-relative")
    args = parser.parse_args(argv)
    try:
        return run(Path.cwd(), args.files, args.min)
    except HelperError as exc:
        print(f"mutate_python: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
