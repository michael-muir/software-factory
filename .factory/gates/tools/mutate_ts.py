"""Mutation-score helper for the TS/JS gate profile (E06, ADR 0010). Standard library only.

Usage:
    python .factory/gates/tools/mutate_ts.py --min PERCENT FILE...

Runs Stryker (Vitest runner) from the project's node_modules on the given non-test files,
with its config and JSON report in a temporary directory outside the repo, then compares the
mutation score to PERCENT.
Exit codes: 0 at or above PERCENT, or nothing to mutate; 1 below, or Stryker could not finish
(for example a red initial test run); 2 npx or Stryker is not installed.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

SOURCE_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
DETECTED = ("Killed", "Timeout")
UNDETECTED = ("Survived", "NoCoverage")
REQUIRED_PACKAGES = ("@stryker-mutator/core", "@stryker-mutator/vitest-runner")
OUTPUT_TAIL_LINES = 20


class HelperError(Exception):
    """A missing tool: exit 2."""


def _parts(path: str) -> tuple[str, ...]:
    return PurePosixPath(path.replace("\\", "/")).parts


def is_test_file(path: str) -> bool:
    parts = _parts(path)
    name = parts[-1]
    return ".test." in name or ".spec." in name or "__tests__" in parts[:-1]


def is_installed_kit(path: str) -> bool:
    return _parts(path)[0] == ".factory"


def is_tool_config(path: str) -> bool:
    """`<tool>.config.<ext>` files such as eslint.config.js or vitest.config.ts."""
    return ".config." in _parts(path)[-1]


def select_sources(paths: Sequence[str]) -> list[str]:
    """The given TS/JS files that are project code, in the order given (spec AC-06).

    Skipped: tests, the installed kit under .factory/, and tool configuration files.
    """
    return [
        p
        for p in paths
        if p.endswith(SOURCE_SUFFIXES)
        and not is_test_file(p)
        and not is_installed_kit(p)
        and not is_tool_config(p)
    ]


def stryker_config(sources: Sequence[str], report: Path) -> dict[str, Any]:
    return {
        "testRunner": "vitest",
        "mutate": list(sources),
        "reporters": ["json"],
        "jsonReporter": {"fileName": report.as_posix()},
        "coverageAnalysis": "perTest",
        "cleanTempDir": True,
        "logLevel": "warn",
    }


def score(report: Mapping[str, Any]) -> tuple[int, int]:
    """(detected, detected + undetected): Stryker's mutation score inputs."""
    statuses = [
        str(mutant.get("status"))
        for file in report.get("files", {}).values()
        for mutant in file.get("mutants", [])
    ]
    detected = sum(status in DETECTED for status in statuses)
    undetected = sum(status in UNDETECTED for status in statuses)
    return detected, detected + undetected


def _tail(text: str) -> str:
    return "\n".join(text.splitlines()[-OUTPUT_TAIL_LINES:])


def run(root: Path, files: Sequence[str], minimum: float) -> int:
    sources = select_sources(files)
    if not sources:
        print("no source files to mutate")
        return 0
    npx = shutil.which("npx")
    if npx is None:
        raise HelperError("npx (Node.js) is not on PATH")
    missing = [p for p in REQUIRED_PACKAGES if not (root / "node_modules" / p).is_dir()]
    if missing:
        raise HelperError(f"Stryker is not installed in node_modules: {', '.join(missing)}")

    workdir = Path(tempfile.mkdtemp(prefix="factory-mutate-"))
    try:
        config, report_path = workdir / "stryker.config.json", workdir / "mutation.json"
        config.write_text(json.dumps(stryker_config(sources, report_path)), encoding="utf-8")
        print(f"mutating {len(sources)} file(s) with Stryker")
        completed = subprocess.run(
            [npx, "--no-install", "stryker", "run", config.as_posix()],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0 or not report_path.is_file():
            print("stryker could not finish:")
            print(_tail(completed.stdout + completed.stderr))
            return 1
        detected, total = score(json.loads(report_path.read_text(encoding="utf-8")))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    value = 100.0 if total == 0 else 100.0 * detected / total
    print(f"mutation score: {detected} detected of {total} = {value:.1f}% (minimum {minimum:g}%)")
    return 0 if value >= minimum else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mutate_ts.py", description=__doc__)
    parser.add_argument("--min", type=float, required=True, help="minimum mutation score")
    parser.add_argument("files", nargs="*", help="changed files, repo-relative")
    args = parser.parse_args(argv)
    try:
        return run(Path.cwd(), args.files, args.min)
    except HelperError as exc:
        print(f"mutate_ts: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
