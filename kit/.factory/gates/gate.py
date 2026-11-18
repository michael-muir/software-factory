"""Software Factory gate engine: one deterministic pass/fail verdict for a repository.

Usage (from anywhere inside the repo):
    python .factory/gates/gate.py [--json]

Exit codes: 0 every check passed, 1 at least one check failed, 2 a usage, config or profile
error stopped the gate before any check ran. Standard library only (ADR 0007).
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CHECK_ORDER = ("format", "lint", "types", "build", "tests", "coverage", "mutation")
PROFILES_DIR = Path(".factory") / "gates" / "profiles"
CONFIG_PATH = Path(".agentic") / "config.toml"
CHANGED_FILES = "{changed_files}"
DEFAULT_TIMEOUT_S = 600
OUTPUT_TAIL_LINES = 40

# Mirrors factory_installer.config_schema's gates.* defaults; a test keeps them equal (ADR 0007).
DEFAULTS: dict[str, object] = {
    "coverage_threshold": 0.8,
    "mutation_threshold": 0.6,
    "mutation_scope": "changed-lines",
    "profiles": [],
    "base_ref": "main",
}


class GateError(Exception):
    """A usage, config or profile problem: exit 2 before any check runs."""


# --- settings -----------------------------------------------------------------------------------


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _fraction(value: object) -> str | None:
    if not _is_number(value):
        return "expected a number"
    return None if 0 <= float(value) <= 1 else "must be between 0 and 1"  # type: ignore[arg-type]


def _scope(value: object) -> str | None:
    if value in ("changed-lines", "all"):
        return None
    return 'must be "changed-lines" or "all"'


def _names(value: object) -> str | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return "expected a list of strings"
    return None if all(item.strip() for item in value) else "must not contain empty names"


def _ref(value: object) -> str | None:
    if not isinstance(value, str):
        return "expected a string"
    return None if value.strip() else "must not be empty"


_RULES = {
    "coverage_threshold": _fraction,
    "mutation_threshold": _fraction,
    "mutation_scope": _scope,
    "profiles": _names,
    "base_ref": _ref,
}


@dataclass(frozen=True)
class Settings:
    coverage_threshold: float
    mutation_threshold: float
    mutation_scope: str
    profiles: list[str]
    base_ref: str

    @classmethod
    def load(cls, root: Path) -> Settings:
        """Read gates.* from .agentic/config.toml; missing keys take the defaults."""
        values = dict(DEFAULTS)
        path = root / CONFIG_PATH
        if path.is_file():
            try:
                with path.open("rb") as f:
                    data = tomllib.load(f)
            except tomllib.TOMLDecodeError as exc:
                raise GateError(f"{CONFIG_PATH.as_posix()}: invalid TOML: {exc}") from exc
            gates = data.get("gates", {})
            if not isinstance(gates, dict):
                raise GateError(f"{CONFIG_PATH.as_posix()}: gates: expected a table")
            for key, rule in _RULES.items():
                if key in gates:
                    problem = rule(gates[key])
                    if problem:
                        raise GateError(f"{CONFIG_PATH.as_posix()}: gates.{key}: {problem}")
                    values[key] = gates[key]
        return cls(
            coverage_threshold=float(values["coverage_threshold"]),  # type: ignore[arg-type]
            mutation_threshold=float(values["mutation_threshold"]),  # type: ignore[arg-type]
            mutation_scope=str(values["mutation_scope"]),
            profiles=[str(name) for name in values["profiles"]],  # type: ignore[attr-defined]
            base_ref=str(values["base_ref"]),
        )


# --- profiles -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckSpec:
    name: str
    command: list[str]
    timeout_s: int


@dataclass(frozen=True)
class Profile:
    name: str
    detect: list[str]
    mutation_paths: list[str]
    checks: dict[str, CheckSpec]
    source: str


def _string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _parse_check(where: str, name: str, table: object) -> CheckSpec:
    if name not in CHECK_ORDER:
        raise GateError(f"{where}: unknown check '{name}' (valid: {', '.join(CHECK_ORDER)})")
    if not isinstance(table, dict):
        raise GateError(f"{where}: checks.{name}: expected a table")
    command = table.get("command")
    if not _string_list(command) or not command:
        raise GateError(f"{where}: checks.{name}: command must be a non-empty list of strings")
    for arg in command:
        if CHANGED_FILES in arg and arg != CHANGED_FILES:
            raise GateError(
                f"{where}: checks.{name}: {CHANGED_FILES} must be a whole argument, got {arg!r}"
            )
    timeout = table.get("timeout_s", DEFAULT_TIMEOUT_S)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
        raise GateError(f"{where}: checks.{name}: timeout_s must be a positive integer")
    return CheckSpec(name, list(command), timeout)


def parse_profile(path: Path, display: str) -> Profile:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise GateError(f"{display}: invalid TOML: {exc}") from exc
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise GateError(f"{display}: missing name (a non-empty string)")
    detect = data.get("detect", [])
    mutation_paths = data.get("mutation_paths", [])
    for key, value in (("detect", detect), ("mutation_paths", mutation_paths)):
        if not _string_list(value):
            raise GateError(f"{display}: {key} must be a list of strings")
    checks_table = data.get("checks", {})
    if not isinstance(checks_table, dict):
        raise GateError(f"{display}: checks must be a table")
    checks = {name_: _parse_check(display, name_, t) for name_, t in checks_table.items()}
    return Profile(name, list(detect), list(mutation_paths), checks, display)


def load_profiles(root: Path) -> dict[str, Profile]:
    """Parse every profile; any malformed one is an error even if it would not be selected."""
    profiles: dict[str, Profile] = {}
    directory = root / PROFILES_DIR
    for path in sorted(directory.glob("*.toml")) if directory.is_dir() else []:
        display = (PROFILES_DIR / path.name).as_posix()
        loaded = parse_profile(path, display)
        if loaded.name in profiles:
            raise GateError(f"{display}: duplicate profile name '{loaded.name}'")
        profiles[loaded.name] = loaded
    return profiles


def select_profiles(root: Path, profiles: dict[str, Profile], settings: Settings) -> list[Profile]:
    available = ", ".join(sorted(profiles)) or "none"
    if settings.profiles:
        unknown = [name for name in settings.profiles if name not in profiles]
        if unknown:
            raise GateError(
                f"gates.profiles names unknown profile(s) {', '.join(unknown)}; "
                f"available: {available}"
            )
        return [profiles[name] for name in settings.profiles]
    detected = [
        profiles[name]
        for name in sorted(profiles)
        if any((root / marker).exists() for marker in profiles[name].detect)
    ]
    if not detected:
        raise GateError(f"no profile applies to this repo; available: {available}")
    return detected


# --- running ------------------------------------------------------------------------------------


@dataclass
class Result:
    profile: str
    check: str
    status: str  # "pass" | "fail" | "skipped" | "n/a"
    reason: str = ""
    exit_code: int | None = None
    duration_s: float | None = None
    command: list[str] | None = None
    output_tail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "check": self.check,
            "status": self.status,
            "reason": self.reason,
            "exit_code": self.exit_code,
            "duration_s": self.duration_s,
            "command": self.command,
            "output_tail": self.output_tail,
        }


def _tail(output: bytes) -> str:
    lines = output.decode("utf-8", errors="replace").splitlines()
    return "\n".join(lines[-OUTPUT_TAIL_LINES:])


def snapshot(root: Path) -> dict[str, str]:
    """Status code and content hash of every changed or untracked, non-ignored file (ADR 0008).

    Comparing two snapshots names exactly the paths a check touched: new or changed status
    entries, and content changes to files that were already modified or untracked.
    """
    raw = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
        check=False,
    ).stdout
    entries = raw.split(b"\0")
    state: dict[str, str] = {}
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        code = entry[:2].decode("ascii", errors="replace")
        rel = entry[3:].decode("utf-8", errors="surrogateescape")
        if code[0] in "RC":
            index += 1  # the next entry is the rename/copy source
        path = root / rel
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "-"
        state[rel] = f"{code}:{digest}"
    return state


def _changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))


def _kill_tree(process: subprocess.Popen[bytes]) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True, check=False
        )
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    with contextlib.suppress(OSError):
        process.kill()


def _execute(argv: list[str], root: Path, timeout_s: int) -> tuple[int | None, bytes, bool]:
    """Run argv from root without a shell; on timeout kill the whole process tree."""
    if sys.platform == "win32":
        process = subprocess.Popen(
            argv,
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    else:
        process = subprocess.Popen(
            argv,
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    try:
        output, _ = process.communicate(timeout=timeout_s)
        return process.returncode, output, False
    except subprocess.TimeoutExpired:
        _kill_tree(process)
        try:
            output, _ = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            output = b""
        return None, output, True


def run_check(root: Path, profile: Profile, spec: CheckSpec) -> Result:
    result = Result(profile.name, spec.name, "fail", command=list(spec.command))
    program = shutil.which(spec.command[0], path=os.environ.get("PATH"))
    if program is None:
        result.reason = f"command not found: {spec.command[0]}"
        return result
    argv = [program, *spec.command[1:]]
    result.command = argv

    before = snapshot(root)
    started = time.monotonic()
    exit_code, output, timed_out = _execute(argv, root, spec.timeout_s)
    result.duration_s = round(time.monotonic() - started, 3)
    result.exit_code = exit_code
    result.output_tail = _tail(output)
    touched = _changed(before, snapshot(root))

    reasons: list[str] = []
    if touched:
        reasons.append("modified the repository: " + ", ".join(touched))
    if timed_out:
        reasons.append(f"timed out after {spec.timeout_s}s")
    elif exit_code != 0:
        reasons.append(f"exited with code {exit_code}")
    result.status = "fail" if reasons else "pass"
    result.reason = "; ".join(reasons)
    return result


def run_profiles(root: Path, profiles: list[Profile]) -> list[Result]:
    results: list[Result] = []
    for profile in profiles:
        for check in CHECK_ORDER:
            spec = profile.checks.get(check)
            if spec is None:
                results.append(Result(profile.name, check, "n/a", "not defined by the profile"))
            else:
                results.append(run_check(root, profile, spec))
    return results


# --- report -------------------------------------------------------------------------------------


@dataclass
class Report:
    root: str
    base_ref: str
    profiles: list[str]
    changed_files: list[str]
    results: list[Result]

    @property
    def verdict(self) -> str:
        return "fail" if any(r.status == "fail" for r in self.results) else "pass"

    def to_json(self) -> str:
        data = {
            "verdict": self.verdict,
            "root": self.root,
            "base_ref": self.base_ref,
            "profiles": self.profiles,
            "changed_files": self.changed_files,
            "checks": [r.to_dict() for r in self.results],
        }
        return json.dumps(data, indent=2)

    def to_text(self) -> str:
        lines = [f"Gate: {self.root}"]
        width = max((len(name) for name in self.profiles), default=0)
        for r in self.results:
            took = f"{r.duration_s:.2f}s" if r.duration_s is not None else "-"
            row = f"  {r.profile:<{width}}  {r.check:<8}  {r.status:<7}  {took:>8}"
            lines.append(f"{row}  {r.reason}".rstrip() if r.status == "fail" else row)
            if r.status == "fail" and r.output_tail:
                lines += [f"      | {line}" for line in r.output_tail.splitlines()]
        lines.append(self.verdict.upper())
        return "\n".join(lines)


# --- entry point --------------------------------------------------------------------------------


def find_root(start: Path) -> Path:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GateError("git is not installed or not on PATH") from exc
    if completed.returncode != 0:
        raise GateError(f"{start}: not inside a git working tree")
    return Path(completed.stdout.strip())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gate.py", description="Run the repository gate.")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    try:
        root = find_root(Path.cwd())
        settings = Settings.load(root)
        selected = select_profiles(root, load_profiles(root), settings)
    except GateError as exc:
        print(f"gate: {exc}", file=sys.stderr)
        return 2
    results = run_profiles(root, selected)
    report = Report(str(root), settings.base_ref, [p.name for p in selected], [], results)
    print(report.to_json() if args.json else report.to_text())
    return 0 if report.verdict == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
