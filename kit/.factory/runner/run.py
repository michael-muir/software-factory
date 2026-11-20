#!/usr/bin/env python3
"""Software Factory runner (E16): a file queue of jobs, each run in its own git worktree.

Standard library only (PRD). Every file the runner keeps is under `<git-common-dir>/factory/`,
and each change to it is one atomic file operation (ADR 0030):

    queue/<id>.toml              a request waiting for a daemon
    jobs/<id>/                   reserves the id; holds everything else about the job
    jobs/<id>/request.toml       the request, once a daemon has claimed it
    jobs/<id>/job.toml           the record, written only by the job's claimer
    jobs/<id>/commands/0001.toml commands added with `send`
    jobs/<id>/logs/0001.log      output of command 1
    jobs/<id>/closed             no more commands will come
    jobs/<id>/cancel             `cancel` asks the job's daemon to halt it
    jobs/<id>/handoff.md         the body of the handoff a halt writes in the worktree
    claims/<sha256 of path>      a worktree claim, holding the job id
    rejected/<name>              a hand-dropped file whose name isn't a job id, and its record
    stop                         when `stop` was run: daemons started before then stop

Usage:
    run.py --daemon
    run.py submit [--id ID] [--base REF] [--task TASK] [--open] [-- argv ...]
    run.py send <job> -- argv ...
    run.py close <job>
    run.py cancel <job>
    run.py status <job> [--json]
    run.py stop
    run.py _host -- argv ...     (Windows, internal: runs one command inside a Job Object)

Exit codes: 0 done, 1 refused, 2 bad input (arguments, config, unknown job, no git repo).
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

JOB_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,39}", re.ASCII)
TASK_ID = re.compile(r"[A-Za-z0-9._-]+", re.ASCII)  # mirrors state.TASK_ID (E02)
FINISHED = ("succeeded", "failed", "halted")
REQUEST_VERSION = 1
CONFIG_REL = Path(".agentic") / "config.toml"
POLL_SECONDS = 0.2  # one daemon pass; the spec allows 2 seconds for a pickup (ADR 0032)
KILL_WAIT_S = 10.0  # AC-17: a killed tree is gone within 10 seconds
HALT_STOPPED = "daemon stopped"
HALT_CANCELLED = "cancelled"


class BadInput(Exception):
    """Bad arguments, config or job id: exit 2."""


class Refused(Exception):
    """A valid request the job's state doesn't allow: exit 1."""


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


# --- config (mirrors factory_installer/config_schema.py for the keys the runner reads) ---------

Check = Callable[[Any], str | None]


def _between(low: float, high: float, *, low_open: bool = False) -> Check:
    def check(value: Any) -> str | None:
        ok_low = value > low if low_open else value >= low
        if ok_low and value <= high:
            return None
        left = "greater than" if low_open else "at least"
        return f"must be {left} {low:g} and at most {high:g}"

    return check


def _positive(value: Any) -> str | None:
    return None if value > 0 else "must be greater than 0"


def _not_empty(value: Any) -> str | None:
    return None if value.strip() else "must not be empty"


# key: (kind, default, check). Kinds: "int", "number", "str".
RULES: dict[str, tuple[str, object, Check | None]] = {
    "runner.max_turns": ("int", 50, _between(1, 10000)),
    "runner.job_timeout_minutes": ("number", 120, _positive),
    "runner.max_parallel": ("int", 2, _between(1, 64)),
    "runner.worktree_root": ("str", "", None),
    "budgets.per_job_usd": ("number", 15, _positive),
    "budgets.per_day_usd": ("number", 120, _positive),
    "budgets.warn_at": ("number", 0.8, _positive),
    "budgets.halt_at": ("number", 1.0, _between(0, 1, low_open=True)),
    "gates.base_ref": ("str", "main", _not_empty),
}
WHOLE_SECTIONS = ("runner", "budgets")  # sections whose unknown keys are errors here too
PAIRS = (("budgets.per_job_usd", "budgets.per_day_usd"), ("budgets.warn_at", "budgets.halt_at"))
_KINDS = {"int": "an integer", "number": "a number", "str": "a string"}


@dataclass(frozen=True)
class Config:
    max_turns: int
    job_timeout_minutes: float
    max_parallel: int
    worktree_root: str
    per_job_usd: float
    per_day_usd: float
    warn_at: float
    halt_at: float
    base_ref: str


def _kind_ok(kind: str, value: object) -> bool:
    if isinstance(value, bool):
        return False
    if kind == "int":
        return isinstance(value, int)
    if kind == "number":
        return isinstance(value, int | float)
    return isinstance(value, str)


def config_problems(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The effective values of RULES, and one problem per bad key ("<key>: <reason>")."""
    values: dict[str, Any] = {key: rule[1] for key, rule in RULES.items()}
    problems: list[str] = []
    bad: set[str] = set()
    for section in {key.split(".")[0] for key in RULES}:
        table = data.get(section)
        if table is None:
            continue
        if not isinstance(table, dict):
            problems.append(f"{section}: expected a table")
            bad.update(key for key in RULES if key.startswith(section + "."))
            continue
        for sub, value in table.items():
            key = f"{section}.{sub}"
            if key not in RULES:
                if section in WHOLE_SECTIONS:
                    problems.append(f"{key}: unknown key")
                continue
            kind, _, check = RULES[key]
            reason = None if _kind_ok(kind, value) else f"expected {_KINDS[kind]}"
            if reason is None and check is not None:
                reason = check(value)
            if reason is None:
                values[key] = value
            else:
                problems.append(f"{key}: {reason}")
                bad.add(key)
    for low, high in PAIRS:
        if low not in bad and high not in bad and values[low] > values[high]:
            problems.append(f"{low}: must be at most {high} ({values[high]:g})")
    return values, problems


def load_config(main: Path) -> Config:
    path = main / CONFIG_REL
    data: dict[str, Any] = {}
    if path.is_file():
        try:
            with path.open("rb") as f:
                data = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise BadInput(f"{CONFIG_REL.as_posix()}: {exc}") from exc
    values, problems = config_problems(data)
    if problems:
        raise BadInput("; ".join(f"{CONFIG_REL.as_posix()}: {p}" for p in problems))
    return Config(
        max_turns=values["runner.max_turns"],
        job_timeout_minutes=values["runner.job_timeout_minutes"],
        max_parallel=values["runner.max_parallel"],
        worktree_root=values["runner.worktree_root"],
        per_job_usd=values["budgets.per_job_usd"],
        per_day_usd=values["budgets.per_day_usd"],
        warn_at=values["budgets.warn_at"],
        halt_at=values["budgets.halt_at"],
        base_ref=values["gates.base_ref"],
    )


# --- the repo and its store (ADR 0030) ---------------------------------------------------------


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise BadInput(f"cannot run git: {exc}") from exc


@dataclass(frozen=True)
class Repo:
    main: Path  # the main worktree's root
    store: Path  # <git-common-dir>/factory

    @property
    def queue(self) -> Path:
        return self.store / "queue"

    def job(self, job_id: str) -> Path:
        return self.store / "jobs" / job_id


def find_repo(cwd: Path) -> Repo:
    common = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if common.returncode != 0:
        raise BadInput(f"{cwd} is not inside a git repository")
    if _git(cwd, "rev-parse", "--verify", "-q", "HEAD^{commit}").returncode != 0:
        raise BadInput("the git repository has no commit yet")
    listing = _git(cwd, "worktree", "list", "--porcelain")
    first = next((ln for ln in listing.stdout.splitlines() if ln.startswith("worktree ")), "")
    if listing.returncode != 0 or not first:
        raise BadInput("cannot find the repository's main worktree")
    main = Path(first[len("worktree ") :])
    return Repo(main=main, store=Path(common.stdout.strip()) / "factory")


def worktree_path(repo: Repo, config: Config, job_id: str) -> Path:
    root = config.worktree_root
    base = repo.main / root if root else repo.main.parent / f"{repo.main.name}.worktrees"
    return Path(os.path.normpath(base / job_id))


# --- TOML (written here because the standard library only reads it) ---------------------------


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    raise TypeError(f"cannot write {type(value).__name__} as TOML")


def _is_tables(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(v, dict) for v in value)


def dumps(data: dict[str, Any]) -> str:
    """Flat TOML: scalars and arrays first, then arrays of tables. None values are left out."""
    lines = [
        f"{key} = {_toml_value(value)}"
        for key, value in data.items()
        if value is not None and not _is_tables(value)
    ]
    for key, value in data.items():
        if _is_tables(value):
            for table in value:
                lines += ["", f"[[{key}]]"]
                lines += [f"{k} = {_toml_value(v)}" for k, v in table.items() if v is not None]
    return "\n".join(lines) + "\n"


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        try:
            return tomllib.load(f)
        except tomllib.TOMLDecodeError as exc:
            raise BadInput(f"{path}: {exc}") from exc


def _temp(folder: Path, text: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f".tmp-{secrets.token_hex(8)}"
    with open(tmp, "x", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return tmp


def _publish(tmp: Path, final: Path) -> bool:
    """Move tmp to final in one step, unless final exists (then False, and tmp is removed)."""
    try:
        if sys.platform == "win32":
            os.rename(tmp, final)  # fails if final exists
        else:
            os.link(tmp, final)  # fails if final exists; rename would overwrite
            tmp.unlink()
        return True
    except FileExistsError:
        tmp.unlink()
        return False


# --- jobs -----------------------------------------------------------------------------------


def _check_job_id(job_id: str) -> None:
    if not JOB_ID.fullmatch(job_id):
        raise BadInput(f"job id {job_id!r} must match {JOB_ID.pattern}")


def find_request(repo: Repo, job_id: str) -> dict[str, Any]:
    """The job's request, whether it's still queued or already claimed."""
    if JOB_ID.fullmatch(job_id):
        places = (repo.queue / f"{job_id}.toml", repo.job(job_id) / "request.toml")
        for _ in range(3):  # a claim moves the file between the two places
            for path in places:
                try:
                    return _read_toml(path)
                except FileNotFoundError:
                    continue
    raise BadInput(f"unknown job {job_id}")


def read_record(repo: Repo, job_id: str) -> dict[str, Any] | None:
    try:
        return _read_toml(repo.job(job_id) / "job.toml")
    except FileNotFoundError:
        return None


def sent_commands(repo: Repo, job_id: str) -> list[list[str]]:
    folder = repo.job(job_id) / "commands"
    if not folder.is_dir():
        return []
    names = sorted(p.name for p in folder.iterdir() if re.fullmatch(r"\d{4,}\.toml", p.name))
    return [list(_read_toml(folder / name)["argv"]) for name in names]


def is_closed(repo: Repo, job_id: str, request: dict[str, Any]) -> bool:
    return not request["open"] or (repo.job(job_id) / "closed").exists()


def job_status(repo: Repo, config: Config, job_id: str) -> dict[str, Any]:
    """The job record: what the request and markers say, overlaid with the daemon's record."""
    request = find_request(repo, job_id)
    logs = repo.job(job_id) / "logs"
    argvs = [list(c) for c in request["commands"]] + sent_commands(repo, job_id)
    commands: list[dict[str, Any]] = [
        {
            "argv": argv,
            "exit_code": None,
            "started": None,
            "duration_s": None,
            "log": str(logs / f"{n:04d}.log"),
        }
        for n, argv in enumerate(argvs, start=1)
    ]
    data: dict[str, Any] = {
        "id": job_id,
        "status": "queued",
        "reason": "",
        "base": request["base"],
        "branch": f"factory/{job_id}",
        "worktree": str(worktree_path(repo, config, job_id)),
        "task": request["task"],
        "open": request["open"],
        "closed": is_closed(repo, job_id, request),
        "created": request["submitted"],
        "started": None,
        "finished": None,
        "turns": 0,
        "usd": 0.0,
        "warnings": [],
        "commands": commands,
    }
    record = read_record(repo, job_id) or {}
    for n, ran in enumerate(record.pop("commands", [])):
        if n < len(commands):
            commands[n].update(ran)
    data.update(record)
    return data


def _refuse_if_finished(repo: Repo, job_id: str) -> None:
    record = read_record(repo, job_id)
    if record is not None and record.get("status") in FINISHED:
        raise Refused(f"job {job_id} has finished ({record['status']})")


# --- the daemon (ADR 0032) --------------------------------------------------------------------


class Proc(Protocol):
    """A running command: subprocess.Popen, or a test's stand-in."""

    def poll(self) -> int | None: ...

    def kill(self) -> None: ...


Starter = Callable[[list[str], Path, Mapping[str, str], Path], Proc]


class _NotStarted:
    """A command that could not start: it has already exited with 127."""

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def poll(self) -> int | None:
        return 127

    def kill(self) -> None:
        return None


# --- process trees (ADR 0031) -----------------------------------------------------------------

# Win32 values, from the Windows SDK's winnt.h.
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9  # the information class
PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100
NO_JOB_OBJECT = (
    "no Job Object ({}): a halt falls back to taskkill /T /F, "
    "and an orphaned grandchild may survive it"
)


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in ("Read", "Write", "Other", "ReadBytes", "WriteBytes", "OtherBytes")
    ]


class _ExtendedLimits(ctypes.Structure):
    """JOBOBJECT_EXTENDED_LIMIT_INFORMATION."""

    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _kernel32() -> Any:
    """kernel32 with every call the runner makes declared, so 64-bit handles aren't cut short."""
    if sys.platform != "win32":
        raise OSError("Job Objects exist only on Windows")
    from ctypes import wintypes

    lib = ctypes.WinDLL("kernel32", use_last_error=True)
    handle, dword, boolean = wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL
    for name, restype, argtypes in (
        ("CreateJobObjectW", handle, [ctypes.c_void_p, wintypes.LPCWSTR]),
        ("SetInformationJobObject", boolean, [handle, ctypes.c_int, ctypes.c_void_p, dword]),
        ("OpenProcess", handle, [dword, boolean, dword]),
        ("AssignProcessToJobObject", boolean, [handle, handle]),
        ("TerminateJobObject", boolean, [handle, ctypes.c_uint]),
        ("CloseHandle", boolean, [handle]),
    ):
        function = getattr(lib, name)
        function.restype = restype
        function.argtypes = argtypes
    return lib


class JobObject:
    """A Windows Job Object holding one process and everything it starts (ADR 0031).

    It kills them all when it's terminated or its last handle closes, and no child may break
    away. `kernel32` is the library to call: the real one unless a test passes a stand-in.
    """

    def __init__(self, pid: int, kernel32: Any = None) -> None:
        self._kernel32 = _kernel32() if kernel32 is None else kernel32
        self._handle: Any = self._call("CreateJobObjectW", None, None)
        try:
            info = _ExtendedLimits()
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            self._call(
                "SetInformationJobObject",
                self._handle,
                JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
            process = self._call("OpenProcess", PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
            try:
                self._call("AssignProcessToJobObject", self._handle, process)
            finally:
                self._kernel32.CloseHandle(process)
        except OSError:
            self.close()
            raise

    def _call(self, name: str, *args: Any) -> Any:
        result = getattr(self._kernel32, name)(*args)
        if not result:
            error = getattr(ctypes, "get_last_error", lambda: 0)()
            raise OSError(f"{name} failed (Windows error {error})")
        return result

    def terminate(self) -> None:
        self._call("TerminateJobObject", self._handle, 1)

    def close(self) -> None:
        """Close the job. KILL_ON_JOB_CLOSE ends anything still inside it."""
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


class Tree:
    """A running command and every process it starts (ADR 0031).

    POSIX: the command leads a new session, and a kill sends SIGKILL to its process group, which
    orphaned grandchildren keep. Windows: the command runs under `run.py _host` inside a Job
    Object, and a kill terminates the job; without one, `taskkill /T /F` is the fallback, and
    `warnings` says so.
    """

    def __init__(
        self,
        process: subprocess.Popen[bytes],
        job: JobObject | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        self.process = process
        self.job = job
        self.warnings = warnings or []

    def poll(self) -> int | None:
        code = self.process.poll()
        if code is not None and self.job is not None:
            self.job.close()  # the command is done: nothing it left behind outlives it
            self.job = None
        return code

    def kill(self) -> None:
        """Kill the whole tree, and wait up to KILL_WAIT_S for the command to go."""
        if sys.platform == "win32":
            self._kill_windows()
        else:
            with contextlib.suppress(ProcessLookupError, PermissionError):  # already gone
                os.killpg(self.process.pid, signal.SIGKILL)  # the session's group: pgid == pid
        with contextlib.suppress(subprocess.TimeoutExpired):
            self.process.wait(timeout=KILL_WAIT_S)

    def _kill_windows(self) -> None:
        if self.job is not None:
            try:
                self.job.terminate()
                return
            except OSError as exc:
                self.warnings.append(NO_JOB_OBJECT.format(exc))
            finally:
                self.job.close()
                self.job = None
        if self.process.poll() is None:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(self.process.pid)],
                capture_output=True,
                check=False,
            )


def _start_host(command: list[str], cwd: Path, env: Mapping[str, str], out: Any) -> Tree:
    """Windows: the host waits for a line on stdin, so the command is born inside the job."""
    host = subprocess.Popen(
        [sys.executable, "-I", "-S", str(Path(__file__).resolve()), "_host", "--", *command],
        cwd=cwd,
        env=dict(env),
        stdin=subprocess.PIPE,
        stdout=out,
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    warnings: list[str] = []
    job: JobObject | None = None
    try:
        job = JobObject(host.pid)
    except OSError as exc:
        warnings.append(NO_JOB_OBJECT.format(exc))
    try:
        assert host.stdin is not None
        host.stdin.write(b"go\n")
        host.stdin.close()
    except OSError:
        pass  # the host has already gone: poll() reports its exit
    return Tree(host, job, warnings)


def start_command(argv: list[str], cwd: Path, env: Mapping[str, str], log: Path) -> Proc:
    """Start argv without a shell in cwd, as a Tree, its stdout and stderr going to log."""
    program = shutil.which(argv[0], path=env.get("PATH")) or argv[0]
    command = [program, *argv[1:]]
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "wb") as out:
        try:
            if sys.platform == "win32":
                return _start_host(command, cwd, env, out)
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=dict(env),
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as exc:
            out.write(f"run.py: cannot start {argv[0]}: {exc}\n".encode())
            return _NotStarted()
        return Tree(process)


def claim_key(path: Path) -> str:
    """ADR 0030: the SHA-256 of the case-folded, resolved absolute path."""
    return hashlib.sha256(os.path.realpath(path).casefold().encode("utf-8")).hexdigest()


def request_problems(data: dict[str, Any], stem: str) -> list[str]:
    """What is wrong with a request read from queue/<stem>.toml (empty when it's sound)."""
    found: list[str] = []
    job_id = data.get("id")
    if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
        found.append(f"id must match {JOB_ID.pattern}")
    elif job_id != stem:
        found.append(f"id {job_id!r} doesn't match the file name {stem!r}")
    base = data.get("base")
    if not isinstance(base, str) or not base.strip():
        found.append("base must be a git ref")
    task = data.get("task")
    if not isinstance(task, str) or not TASK_ID.fullmatch(task):
        found.append("task must be a task id")
    is_open = data.get("open")
    if not isinstance(is_open, bool):
        found.append("open must be true or false")
    commands = data.get("commands")
    sound = isinstance(commands, list) and all(
        isinstance(c, list) and c and all(isinstance(w, str) for w in c) for c in commands
    )
    if not sound:
        found.append("commands must be a list of non-empty argv lists")
    elif is_open is False and len(commands) != 1:  # type: ignore[arg-type]
        found.append("a job without open needs exactly one command")
    if not isinstance(data.get("submitted"), dt.datetime):
        found.append("submitted must be a date and time")
    if data.get("version") != REQUEST_VERSION:
        found.append(f"version must be {REQUEST_VERSION}")
    return found


def _write_atomic(path: Path, text: str) -> None:
    """Replace path whole. On Windows a reader holding the file open makes replace fail: retry."""
    tmp = _temp(path.parent, text)
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 19:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(0.05)


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    return lines[-1] if lines else "no output"


def _aware(value: object) -> dt.datetime | None:
    if not isinstance(value, dt.datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)


@dataclass
class _Job:
    id: str
    request: dict[str, Any]
    record: dict[str, Any]
    worktree: Path
    claim: Path
    proc: Proc | None = None


class Daemon:
    """One polling loop: claims requests, makes worktrees, runs commands, ends jobs."""

    def __init__(
        self, repo: Repo, config: Config, *, start: Starter = start_command, name: str = ""
    ) -> None:
        self.repo = repo
        self.config = config
        self.start = start
        self.name = name or f"{socket.gethostname()}:{os.getpid()}:{secrets.token_hex(3)}"
        self.running: dict[str, _Job] = {}
        self.started = _now()  # a `stop` written after this stops the daemon

    # -- the loop

    def run(self) -> int:
        """Tick until `stop` or Ctrl+C, then halt every running job (AC-07); queued ones wait."""
        try:
            while not self.stop_requested():
                self.tick(_now())
                time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            pass
        self.halt_all(_now(), HALT_STOPPED)
        return 0

    def stop_requested(self) -> bool:
        try:
            text = (self.repo.store / "stop").read_text(encoding="utf-8").strip()
            when = _aware(dt.datetime.fromisoformat(text))
        except (OSError, ValueError):
            return False
        return when is not None and when > self.started

    def halt_all(self, now: dt.datetime, reason: str) -> None:
        for job in list(self.running.values()):
            try:
                self.halt(job, now, reason)
            except Exception as exc:  # one broken halt must not stop the others
                job.record.update(status="halted", reason=reason, finished=now)
                job.record["warnings"].append(f"halt: {exc}")
                self._save(job.id, job.record)

    def tick(self, now: dt.datetime) -> None:
        self._claim_new(now)
        for job in list(self.running.values()):
            try:
                self._advance(job, now)
            except Exception as exc:  # one broken job must not stop the others
                self.running.pop(job.id, None)
                job.record.update(status="failed", reason=f"runner error: {exc}", finished=now)
                self._save(job.id, job.record)

    # -- claiming

    def _queued(self) -> list[tuple[dt.datetime, str, Path, dict[str, Any] | None]]:
        queue = self.repo.queue
        if not queue.is_dir():
            return []
        found = []
        for path in queue.iterdir():
            if path.suffix != ".toml" or path.name.startswith("."):
                continue
            try:
                data: dict[str, Any] | None = _read_toml(path)
            except (BadInput, OSError):
                data = None
            try:
                mtime = dt.datetime.fromtimestamp(path.stat().st_mtime, dt.UTC)
            except OSError:
                continue  # claimed meanwhile
            when = _aware(data.get("submitted")) if data is not None else None
            found.append((when or mtime, path.name, path, data))
        return sorted(found, key=lambda item: (item[0], item[1]))

    def _claim_new(self, now: dt.datetime) -> None:
        for _, _, path, data in self._queued():
            stem = path.stem
            if not JOB_ID.fullmatch(stem):
                self._reject(path, now, f"the file name {path.name!r} isn't a job id")
                continue
            problems = ["the request is not valid TOML"] if data is None else []
            problems = problems or request_problems(data or {}, stem)
            if not problems and len(self.running) >= self.config.max_parallel:
                continue
            target = self.repo.job(stem) / "request.toml"
            if target.exists():
                self._reject(path, now, f"job {stem} already has a request")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.rename(path, target)  # the claim: only one daemon's rename succeeds
            except FileNotFoundError:
                continue
            if problems:
                self._save(stem, self._failed(stem, data or {}, now, "; ".join(problems)))
            else:
                self._begin(stem, _read_toml(target), now)

    def _reject(self, path: Path, now: dt.datetime, reason: str) -> None:
        folder = self.repo.store / "rejected"
        folder.mkdir(parents=True, exist_ok=True)
        target, number = folder / path.name, 1
        while target.exists() or Path(f"{target}.job.toml").exists():
            number += 1
            target = folder / f"{path.name}.{number}"
        try:
            os.rename(path, target)
        except FileNotFoundError:
            return
        record = self._failed(path.stem, {}, now, reason)
        _write_atomic(Path(f"{target}.job.toml"), dumps(record))

    def _failed(
        self, job_id: str, request: dict[str, Any], now: dt.datetime, reason: str
    ) -> dict[str, Any]:
        return {
            "id": job_id,
            "status": "failed",
            "reason": reason,
            "created": _aware(request.get("submitted")) or now,
            "finished": now,
            "turns": 0,
            "usd": 0.0,
            "warnings": [],
            "daemon": self.name,
            "commands": [],
        }

    # -- starting a job: its claim and worktree (ADR 0030)

    def _begin(self, job_id: str, request: dict[str, Any], now: dt.datetime) -> None:
        worktree = worktree_path(self.repo, self.config, job_id)
        branch = f"factory/{job_id}"
        record: dict[str, Any] = {
            "id": job_id,
            "status": "running",
            "reason": "",
            "base": request["base"],
            "branch": branch,
            "worktree": str(worktree),
            "task": request["task"],
            "open": request["open"],
            "created": _aware(request["submitted"]),
            "started": now,
            "turns": 0,
            "usd": 0.0,
            "warnings": [],
            "daemon": self.name,
            "commands": [],
        }

        def fail(reason: str) -> None:
            record.update(status="failed", reason=reason, finished=now)
            self._save(job_id, record)

        claims = self.repo.store / "claims"
        claims.mkdir(parents=True, exist_ok=True)
        claim = claims / claim_key(worktree)
        try:
            with open(claim, "x", encoding="utf-8") as f:
                f.write(job_id + "\n")
        except FileExistsError:
            other = claim.read_text(encoding="utf-8").strip() or "another job"
            fail(f"worktree {worktree} is already claimed by {other}")
            return
        if worktree.exists() or worktree.is_symlink():
            claim.unlink(missing_ok=True)
            fail(f"worktree path {worktree} already exists")
            return
        had_branch = self._has_branch(branch)
        added = _git(
            self.repo.main, "worktree", "add", "-q", "-b", branch, str(worktree), request["base"]
        )
        if added.returncode != 0:
            self._undo_worktree(worktree, branch, had_branch)
            claim.unlink(missing_ok=True)
            fail(
                f"git worktree add from base {request['base']!r} failed: {_last_line(added.stderr)}"
            )
            return
        job = _Job(job_id, request, record, worktree, claim)
        self.running[job_id] = job
        self._save(job_id, record)

    def _has_branch(self, branch: str) -> bool:
        found = _git(self.repo.main, "rev-parse", "--verify", "-q", f"refs/heads/{branch}")
        return found.returncode == 0

    def _undo_worktree(self, worktree: Path, branch: str, had_branch: bool) -> None:
        if worktree.exists():
            _git(self.repo.main, "worktree", "remove", "--force", str(worktree))
            shutil.rmtree(worktree, ignore_errors=True)
        _git(self.repo.main, "worktree", "prune")
        if not had_branch and self._has_branch(branch):
            _git(self.repo.main, "branch", "-D", branch)

    # -- running a job's commands

    def _advance(self, job: _Job, now: dt.datetime) -> None:
        commands: list[dict[str, Any]] = job.record["commands"]
        if (self.repo.job(job.id) / "cancel").exists():
            self.halt(job, now, HALT_CANCELLED)
            return
        if job.proc is not None:
            code = job.proc.poll()
            if code is None:
                return
            job.proc = None
            ran = commands[-1]
            ran["exit_code"] = code
            ran["duration_s"] = round(max((now - ran["started"]).total_seconds(), 0.0), 3)
            job.record["turns"] += 1
            self._save(job.id, job.record)
            if not job.request["open"] and code != 0:
                self._end(job, now, "failed", f"command {len(commands)} exited {code}")
                return
        closed = is_closed(self.repo, job.id, job.request)  # before listing: see _send's race
        argvs = [list(c) for c in job.request["commands"]] + sent_commands(self.repo, job.id)
        if len(commands) < len(argvs):
            self._run_next(job, argvs[len(commands)], now)
        elif closed:
            last = commands[-1]["exit_code"] if commands else 0
            if last == 0:
                self._end(job, now, "succeeded", "")
            else:
                self._end(job, now, "failed", f"the last command exited {last}")

    def _run_next(self, job: _Job, argv: list[str], now: dt.datetime) -> None:
        commands: list[dict[str, Any]] = job.record["commands"]
        log = self.repo.job(job.id) / "logs" / f"{len(commands) + 1:04d}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        commands.append(
            {"argv": argv, "exit_code": None, "started": now, "duration_s": None, "log": str(log)}
        )
        env = dict(os.environ)
        env["FACTORY_JOB"] = job.id
        job.proc = self.start(argv, job.worktree, env, log)
        job.record["warnings"].extend(getattr(job.proc, "warnings", []))
        self._save(job.id, job.record)

    # -- halting (AC-16): whatever the cause, the same steps in the same order

    def halt(self, job: _Job, now: dt.datetime, reason: str) -> None:
        """Kill the tree, record the halt, drop queued commands, hand off, keep the worktree."""
        self.running.pop(job.id, None)
        if job.proc is not None:
            job.proc.kill()
            ran = job.record["commands"][-1]
            ran["exit_code"] = job.proc.poll()
            ran["duration_s"] = round(max((now - ran["started"]).total_seconds(), 0.0), 3)
            job.record["turns"] += 1
            job.proc = None
        job.record.update(status="halted", reason=reason, finished=now)
        self._save(job.id, job.record)  # queued commands are dropped: nothing runs them now
        problem = self._handoff(job)
        if problem:
            job.record["warnings"].append(f"handoff: {problem}")
            self._save(job.id, job.record)

    def _handoff(self, job: _Job) -> str:
        """Write the halt's handoff with the worktree's own state.py; say what failed, if it did."""
        script = job.worktree / ".factory" / "state" / "state.py"
        if not script.is_file():
            return f"the worktree has no {script.relative_to(job.worktree).as_posix()}"
        task = job.request["task"]

        def state(*args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, str(script), "--root", str(job.worktree), *args],
                cwd=job.worktree,
                capture_output=True,
                text=True,
                check=False,
            )

        body = self.repo.job(job.id) / "handoff.md"
        try:
            if not (job.worktree / ".agentic" / "tasks" / f"{task}.md").is_file():
                made = state("task", "new", task, f"Runner job {job.id}")
                if made.returncode != 0:
                    return _last_line(made.stderr or made.stdout)
            _write_atomic(body, self._handoff_body(job))
            wrote = state("handoff", task, "--from", "runner", "--body-file", str(body))
        except OSError as exc:
            return str(exc)
        return "" if wrote.returncode == 0 else _last_line(wrote.stderr or wrote.stdout)

    def _handoff_body(self, job: _Job) -> str:
        record = job.record
        commands: list[dict[str, Any]] = record["commands"]
        done = [f"- Runner job `{job.id}` ran {len(commands)} command(s):"]
        done += [
            f"  {n}. `{' '.join(c['argv'])}` exited {c['exit_code']}"
            for n, c in enumerate(commands, start=1)
        ]
        done.append(f"- Turns used: {record['turns']}. Cost reported: ${record['usd']:.2f}.")
        branch = record["branch"]
        following = [
            f"- The runner halted this job: {record['reason']}.",
            f"- The worktree is kept at `{job.worktree}`, on branch `{branch}`.",
            "- To carry on from where it stopped, submit a follow-up job from the branch: "
            f"`python .factory/runner/run.py submit --base {branch} --task {job.request['task']}`.",
        ]
        return "\n".join(
            [
                "## Done",
                "",
                *done,
                "",
                "## Next",
                "",
                *following,
                "",
                "## Open questions",
                "",
                "- none",
                "",
            ]
        )

    def _end(self, job: _Job, now: dt.datetime, status: str, reason: str) -> None:
        self.running.pop(job.id, None)
        job.record.update(status=status, reason=reason, finished=now)
        if status == "succeeded":
            removed = _git(self.repo.main, "worktree", "remove", str(job.worktree))
            if removed.returncode == 0:
                job.claim.unlink(missing_ok=True)
            else:
                job.record["warnings"].append(
                    f"worktree kept: git refused to remove it: {_last_line(removed.stderr)}"
                )
        self._save(job.id, job.record)

    def _save(self, job_id: str, record: dict[str, Any]) -> None:
        folder = self.repo.job(job_id)
        folder.mkdir(parents=True, exist_ok=True)
        _write_atomic(folder / "job.toml", dumps(record))


# --- commands ---------------------------------------------------------------------------------


def _new_id() -> str:
    return f"j{_now():%y%m%d-%H%M%S}-{secrets.token_hex(2)}"


def _submit(args: argparse.Namespace, argv: list[str] | None) -> int:
    repo = find_repo(Path.cwd())
    config = load_config(repo.main)
    if args.id is not None:
        _check_job_id(args.id)
    base = config.base_ref if args.base is None else args.base
    if not base.strip():
        raise BadInput("--base must not be empty")
    if args.task is not None and not TASK_ID.fullmatch(args.task):
        raise BadInput(f"task id {args.task!r} must use only A-Z, a-z, 0-9, '.', '_' and '-'")
    if argv is not None and not argv:
        raise BadInput("no command after --")
    commands = [argv] if argv else []
    if not args.open and len(commands) != 1:
        raise BadInput("a job without --open needs one command after --")

    jobs = repo.store / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    job_id = args.id
    for _ in range(10):
        candidate = job_id or _new_id()
        try:
            os.mkdir(jobs / candidate)  # reserves the id (ADR 0030)
        except FileExistsError:
            if job_id is not None:
                raise BadInput(f"job id {job_id} is already used in this repository") from None
            continue
        job_id = candidate
        break
    else:
        raise BadInput("could not find a free job id")

    request = {
        "version": REQUEST_VERSION,
        "id": job_id,
        "base": base,
        "task": args.task or job_id,
        "open": bool(args.open),
        "commands": commands,
        "submitted": _now(),
    }
    tmp = _temp(repo.queue, dumps(request))
    os.rename(tmp, repo.queue / f"{job_id}.toml")
    print(job_id)
    return 0


def _send(args: argparse.Namespace, argv: list[str] | None) -> int:
    repo = find_repo(Path.cwd())
    request = find_request(repo, args.job)
    if not argv:
        raise BadInput("send needs a command after --")
    if not request["open"]:
        raise Refused(f"job {args.job} was submitted without --open, so it takes no commands")
    _refuse_if_finished(repo, args.job)
    if is_closed(repo, args.job, request):
        raise Refused(f"job {args.job} is closed")
    folder = repo.job(args.job) / "commands"
    folder.mkdir(parents=True, exist_ok=True)
    number = len(sent_commands(repo, args.job)) + 1
    while not _publish(
        _temp(folder, dumps({"argv": argv, "sent": _now()})), folder / f"{number:04d}.toml"
    ):
        number += 1
    return 0


def _close(args: argparse.Namespace, argv: list[str] | None) -> int:
    repo = find_repo(Path.cwd())
    request = find_request(repo, args.job)
    if argv is not None:
        raise BadInput("close takes no command")
    if not request["open"]:
        raise Refused(f"job {args.job} was submitted without --open, so it is already closed")
    _refuse_if_finished(repo, args.job)
    try:
        with open(repo.job(args.job) / "closed", "x", encoding="utf-8") as f:
            f.write(_now().isoformat() + "\n")
    except FileExistsError:
        raise Refused(f"job {args.job} is already closed") from None
    return 0


def _cancel(args: argparse.Namespace, argv: list[str] | None) -> int:
    if argv is not None:
        raise BadInput("cancel takes no command")
    repo = find_repo(Path.cwd())
    find_request(repo, args.job)  # an unknown job exits 2
    _refuse_if_finished(repo, args.job)
    claimed = repo.job(args.job) / "request.toml"
    try:
        os.rename(repo.queue / f"{args.job}.toml", claimed)  # beats any daemon to the claim
    except (FileNotFoundError, FileExistsError):
        pass  # a daemon has it: it halts the job when it sees the marker
    else:
        request = _read_toml(claimed)
        now = _now()
        record = {
            "id": args.job,
            "status": "halted",
            "reason": HALT_CANCELLED,
            "base": request["base"],
            "branch": f"factory/{args.job}",
            "task": request["task"],
            "open": request["open"],
            "created": _aware(request["submitted"]),
            "finished": now,
            "turns": 0,
            "usd": 0.0,
            "warnings": ["cancelled before it started: there was no worktree, so no handoff"],
            "commands": [],
        }
        _write_atomic(repo.job(args.job) / "job.toml", dumps(record))
        return 0
    try:
        with open(repo.job(args.job) / "cancel", "x", encoding="utf-8") as f:
            f.write(_now().isoformat() + "\n")
    except FileExistsError:
        pass  # already asked
    return 0


def _stop(args: argparse.Namespace, argv: list[str] | None) -> int:
    if argv is not None:
        raise BadInput("stop takes no command")
    repo = find_repo(Path.cwd())
    repo.store.mkdir(parents=True, exist_ok=True)
    _write_atomic(repo.store / "stop", _now().isoformat() + "\n")
    return 0


def _host(args: argparse.Namespace, argv: list[str] | None) -> int:
    """Windows (ADR 0031): wait for the daemon's go, which comes once this process is in the
    job, then run the command with an empty stdin and exit with its code."""
    if not argv:
        raise BadInput("_host needs a command after --")
    if sys.stdin.readline().strip() != "go":
        print("run.py _host: the daemon never said go, so the command didn't run", file=sys.stderr)
        return 1
    try:
        return subprocess.call(argv, stdin=subprocess.DEVNULL)
    except OSError as exc:
        print(f"run.py: cannot start {argv[0]}: {exc}", file=sys.stderr)
        return 127


def _jsonable(value: object) -> object:
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _status(args: argparse.Namespace, argv: list[str] | None) -> int:
    if argv is not None:
        raise BadInput("status takes no command")
    repo = find_repo(Path.cwd())
    data = job_status(repo, load_config(repo.main), args.job)
    if args.json:
        print(json.dumps(_jsonable(data), indent=2))
    else:
        sys.stdout.write(dumps(data))
    return 0


def _daemon(args: argparse.Namespace, argv: list[str] | None) -> int:
    if argv is not None:
        raise BadInput("--daemon takes no command")
    repo = find_repo(Path.cwd())
    return Daemon(repo, load_config(repo.main)).run()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run.py", description="Software Factory runner: jobs in their own git worktrees."
    )
    parser.add_argument("--daemon", action="store_true", help="run jobs from the queue")
    commands = parser.add_subparsers(dest="command")

    submit = commands.add_parser("submit", help="queue a job; its command follows --")
    submit.add_argument("--id", help="the job id (default: generated)")
    submit.add_argument("--base", help="the git ref to start from (default: gates.base_ref)")
    submit.add_argument("--task", help="the state.py task the job works on (default: its id)")
    submit.add_argument("--open", action="store_true", help="more commands will come by send")
    submit.set_defaults(run=_submit)

    send = commands.add_parser("send", help="add a command (after --) to an open job")
    send.add_argument("job")
    send.set_defaults(run=_send)

    close = commands.add_parser("close", help="say that no more commands will come")
    close.add_argument("job")
    close.set_defaults(run=_close)

    cancel = commands.add_parser("cancel", help="halt a job, queued or running")
    cancel.add_argument("job")
    cancel.set_defaults(run=_cancel)

    status = commands.add_parser("status", help="print a job's record")
    status.add_argument("job")
    status.add_argument("--json", action="store_true", help="print it as JSON")
    status.set_defaults(run=_status)

    stop = commands.add_parser("stop", help="stop the daemons; they halt their running jobs")
    stop.set_defaults(run=_stop)

    host = commands.add_parser("_host", help="internal: run one command inside a Job Object")
    host.set_defaults(run=_host)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    words = list(sys.argv[1:] if argv is None else argv)
    command: list[str] | None = None
    if "--" in words:  # everything after the first -- is the job's command, untouched
        cut = words.index("--")
        words, command = words[:cut], words[cut + 1 :]
    parser = _parser()
    try:
        args = parser.parse_args(words)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    if args.daemon == (args.command is not None):
        parser.print_usage(sys.stderr)
        print("run.py: give either --daemon or one command", file=sys.stderr)
        return 2
    if args.daemon:
        args.run = _daemon
    run: Callable[[argparse.Namespace, list[str] | None], int] = args.run
    try:
        return run(args, command)
    except BadInput as exc:
        print(f"run.py: {exc}", file=sys.stderr)
        return 2
    except Refused as exc:
        print(f"run.py: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"run.py: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
