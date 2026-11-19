"""Software Factory gate engine: one deterministic pass/fail verdict for a repository.

Usage (from anywhere inside the repo):
    python .factory/gates/gate.py [--json]

Exit codes: 0 every check passed, 1 at least one check failed, 2 a usage, config or profile
error stopped the gate before any check ran. Standard library only (ADR 0007).
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import fnmatch
import hashlib
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import tomllib
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
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
    "commit_checks": ["format", "lint", "types"],
    "python_command": ["python"],
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


def _check_names(value: object) -> str | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return "expected a list of strings"
    unknown = [item for item in value if item not in CHECK_ORDER]
    if unknown:
        return f"unknown check(s) {', '.join(unknown)}; valid: {', '.join(CHECK_ORDER)}"
    return None


def _command(value: object) -> str | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return "expected a list of strings"
    if not value:
        return "must not be empty"
    return None if all(item.strip() for item in value) else "must not contain empty items"


_RULES = {
    "coverage_threshold": _fraction,
    "mutation_threshold": _fraction,
    "mutation_scope": _scope,
    "profiles": _names,
    "base_ref": _ref,
    "commit_checks": _check_names,
    "python_command": _command,
}


@dataclass(frozen=True)
class Settings:
    coverage_threshold: float
    mutation_threshold: float
    mutation_scope: str
    profiles: list[str]
    base_ref: str
    commit_checks: list[str]
    python_command: list[str]

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
            commit_checks=[str(name) for name in values["commit_checks"]],  # type: ignore[attr-defined]
            python_command=[str(arg) for arg in values["python_command"]],  # type: ignore[attr-defined]
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


# --- placeholders and changed files -------------------------------------------------------------


class BaseRefError(Exception):
    """gates.base_ref does not resolve; only checks that need changed files fail (AC-15)."""


def _git_paths(root: Path, *args: str) -> list[str] | None:
    completed = subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)
    if completed.returncode != 0:
        return None
    return [p.decode("utf-8", errors="surrogateescape") for p in completed.stdout.split(b"\0") if p]


def changed_files(root: Path, base_ref: str) -> list[str]:
    """Files changed since merge-base(base_ref, HEAD): committed, staged, unstaged and untracked
    (not ignored), minus deletions. Sorted repo-relative posix paths (AC-13)."""
    merge_base = subprocess.run(
        ["git", "merge-base", base_ref, "HEAD"], cwd=root, capture_output=True, text=True
    )
    if merge_base.returncode != 0:
        raise BaseRefError(f"base ref '{base_ref}' not found (gates.base_ref or --base-ref)")
    base = merge_base.stdout.strip()
    diffed = _git_paths(root, "diff", "--name-only", "-z", "--diff-filter=d", base) or []
    untracked = _git_paths(root, "ls-files", "--others", "--exclude-standard", "-z") or []
    return sorted({p for p in (*diffed, *untracked) if (root / p).is_file()})


def tracked_files(root: Path) -> list[str]:
    return sorted(p for p in _git_paths(root, "ls-files", "-z") or [] if (root / p).is_file())


class FileSource:
    """Works out the files for {changed_files} once, only if a command asks for them."""

    def __init__(self, root: Path, settings: Settings) -> None:
        self.root = root
        self.settings = settings
        self.changed: list[str] | None = None
        self._candidates: list[str] | None = None

    def candidates(self) -> list[str]:
        if self._candidates is None:
            if self.settings.mutation_scope == "all":
                self._candidates = tracked_files(self.root)
            else:
                self.changed = changed_files(self.root, self.settings.base_ref)
                self._candidates = self.changed
        return self._candidates


def _matches(path: str, globs: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in globs)


def expand(command: list[str], values: dict[str, str], files: list[str]) -> list[str]:
    """Fill threshold placeholders in every argument; splice files in for {changed_files}."""
    expanded: list[str] = []
    for arg in command:
        if arg == CHANGED_FILES:
            expanded.extend(files)
            continue
        for placeholder, value in values.items():
            arg = arg.replace(placeholder, value)
        expanded.append(arg)
    return expanded


def run_profiles(
    root: Path,
    profiles: list[Profile],
    settings: Settings,
    files: FileSource,
    only: Collection[str] | None = None,
) -> list[Result]:
    """Run every profile's checks in order; with `only`, the rest are skipped (E07 AC-01)."""
    values = {
        "{coverage_percent}": str(round(settings.coverage_threshold * 100)),
        "{mutation_percent}": str(round(settings.mutation_threshold * 100)),
    }
    results: list[Result] = []
    for profile in profiles:
        for check in CHECK_ORDER:
            if only is not None and check not in only:
                results.append(Result(profile.name, check, "skipped", "not selected"))
                continue
            spec = profile.checks.get(check)
            if spec is None:
                results.append(Result(profile.name, check, "n/a", "not defined by the profile"))
                continue
            selected: list[str] = []
            if CHANGED_FILES in spec.command:
                try:
                    candidates = files.candidates()
                except BaseRefError as exc:
                    results.append(
                        Result(profile.name, check, "fail", str(exc), command=spec.command)
                    )
                    continue
                selected = [p for p in candidates if _matches(p, profile.mutation_paths)]
                if not selected:
                    results.append(Result(profile.name, check, "skipped", "no changed files"))
                    continue
            argv = expand(spec.command, values, selected)
            results.append(run_check(root, profile, CheckSpec(spec.name, argv, spec.timeout_s)))
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
        lines = [f"Gate: {self.root}", f"Base: {self.base_ref}"]
        width = max((len(name) for name in self.profiles), default=0)
        for r in self.results:
            took = f"{r.duration_s:.2f}s" if r.duration_s is not None else "-"
            row = f"  {r.profile:<{width}}  {r.check:<8}  {r.status:<7}  {took:>8}"
            shows_reason = r.status in ("fail", "skipped")
            lines.append(f"{row}  {r.reason}".rstrip() if shows_reason else row)
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


STATE_MODULE = Path(".factory") / "state" / "state.py"


def load_state_module(path: Path) -> ModuleType | None:
    """The E02 state module (ADR 0015), or None if this kit predates it."""
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("factory_state", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules["factory_state"] = module  # dataclasses look the module up by name
    spec.loader.exec_module(module)
    return module


def state_problems(root: Path) -> list[str]:
    """Problems in the repo's state files, as `<file>: <where>: <message>` (E02 AC-04)."""
    module = load_state_module(root / STATE_MODULE)
    return [] if module is None else [str(p) for p in module.validate(root)]


AGENTS_MODULE = Path(".factory") / "agents" / "agents.py"


def load_agents_module(path: Path) -> ModuleType | None:
    """The E03 agents module (ADR 0016), or None if this kit predates it."""
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("factory_agents", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules["factory_agents"] = module
    spec.loader.exec_module(module)
    return module


def agent_problems(root: Path) -> tuple[list[str], list[str]]:
    """(problems in agent files and lock records, broken locks) for E03 AC-04 and AC-10."""
    module = load_agents_module(root / AGENTS_MODULE)
    if module is None:
        return [], []
    problems = [str(p) for p in module.validate(root)]
    if problems:
        return problems, []
    return [], [str(line) for line in module.verify_locks(root)]


def parse_checks(text: str) -> list[str]:
    """`--checks a,b` -> ["a", "b"]; unknown names are a usage error (E07 AC-01)."""
    names = [name.strip() for name in text.split(",") if name.strip()]
    unknown = [name for name in names if name not in CHECK_ORDER]
    if unknown or not names:
        shown = ", ".join(unknown) if unknown else "(none)"
        raise GateError(f"--checks: unknown check(s) {shown}; valid: {', '.join(CHECK_ORDER)}")
    return names


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gate.py", description="Run the repository gate.")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument(
        "--checks", metavar="NAME[,NAME...]", help="run only these checks; skip the rest"
    )
    parser.add_argument(
        "--base-ref", metavar="REF", help="measure changed files from REF (overrides config)"
    )
    args = parser.parse_args(argv)
    try:
        only = parse_checks(args.checks) if args.checks is not None else None
        root = find_root(Path.cwd())
        settings = Settings.load(root)
        problems = state_problems(root)
        if problems:
            listed = "".join(f"\ngate: {problem}" for problem in problems)
            raise GateError(f"invalid state files (python .factory/state/state.py check):{listed}")
        problems, broken = agent_problems(root)
        if problems:
            listed = "".join(f"\ngate: {problem}" for problem in problems)
            raise GateError(
                f"invalid agent files or lock records (python {AGENTS_MODULE.as_posix()} check):"
                f"{listed}"
            )
        if broken:
            for line in broken:
                print(f"gate: {line}", file=sys.stderr)
            print("gate: FAIL: locked files changed; nothing was run (ADR 0018)", file=sys.stderr)
            return 1
        if args.base_ref is not None:
            if not args.base_ref.strip():
                raise GateError("--base-ref must not be empty")
            settings = dataclasses.replace(settings, base_ref=args.base_ref)
        selected = select_profiles(root, load_profiles(root), settings)
    except GateError as exc:
        print(f"gate: {exc}", file=sys.stderr)
        return 2
    files = FileSource(root, settings)
    results = run_profiles(root, selected, settings, files, only)
    names = [p.name for p in selected]
    report = Report(str(root), settings.base_ref, names, files.changed or [], results)
    print(report.to_json() if args.json else report.to_text())
    return 0 if report.verdict == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
