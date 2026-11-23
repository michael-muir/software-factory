#!/usr/bin/env python3
"""Software Factory job index (E18): job records, leases, and a SQLite index over them.

Standard library only (PRD). A job is one piece of work, shared by every epic that drives it
(ADR 0050). Its record is a file, and the index is derived from the files (ADR 0051), except
for leases, which live only in the index (ADR 0052). Everything is under
`<git-common-dir>/factory/`, beside the runner's files (ADR 0030):

    work/<id>.toml           the job record
    work/<id>.<name>.toml    a sidecar, owned by another epic (E13: <id>.pipeline.toml)
    work/.ids/<id>/          reserves the id
    work/.tasks/<task>       reserves a task for a live job, holding the job id
    index.sqlite             the index

Usage:
    jobs.py new "<title>" [--id ID] [--track T] [--task TASK] [--branch B] [--worktree PATH]
    jobs.py show <job> [--json]
    jobs.py list [--status S] [--json] [--cached]
    jobs.py daemons [--json]
    jobs.py rebuild
    jobs.py set <job> [--session S] [--title T] [--track T] [--phase P] [--status S]
                [--task TASK] [--branch B] [--worktree PATH]
    jobs.py claim <job> [--session S] [--force] [--json]
    jobs.py beat <job> [--session S] [--json]
    jobs.py release <job> [--session S]
    jobs.py resume <job> [--session S] [--force] [--json]

The session is --session, else $FACTORY_SESSION; `claim` and `resume` generate one if neither
is given.
Exit codes: 0 done, 1 refused, 2 bad input (arguments, config, unknown job, no git repo).
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import decimal
import importlib.util
import json
import os
import re
import secrets
import shlex
import socket
import subprocess
import sys
import time
import tomllib
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import sqlite3

    HAVE_SQLITE = True
except ImportError:  # a Python built without it (spec assumption 11)
    HAVE_SQLITE = False

JOB_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,29}", re.ASCII)  # 30 at most, as E13's (ADR 0050)
GENERATED = re.compile(r"job-([1-9][0-9]*)", re.ASCII)
TASK_ID = re.compile(r"[A-Za-z0-9._-]+", re.ASCII)  # mirrors state.TASK_ID (E02)
SESSION_ID = re.compile(r"[A-Za-z0-9._:@-]{1,64}", re.ASCII)
SIDECAR = re.compile(r"[a-z][a-z0-9]{0,19}", re.ASCII)
TRACKS = ("full", "lite", "pass-through")  # mirrors state.TRACKS (E02)
PHASES = ("spec", "design", "test", "build", "gate", "review", "docs", "ship", "learn")
STATUSES = ("open", "blocked", "done", "cancelled")
ENDED = ("done", "cancelled")
RECORD_VERSION = 1
CONFIG_REL = Path(".agentic") / "config.toml"
BUSY_TIMEOUT_S = 10.0
SETTABLE = ("title", "track", "phase", "status", "task", "branch", "worktree")


class BadInput(Exception):
    """Bad arguments, config or job id: exit 2."""


class Refused(Exception):
    """A valid request the job's state doesn't allow: exit 1."""


class UnknownJob(BadInput):
    """No record for that job id."""


class IndexTooNew(BadInput):
    """The index's schema is newer than this tool knows."""


class IndexUnavailable(Refused):
    """The index couldn't be used: locked for longer than the busy timeout, or broken."""


def _now(now: float | None) -> float:
    return time.time() if now is None else now


def _stamp(now: float) -> dt.datetime:
    return dt.datetime.fromtimestamp(int(now), dt.UTC)


def _iso(seconds: float) -> str:
    return dt.datetime.fromtimestamp(seconds, dt.UTC).isoformat()


def _warn(message: str) -> None:
    print(f"jobs.py: warning: {message}", file=sys.stderr)


# --- config (mirrors factory_installer/config_schema.py for [jobs]) ----------------------------

Check = Callable[[Any], str | None]


def _positive(value: Any) -> str | None:
    return None if value > 0 else "must be greater than 0"


def _at_least(low: float) -> Check:
    def check(value: Any) -> str | None:
        return None if value >= low else f"must be at least {low:g}"

    return check


# key: (default, check). Both keys are numbers.
JOBS_RULES: dict[str, tuple[float, Check]] = {
    "lease_minutes": (10, _positive),
    "daemon_timeout_seconds": (60, _at_least(5)),
}


@dataclass(frozen=True)
class Config:
    lease_minutes: float
    daemon_timeout_seconds: float


def config_problems(data: dict[str, Any]) -> tuple[dict[str, float], list[str]]:
    """The effective [jobs] values, and one problem per bad key ("jobs.<key>: <reason>")."""
    values = {key: rule[0] for key, rule in JOBS_RULES.items()}
    table = data.get("jobs")
    if table is None:
        return values, []
    if not isinstance(table, dict):
        return values, ["jobs: expected a table"]
    problems: list[str] = []
    for key, value in table.items():
        if key not in JOBS_RULES:
            problems.append(f"jobs.{key}: unknown key")
            continue
        ok = isinstance(value, int | float) and not isinstance(value, bool)
        reason = JOBS_RULES[key][1](value) if ok else "expected a number"
        if reason is None:
            values[key] = value
        else:
            problems.append(f"jobs.{key}: {reason}")
    return values, problems


def _load_config_at(main: Path) -> Config:
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
    return Config(values["lease_minutes"], values["daemon_timeout_seconds"])


# --- the repo -----------------------------------------------------------------------------------


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
    def work(self) -> Path:
        return self.store / "work"

    @property
    def index(self) -> Path:
        return self.store / "index.sqlite"

    def record(self, job_id: str) -> Path:
        return self.work / f"{job_id}.toml"


def find_repo(cwd: Path) -> Repo:
    """The repo `cwd` is in, from the main checkout or any worktree (spec AC-01)."""
    common = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if common.returncode != 0:
        raise BadInput(f"{cwd} is not inside a git repository")
    if _git(cwd, "rev-parse", "--verify", "-q", "HEAD^{commit}").returncode != 0:
        raise BadInput("the git repository has no commit yet")
    common_dir = Path(common.stdout.strip())
    return Repo(main=main_worktree(cwd, common_dir), store=common_dir / "factory")


LISTING_TRIES = (0.1, 0.2, 0.4, 0.8)  # back-off between tries of `git worktree list` (#87)


def _listing(cwd: Path) -> subprocess.CompletedProcess[str]:
    """`git worktree list --porcelain`, retried: another process's `git worktree add` can make
    it fail, or come back empty, for a moment (#87)."""
    for pause in (*LISTING_TRIES, None):
        listing = _git(cwd, "worktree", "list", "--porcelain")
        if listing.returncode == 0 and "worktree " in listing.stdout:
            return listing
        if pause is not None:
            time.sleep(pause)
    return listing


def main_worktree(cwd: Path, common: Path) -> Path:
    """The main worktree's root: the common dir's parent when that is a normal `.git` folder,
    found without listing; otherwise the first entry of `git worktree list` (#87)."""
    dot_git = common.parent / ".git"
    if common.name == ".git" and dot_git.is_dir() and os.path.samefile(dot_git, common):
        return common.parent
    listing = _listing(cwd)
    first = next((ln for ln in listing.stdout.splitlines() if ln.startswith("worktree ")), "")
    if listing.returncode != 0 or not first:
        raise BadInput("cannot find the repository's main worktree")
    return Path(first[len("worktree ") :])


def load_config(repo: Repo) -> Config:
    """The [jobs] config from the main worktree's `.agentic/config.toml`, validated."""
    return _load_config_at(repo.main)


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
    """Flat TOML: scalars and arrays, then tables, then arrays of tables. None is left out."""
    lines = [
        f"{key} = {_toml_value(value)}"
        for key, value in data.items()
        if value is not None and not isinstance(value, dict) and not _is_tables(value)
    ]
    for key, value in data.items():
        if isinstance(value, dict):
            lines += ["", f"[{key}]"]
            lines += [f"{json.dumps(k)} = {_toml_value(v)}" for k, v in value.items()]
    for key, value in data.items():
        if _is_tables(value):
            for table in value:
                lines += ["", f"[[{key}]]"]
                lines += [f"{k} = {_toml_value(v)}" for k, v in table.items() if v is not None]
    return "\n".join(lines) + "\n"


def _write_atomic(path: Path, text: str) -> None:
    """Replace path whole. On Windows a reader holding the file open makes replace fail: retry."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".tmp-{secrets.token_hex(8)}"
    with open(tmp, "x", encoding="utf-8", newline="\n") as f:
        f.write(text)
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 19:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(0.05)


# --- job records (ADR 0050) ---------------------------------------------------------------------


def _check_job_id(job_id: str) -> None:
    if not JOB_ID.fullmatch(job_id):
        raise BadInput(f"job id {job_id!r} must match {JOB_ID.pattern}")


def _check_task(task: str) -> None:
    if not TASK_ID.fullmatch(task):
        raise BadInput(f"task id {task!r} must match {TASK_ID.pattern}")


def _check_session(session: str) -> None:
    if not SESSION_ID.fullmatch(session):
        raise BadInput(f"session id {session!r} must match {SESSION_ID.pattern}")


def _check_field(key: str, value: object) -> None:
    if not isinstance(value, str):
        raise BadInput(f"{key} must be a string")
    if key == "title" and not value.strip():
        raise BadInput("title must not be empty")
    choices = {"track": TRACKS, "phase": PHASES, "status": STATUSES}.get(key)
    if choices is not None and value not in choices:
        raise BadInput(f"{key} must be one of {', '.join(choices)}, not {value!r}")
    if key == "task":
        _check_task(value)


_STR_KEYS = ("id", "title", "track", "phase", "status", "task", "branch", "worktree", "owner")
_CLAIM_KEYS = {"session": str, "at": dt.datetime, "forced": bool, "from": str}


def record_problems(data: dict[str, Any], job_id: str) -> list[str]:
    """What's wrong with a parsed record, one problem per key."""
    found: list[str] = []
    expected = {"version", *_STR_KEYS, "tasks", "created", "updated", "claims"}
    found += [f"{key}: unknown key" for key in data if key not in expected]
    if data.get("version") != RECORD_VERSION:
        found.append(f"version: must be {RECORD_VERSION}")
    for key in _STR_KEYS:
        value = data.get(key)
        if not isinstance(value, str):
            found.append(f"{key}: expected a string")
            continue
        try:
            if key in ("title", "track", "phase", "status", "task"):
                _check_field(key, value)
        except BadInput as exc:
            found.append(f"{key}: {exc}")
    if data.get("id") != job_id:
        found.append(f"id: must be {job_id!r}, the file's name")
    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks or not all(isinstance(t, str) for t in tasks):
        found.append("tasks: expected a non-empty list of strings")
    elif data.get("task") not in tasks:
        found.append("tasks: must hold the current task")
    for key in ("created", "updated"):
        value = data.get(key)
        if not isinstance(value, dt.datetime) or value.tzinfo is None:
            found.append(f"{key}: expected a date-time with a time zone")
    claims = data.get("claims", [])
    if not isinstance(claims, list) or not all(
        isinstance(c, dict)
        and set(c) == set(_CLAIM_KEYS)
        and all(isinstance(c[k], t) for k, t in _CLAIM_KEYS.items())
        for c in claims
    ):
        found.append("claims: each entry needs session, at, forced and from")
    return found


def read_job(repo: Repo, job_id: str) -> dict[str, Any]:
    """The job's record, checked. Raises UnknownJob, or BadInput if the record is damaged."""
    if not JOB_ID.fullmatch(job_id):
        raise UnknownJob(f"unknown job {job_id}")
    path = repo.record(job_id)
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        raise UnknownJob(f"unknown job {job_id}") from None
    except tomllib.TOMLDecodeError as exc:
        raise BadInput(f"{path}: {exc}") from exc
    problems = record_problems(data, job_id)
    if problems:
        raise BadInput(f"{path}: " + "; ".join(problems))
    data.setdefault("claims", [])
    return data


def _save(repo: Repo, data: dict[str, Any]) -> None:
    _write_atomic(repo.record(data["id"]), dumps(data))


def _reserve_id(repo: Repo, job_id: str | None) -> str:
    ids = repo.work / ".ids"
    ids.mkdir(parents=True, exist_ok=True)
    if job_id is not None:
        _check_job_id(job_id)
        try:
            os.mkdir(ids / job_id)
        except FileExistsError:
            raise BadInput(f"job id {job_id} is already used in this repo") from None
        return job_id
    numbers = [int(m.group(1)) for p in ids.iterdir() if (m := GENERATED.fullmatch(p.name))]
    n = max(numbers, default=0) + 1
    while True:
        try:
            os.mkdir(ids / f"job-{n}")
            return f"job-{n}"
        except FileExistsError:
            n += 1


def _task_holder(repo: Repo, task: str) -> str | None:
    """The live job holding a task reservation, or None if it's free (or held by an ended job)."""
    try:
        holder = (repo.work / ".tasks" / task).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    try:
        if read_job(repo, holder)["status"] in ENDED:
            return None
    except BadInput:
        return None  # a reservation whose record is gone or unreadable holds nothing
    return holder


def _reserve_task(repo: Repo, task: str, job_id: str) -> None:
    folder = repo.work / ".tasks"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / task
    for _ in range(3):
        try:
            with open(path, "x", encoding="utf-8", newline="\n") as f:
                f.write(job_id + "\n")
            return
        except FileExistsError:
            holder = _task_holder(repo, task)
            if holder == job_id:
                return
            if holder is not None:
                raise Refused(f"task {task} belongs to job {holder}") from None
            path.unlink(missing_ok=True)  # a stale reservation: take it
    raise Refused(f"task {task} is being reserved by another job")


def _release_tasks(repo: Repo, data: dict[str, Any]) -> None:
    for task in data["tasks"]:
        path = repo.work / ".tasks" / task
        try:
            if path.read_text(encoding="utf-8").strip() == data["id"]:
                path.unlink()
        except FileNotFoundError:
            continue


def sidecar_path(repo: Repo, job_id: str, name: str) -> Path:
    """Where another epic keeps its details about a job: `work/<id>.<name>.toml` (ADR 0050)."""
    _check_job_id(job_id)
    if not SIDECAR.fullmatch(name):
        raise BadInput(f"sidecar name {name!r} must match {SIDECAR.pattern}")
    return repo.work / f"{job_id}.{name}.toml"


def sidecars(repo: Repo, job_id: str) -> dict[str, str]:
    """The job's sidecars by name. Their contents are never read."""
    found: dict[str, str] = {}
    if repo.work.is_dir():
        prefix = f"{job_id}."
        for path in sorted(repo.work.iterdir()):
            name = path.name
            if name.startswith(prefix) and name.endswith(".toml"):
                middle = name[len(prefix) : -len(".toml")]
                if SIDECAR.fullmatch(middle):
                    found[middle] = str(path)
    return found


# --- the index (ADR 0051) -----------------------------------------------------------------------

# Each migration is a tuple of statements; the schema's version is the number applied.
MIGRATIONS: tuple[tuple[str, ...], ...] = (
    (  # 1 (E18-T1): job records and leases
        "CREATE TABLE jobs (id TEXT PRIMARY KEY, title TEXT, track TEXT, phase TEXT,"
        " status TEXT, task TEXT, branch TEXT, worktree TEXT, owner TEXT, created TEXT,"
        " updated TEXT, path TEXT, sidecars TEXT)",
        "CREATE TABLE job_tasks (task TEXT NOT NULL, job TEXT NOT NULL, PRIMARY KEY (task, job))",
        "CREATE TABLE claims (job TEXT NOT NULL, n INTEGER NOT NULL, session TEXT, at TEXT,"
        " forced INTEGER, from_session TEXT, PRIMARY KEY (job, n))",
        "CREATE TABLE leases (job TEXT PRIMARY KEY, session TEXT NOT NULL, minutes REAL NOT NULL,"
        " acquired REAL NOT NULL, expires REAL NOT NULL)",
        "CREATE TABLE problems (path TEXT PRIMARY KEY, problem TEXT NOT NULL)",
    ),
    (  # 2 (E18-T2): runner jobs, usage and the worktrees' state
        "ALTER TABLE jobs ADD COLUMN tasks TEXT",
        "CREATE TABLE runner_jobs (id TEXT PRIMARY KEY, status TEXT, task TEXT, daemon TEXT,"
        " usd REAL, created TEXT, data TEXT NOT NULL)",
        "CREATE TABLE commands (runner_job TEXT NOT NULL, n INTEGER NOT NULL, argv TEXT,"
        " exit_code INTEGER, started TEXT, duration_s REAL, log TEXT, PRIMARY KEY (runner_job, n))",
        "CREATE TABLE usage (runner_job TEXT NOT NULL, file TEXT NOT NULL, usd TEXT NOT NULL,"
        " at TEXT NOT NULL, PRIMARY KEY (runner_job, file))",
        "CREATE TABLE worktrees (path TEXT PRIMARY KEY, branch TEXT, head TEXT, phase TEXT,"
        " active_task TEXT, blockers TEXT)",
        "CREATE TABLE tasks (worktree TEXT NOT NULL, task TEXT NOT NULL, status TEXT,"
        " review_round INTEGER, open_findings TEXT, handoff TEXT, next TEXT,"
        " PRIMARY KEY (worktree, task))",
    ),
    (  # 3 (E18-T3): daemon heartbeats
        "CREATE TABLE daemons (id TEXT PRIMARY KEY, host TEXT, pid INTEGER, started REAL NOT NULL,"
        " beat REAL NOT NULL)",
    ),
)
SCHEMA_VERSION = len(MIGRATIONS)
LIVE_TABLES = ("leases", "daemons")  # not derived from files: kept by a rebuild
DERIVED_TABLES = (
    "jobs",
    "job_tasks",
    "claims",
    "problems",
    "runner_jobs",
    "commands",
    "usage",
    "worktrees",
    "tasks",
)


def _require_sqlite() -> None:
    if not HAVE_SQLITE:
        raise BadInput("this Python has no sqlite3 module, which the job index needs")


@contextlib.contextmanager
def _transaction(con: sqlite3.Connection) -> Iterator[None]:
    con.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")


def _version(con: sqlite3.Connection) -> int:
    row = con.execute("PRAGMA user_version").fetchone()
    return int(row[0])


def _too_new(repo: Repo, found: int) -> IndexTooNew:
    return IndexTooNew(
        f"{repo.index} has schema version {found}, newer than this tool's {SCHEMA_VERSION}"
    )


def _migrate(con: sqlite3.Connection, repo: Repo) -> None:
    found = _version(con)
    if found > SCHEMA_VERSION:
        raise _too_new(repo, found)
    if found == SCHEMA_VERSION:
        return
    snapshot = take_snapshot(repo)
    with _transaction(con):
        found = _version(con)  # another process may have migrated it meanwhile
        for statements in MIGRATIONS[found:]:
            for statement in statements:
                con.execute(statement)
        con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        _apply(con, snapshot)


def _set_aside(repo: Repo, why: Exception) -> None:
    """Move a damaged index out of the way, so a new one can be built from the files."""
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    target = repo.index.with_name(f"index.sqlite.damaged-{stamp}-{secrets.token_hex(2)}")
    try:
        os.replace(repo.index, target)
        journal = repo.index.with_name("index.sqlite-journal")
        if journal.exists():
            os.replace(journal, Path(f"{target}-journal"))
    except OSError as exc:
        raise BadInput(
            f"the index {repo.index} is damaged ({why}) and can't be moved aside ({exc}); "
            "stop the other factory processes and run `jobs.py rebuild`"
        ) from exc
    _warn(f"the index was damaged ({why}); moved it to {target.name} and rebuilt it")


def _connect(repo: Repo) -> sqlite3.Connection:
    """Open and migrate the index. A damaged one is set aside and rebuilt (ADR 0051)."""
    for attempt in range(2):
        try:
            con = sqlite3.connect(repo.index, timeout=BUSY_TIMEOUT_S, isolation_level=None)
        except sqlite3.Error as exc:
            raise IndexUnavailable(f"index unavailable: {exc}") from exc
        try:
            found = _version(con)
            if found > SCHEMA_VERSION:
                raise _too_new(repo, found)
            check = con.execute("PRAGMA quick_check").fetchall()
            if check != [("ok",)]:
                raise sqlite3.DatabaseError(f"quick_check: {check[0][0]}")
            _migrate(con, repo)
            return con
        except sqlite3.OperationalError as exc:
            con.close()
            raise IndexUnavailable(f"index unavailable: {exc}") from exc
        except sqlite3.DatabaseError as exc:
            con.close()
            if attempt == 1:
                raise IndexUnavailable(f"index unavailable: {exc}") from exc
            _set_aside(repo, exc)
        except BaseException:
            con.close()
            raise
    raise AssertionError("unreachable")  # pragma: no cover


@contextlib.contextmanager
def _index(repo: Repo) -> Iterator[sqlite3.Connection]:
    """An open, migrated index connection; closed on exit, because Windows holds open files."""
    _require_sqlite()
    repo.store.mkdir(parents=True, exist_ok=True)
    con = _connect(repo)
    try:
        yield con
    except sqlite3.Error as exc:
        raise IndexUnavailable(f"index unavailable: {exc}") from exc
    finally:
        con.close()


def _refuse_a_newer_index(repo: Repo) -> None:
    """Before `new` writes anything: an index from a newer kit is refused (spec AC-09)."""
    if not HAVE_SQLITE or not repo.index.is_file():
        return
    try:
        con = sqlite3.connect(repo.index, timeout=BUSY_TIMEOUT_S)
    except sqlite3.Error:
        return
    try:
        found = _version(con)
    except sqlite3.Error:
        return  # locked or damaged: `new` still writes its record, with a warning
    finally:
        con.close()
    if found > SCHEMA_VERSION:
        raise _too_new(repo, found)


def _put_job(con: sqlite3.Connection, repo: Repo, data: dict[str, Any]) -> None:
    job_id = data["id"]
    con.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    con.execute("DELETE FROM job_tasks WHERE job = ?", (job_id,))
    con.execute("DELETE FROM claims WHERE job = ?", (job_id,))
    con.execute(
        "INSERT INTO jobs (id, title, track, phase, status, task, branch, worktree, owner,"
        " created, updated, path, sidecars, tasks)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            job_id,
            data["title"],
            data["track"],
            data["phase"],
            data["status"],
            data["task"],
            data["branch"],
            data["worktree"],
            data["owner"],
            data["created"].isoformat(),
            data["updated"].isoformat(),
            str(repo.record(job_id)),
            json.dumps(sidecars(repo, job_id)),
            json.dumps(data["tasks"]),
        ),
    )
    con.executemany(
        "INSERT OR IGNORE INTO job_tasks VALUES (?, ?)", [(t, job_id) for t in data["tasks"]]
    )
    con.executemany(
        "INSERT INTO claims VALUES (?, ?, ?, ?, ?, ?)",
        [
            (job_id, n, c["session"], c["at"].isoformat(), int(c["forced"]), c["from"])
            for n, c in enumerate(data["claims"], start=1)
        ],
    )


# --- readers: the runner's files (ADR 0030) and each worktree's .agentic (E02) ------------------

RUNNER_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,39}", re.ASCII)  # mirrors run.JOB_ID (E16)
STATE_PY = Path(__file__).resolve().parent.parent / "state" / "state.py"
_STATE_MODULE: list[Any] = []


def _state_module() -> Any:
    """The kit's own state.py, loaded by path as docs.py does; None if it isn't installed."""
    if not _STATE_MODULE:
        module = None
        if STATE_PY.is_file():
            spec = importlib.util.spec_from_file_location("factory_state_for_jobs", STATE_PY)
            if spec is not None and spec.loader is not None:
                module = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = module  # dataclasses look their module up here
                spec.loader.exec_module(module)
        _STATE_MODULE.append(module)
    return _STATE_MODULE[0]


@dataclass
class Snapshot:
    """Everything the derived tables hold, read from the files before any lock is taken."""

    repo: Repo
    records: list[dict[str, Any]] = field(default_factory=list)
    problems: list[tuple[str, str]] = field(default_factory=list)
    runners: list[dict[str, Any]] = field(default_factory=list)
    usage: list[tuple[str, str, str, str]] = field(default_factory=list)
    worktrees: list[dict[str, Any]] = field(default_factory=list)


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        return tomllib.load(f)


def _runner_ids(repo: Repo) -> list[str]:
    ids: set[str] = set()
    queue = repo.store / "queue"
    if queue.is_dir():
        ids |= {p.stem for p in queue.glob("*.toml") if RUNNER_ID.fullmatch(p.stem)}
    folder = repo.store / "jobs"
    if folder.is_dir():
        ids |= {p.name for p in folder.iterdir() if p.is_dir() and RUNNER_ID.fullmatch(p.name)}
    return sorted(ids)


def _runner_request(repo: Repo, runner_id: str) -> dict[str, Any] | None:
    places = (
        repo.store / "queue" / f"{runner_id}.toml",
        repo.store / "jobs" / runner_id / "request.toml",
    )
    for _ in range(3):  # a claim moves the file between the two places
        for path in places:
            try:
                return _read_toml(path)
            except FileNotFoundError:
                continue
    return None


def _runner_worktree_root(main: Path) -> str:
    try:
        value = _read_toml(main / CONFIG_REL).get("runner", {}).get("worktree_root", "")
    except (OSError, tomllib.TOMLDecodeError, AttributeError):
        return ""
    return value if isinstance(value, str) else ""


def _usage_files(folder: Path) -> list[tuple[str, decimal.Decimal, str]]:
    """(file name, amount, time) for each report, as run.py's ledger counts them."""
    found: list[tuple[str, decimal.Decimal, str]] = []
    if not folder.is_dir():
        return found
    for path in sorted(folder.iterdir()):
        if path.suffix != ".usd" or path.name.startswith("."):
            continue
        try:
            text = path.read_text(encoding="utf-8").strip()
            amount = decimal.Decimal(text)
        except (OSError, decimal.InvalidOperation):
            continue
        nanos = path.name.split("-", 1)[0]
        at = _iso(int(nanos) / 1e9) if nanos.isdigit() else ""
        found.append((path.name, amount, at))
    return found


def runner_view(repo: Repo, runner_id: str, worktree_root: str = "") -> dict[str, Any] | None:
    """A runner job as `run.py status --json` shows it (pinned by a test), or None if it has
    neither a request nor a record yet. Raises BadInput for files that can't be read."""
    folder = repo.store / "jobs" / runner_id
    try:
        request = _runner_request(repo, runner_id)
        record: dict[str, Any] | None = None
        if (folder / "job.toml").is_file():
            record = _read_toml(folder / "job.toml")
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise BadInput(f"runner job {runner_id}: {exc}") from exc
    if request is None and record is None:
        return None
    usd = float(sum((u[1] for u in _usage_files(folder / "usage")), decimal.Decimal(0)))
    try:
        if request is None:
            raise KeyError("request")
        logs = folder / "logs"
        argvs = [list(c) for c in request["commands"]]
        sent = folder / "commands"
        if sent.is_dir():
            names = sorted(p.name for p in sent.iterdir() if re.fullmatch(r"\d{4,}\.toml", p.name))
            argvs += [list(_read_toml(sent / name)["argv"]) for name in names]
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
        main = repo.main
        base = main / worktree_root if worktree_root else main.parent / f"{main.name}.worktrees"
        data: dict[str, Any] = {
            "id": runner_id,
            "status": "queued",
            "reason": "",
            "base": request["base"],
            "branch": f"factory/{runner_id}",
            "worktree": str(Path(os.path.normpath(base / runner_id))),
            "task": request["task"],
            "open": request["open"],
            "closed": not request["open"] or (folder / "closed").exists(),
            "created": request["submitted"],
            "started": None,
            "finished": None,
            "turns": 0,
            "usd": 0.0,
            "warnings": [],
            "commands": commands,
        }
    except (KeyError, TypeError, OSError, tomllib.TOMLDecodeError):
        if record is None:
            raise BadInput(f"runner job {runner_id}: its request can't be read") from None
        data = {"id": runner_id, "commands": []}  # a malformed request: its record alone
        commands = data["commands"]
    ran = dict(record or {})
    for n, command in enumerate(ran.pop("commands", [])):
        if n < len(commands):
            commands[n].update(command)
        elif request is None:
            commands.append(command)
    data.update(ran)
    data["usd"] = usd
    result = _jsonable(data)
    assert isinstance(result, dict)
    return result


def _section(body: str, heading: str) -> str:
    lines = body.split("\n")
    out: list[str] = []
    inside = False
    for line in lines:
        if line.startswith("## "):
            inside = line.strip() == heading
            continue
        if inside:
            out.append(line)
    return "\n".join(out).strip()


def _worktree_list(repo: Repo) -> list[dict[str, str]]:
    listing = _listing(repo.main)
    if listing.returncode != 0:
        raise BadInput(f"git worktree list failed: {listing.stderr.strip()}")
    found: list[dict[str, str]] = []
    entry: dict[str, str] = {}
    for line in [*listing.stdout.splitlines(), ""]:
        if not line.strip():
            if entry.get("path") and "bare" not in entry and Path(entry["path"]).is_dir():
                found.append(entry)
            entry = {}
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            entry = {"path": value, "head": "", "branch": ""}
        elif key == "HEAD":
            entry["head"] = value
        elif key == "branch":
            entry["branch"] = value.removeprefix("refs/heads/")
        elif key == "bare":
            entry["bare"] = "1"
    return found


def _worktree_state(path: Path, problems: list[tuple[str, str]]) -> dict[str, Any]:
    """The phase, active task, blockers, and each task's state, read with the kit's state.py."""
    found: dict[str, Any] = {"phase": "", "active_task": "", "blockers": [], "tasks": []}
    state = _state_module()
    agentic = path / ".agentic"
    if not agentic.is_dir():
        return found
    if state is None:
        problems.append((str(agentic), "the kit's state.py isn't installed"))
        return found

    def parsed(file: Path) -> dict[str, Any] | None:
        try:
            result = state.parse(file.read_text(encoding="utf-8"))
        except OSError as exc:
            problems.append((str(file), str(exc)))
            return None
        if isinstance(result, str):
            problems.append((str(file), result))
            return None
        front, body = result
        return {"front": front, "body": body}

    state_md = agentic / "STATE.md"
    if state_md.is_file():
        text = state_md.read_text(encoding="utf-8")
        if text.replace("\r\n", "\n") != state.E01_PLACEHOLDER:
            got = parsed(state_md)
            if got is not None:
                front = got["front"]
                found["phase"] = str(front.get("phase", ""))
                found["active_task"] = str(front.get("active_task", ""))
                blockers = front.get("blockers", [])
                found["blockers"] = [str(b) for b in blockers] if isinstance(blockers, list) else []
    newest: dict[str, tuple[Any, str, str]] = {}
    handoffs = agentic / "handoffs"
    if handoffs.is_dir():
        for file in sorted(handoffs.glob("*.md")):
            got = parsed(file)
            if got is None:
                continue
            task = str(got["front"].get("task", ""))
            order = state._handoff_order(f".agentic/handoffs/{file.name}", got["front"])
            if task not in newest or order > newest[task][0]:
                newest[task] = (order, str(file), _section(got["body"], "## Next"))
    tasks = agentic / "tasks"
    if tasks.is_dir():
        for file in sorted(tasks.glob("*.md")):
            got = parsed(file)
            if got is None:
                continue
            front = got["front"]
            findings = front.get("findings", [])
            task_id = file.stem
            latest = newest.get(task_id)
            found["tasks"].append(
                {
                    "id": task_id,
                    "status": str(front.get("status", "")),
                    "review_round": front.get("review_round", 0),
                    "open_findings": [
                        {k: f.get(k) for k in ("id", "severity", "summary")}
                        for f in (findings if isinstance(findings, list) else [])
                        if isinstance(f, dict) and f.get("status") == "open"
                    ],
                    "handoff": latest[1] if latest else "",
                    "next": latest[2] if latest else "",
                }
            )
    return found


def take_snapshot(repo: Repo) -> Snapshot:
    """Read every file the derived tables come from. Problems are collected, never raised."""
    snap = Snapshot(repo)
    if repo.work.is_dir():
        for path in sorted(repo.work.glob("*.toml")):
            job_id = path.name[: -len(".toml")]
            if not JOB_ID.fullmatch(job_id):
                continue  # a sidecar
            try:
                snap.records.append(read_job(repo, job_id))
            except BadInput as exc:
                snap.problems.append((str(path), str(exc)))
    root = _runner_worktree_root(repo.main)
    for runner_id in _runner_ids(repo):
        try:
            view = runner_view(repo, runner_id, root)
        except BadInput as exc:
            snap.problems.append((str(repo.store / "jobs" / runner_id), str(exc)))
            continue
        if view is not None:
            snap.runners.append(view)
            usage = _usage_files(repo.store / "jobs" / runner_id / "usage")
            snap.usage += [(runner_id, name, str(amount), at) for name, amount, at in usage]
    try:
        entries = _worktree_list(repo)
    except BadInput as exc:
        snap.problems.append((str(repo.main), str(exc)))
        entries = []
    for entry in entries:
        snap.worktrees.append({**entry, **_worktree_state(Path(entry["path"]), snap.problems)})
    return snap


def _put_runner(
    con: sqlite3.Connection, view: dict[str, Any], usage: list[tuple[str, str, str, str]]
) -> None:
    runner_id = view["id"]
    for table, key in (("runner_jobs", "id"), ("commands", "runner_job"), ("usage", "runner_job")):
        con.execute(f"DELETE FROM {table} WHERE {key} = ?", (runner_id,))  # fixed names
    con.execute(
        "INSERT INTO runner_jobs VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            runner_id,
            view.get("status", ""),
            view.get("task", ""),
            view.get("daemon", ""),
            view.get("usd", 0.0),
            view.get("created", ""),
            json.dumps(view),
        ),
    )
    con.executemany(
        "INSERT INTO commands VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                runner_id,
                n,
                json.dumps(c.get("argv")),
                c.get("exit_code"),
                c.get("started"),
                c.get("duration_s"),
                c.get("log"),
            )
            for n, c in enumerate(view.get("commands", []), start=1)
        ],
    )
    con.executemany("INSERT OR REPLACE INTO usage VALUES (?, ?, ?, ?)", usage)


def _apply(con: sqlite3.Connection, snap: Snapshot) -> None:
    """Replace every derived row with the snapshot. Leases are kept (ADR 0051)."""
    for table in DERIVED_TABLES:
        con.execute(f"DELETE FROM {table}")  # fixed table names, never input
    for data in snap.records:
        _put_job(con, snap.repo, data)
    con.executemany("INSERT OR REPLACE INTO problems VALUES (?, ?)", snap.problems)
    usage_by_runner: dict[str, list[tuple[str, str, str, str]]] = {}
    for row in snap.usage:
        usage_by_runner.setdefault(row[0], []).append(row)
    for view in snap.runners:
        _put_runner(con, view, usage_by_runner.get(view["id"], []))
    for tree in snap.worktrees:
        con.execute(
            "INSERT OR REPLACE INTO worktrees VALUES (?, ?, ?, ?, ?, ?)",
            (
                tree["path"],
                tree["branch"],
                tree["head"],
                tree["phase"],
                tree["active_task"],
                json.dumps(tree["blockers"]),
            ),
        )
        con.executemany(
            "INSERT OR REPLACE INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    tree["path"],
                    t["id"],
                    t["status"],
                    t["review_round"],
                    json.dumps(t["open_findings"]),
                    t["handoff"],
                    t["next"],
                )
                for t in tree["tasks"]
            ],
        )
    con.execute("DELETE FROM leases WHERE job NOT IN (SELECT id FROM jobs)")


def _refresh(repo: Repo) -> Snapshot:
    """Re-read every file, then replace the derived rows in one short transaction."""
    snap = take_snapshot(repo)
    with _index(repo) as con, _transaction(con):
        _apply(con, snap)
    return snap


def _index_job(repo: Repo, data: dict[str, Any]) -> None:
    """Write-through for a record written without a lease check: a failure is only a warning."""
    try:
        with _index(repo) as con, _transaction(con):
            _put_job(con, repo, data)
    except (IndexUnavailable, IndexTooNew) as exc:
        _warn(f"the index wasn't updated: {exc}")


# --- the runner's hooks (ADR 0053): run.py calls these, and treats any failure as a warning ------


def refresh_runner(repo: Repo, runner_id: str) -> None:
    """Re-read one runner job's files and replace its rows (spec AC-06)."""
    view = runner_view(repo, runner_id, _runner_worktree_root(repo.main))
    usage = _usage_files(repo.store / "jobs" / runner_id / "usage")
    rows = [(runner_id, name, str(amount), at) for name, amount, at in usage]
    with _index(repo) as con, _transaction(con):
        if view is None:
            for table, key in (("runner_jobs", "id"), ("commands", "runner_job")):
                con.execute(f"DELETE FROM {table} WHERE {key} = ?", (runner_id,))  # fixed names
        else:
            _put_runner(con, view, rows)


def daemon_beat(repo: Repo, daemon_id: str, now: float) -> None:
    """A runner daemon's heartbeat, under the id its records carry (`host:pid:hex`, AC-14)."""
    host, _, rest = daemon_id.partition(":")
    pid_text = rest.partition(":")[0]
    pid = int(pid_text) if pid_text.isdigit() else None
    with _index(repo) as con, _transaction(con):
        con.execute(
            "INSERT INTO daemons (id, host, pid, started, beat) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT (id) DO UPDATE SET beat = excluded.beat",
            (daemon_id, host, pid, now, now),
        )


def renew_for_task(repo: Repo, task: str, now: float) -> None:
    """While a runner job's command runs, keep the live lease of the job it belongs to (AC-13).
    A lease that has already expired is never revived: that job has crashed."""
    with _index(repo) as con, _transaction(con):
        owner = con.execute(_BELONGS, (task,)).fetchone()
        if owner is None:
            return
        lease = _lease(con, owner[0])
        if lease is None or lease.expires <= now:
            return
        expires = max(lease.expires, now + lease.minutes * 60)
        _put_lease(con, Lease(lease.job, lease.session, lease.acquired, expires, lease.minutes))


def _daemon_entries(con: sqlite3.Connection, now: float, timeout: float) -> list[dict[str, Any]]:
    """Every daemon with a heartbeat, and every daemon a running runner job names, with its
    state and the running runner jobs it left stale (AC-14)."""
    found: dict[str, dict[str, Any]] = {}
    for daemon_id, host, pid, started, beat in con.execute(
        "SELECT id, host, pid, started, beat FROM daemons ORDER BY id"
    ).fetchall():
        found[daemon_id] = {
            "id": daemon_id,
            "host": host,
            "pid": pid,
            "started": _iso(started),
            "beat": _iso(beat),
            "state": "alive" if now - beat <= timeout else "dead",
            "stale_runner_jobs": [],
        }
    for runner_id, daemon_id in con.execute(
        "SELECT id, daemon FROM runner_jobs WHERE status = 'running' ORDER BY id"
    ).fetchall():
        key = daemon_id or ""
        if key not in found:
            host, _, rest = key.partition(":")
            pid_text = rest.partition(":")[0]
            found[key] = {
                "id": key,
                "host": host,
                "pid": int(pid_text) if pid_text.isdigit() else None,
                "started": None,
                "beat": None,
                "state": "dead",  # no heartbeat at all: never seen, or lost with the index
                "stale_runner_jobs": [],
            }
        if found[key]["state"] == "dead":
            found[key]["stale_runner_jobs"].append(runner_id)
    return [found[k] for k in sorted(found)]


def daemons(repo: Repo, *, now: float | None = None) -> list[dict[str, Any]]:
    """Each daemon, `alive` or `dead` by `jobs.daemon_timeout_seconds`, and its stale runner
    jobs. The runner's files are never changed: repairing them is E22's."""
    config = load_config(repo)
    _refresh(repo)
    with _index(repo) as con:
        return _daemon_entries(con, _now(now), config.daemon_timeout_seconds)


# --- leases (ADR 0052) --------------------------------------------------------------------------


@dataclass(frozen=True)
class Lease:
    job: str
    session: str
    acquired: float  # Unix seconds
    expires: float
    minutes: float

    def as_json(self) -> dict[str, Any]:
        return {
            "job": self.job,
            "session": self.session,
            "acquired": _iso(self.acquired),
            "expires": _iso(self.expires),
            "minutes": self.minutes,
        }


def _lease(con: sqlite3.Connection, job_id: str) -> Lease | None:
    row = con.execute(
        "SELECT session, acquired, expires, minutes FROM leases WHERE job = ?", (job_id,)
    ).fetchone()
    if row is None:
        return None
    return Lease(job_id, row[0], row[1], row[2], row[3])


def _put_lease(con: sqlite3.Connection, lease: Lease) -> None:
    con.execute(
        "INSERT OR REPLACE INTO leases (job, session, minutes, acquired, expires)"
        " VALUES (?, ?, ?, ?, ?)",
        (lease.job, lease.session, lease.minutes, lease.acquired, lease.expires),
    )


def _held(con: sqlite3.Connection, job_id: str, session: str, now: float) -> Lease:
    """The session's live lease on the job, or Refused."""
    lease = _lease(con, job_id)
    if lease is None or lease.session != session or lease.expires <= now:
        holder = "no one" if lease is None else lease.session
        if lease is not None and lease.expires <= now:
            holder += " (expired)"
        raise Refused(
            f"only the session holding job {job_id}'s live lease may change it; "
            f"the lease is held by {holder}"
        )
    return lease


def _state(data: dict[str, Any], lease: Lease | None, now: float) -> str:
    if data["status"] in ENDED:
        return str(data["status"])
    if lease is None:
        return "unclaimed"
    return "claimed" if lease.expires > now else "crashed"


def lease_state(repo: Repo, job_id: str, *, now: float | None = None) -> str:
    """unclaimed, claimed, crashed, done or cancelled (spec AC-10, ADR 0052)."""
    data = read_job(repo, job_id)
    with _index(repo) as con:
        return _state(data, _lease(con, job_id), _now(now))


def claim(
    repo: Repo,
    config: Config,
    job_id: str,
    session: str,
    *,
    force: bool = False,
    now: float | None = None,
) -> Lease:
    """Give `session` the job's lease (spec AC-11). A live lease held by another is Refused,
    unless `force`, which the record's claim entry records."""
    _check_session(session)
    moment = _now(now)
    read_job(repo, job_id)  # an unknown job is bad input, before the index is touched
    with _index(repo) as con, _transaction(con):
        data = read_job(repo, job_id)
        if data["status"] in ENDED:
            raise Refused(f"job {job_id} is {data['status']}")
        held = _lease(con, job_id)
        lease = Lease(
            job_id, session, moment, moment + config.lease_minutes * 60, config.lease_minutes
        )
        if held is not None and held.session == session:
            _put_lease(con, lease)
            return lease
        live = held is not None and held.expires > moment
        if live and not force:
            assert held is not None
            raise Refused(
                f"job {job_id} is claimed by {held.session} until {_iso(held.expires)}; "
                "use --force to take it"
            )
        data["owner"] = session
        data["updated"] = _stamp(moment)
        data["claims"].append(
            {
                "session": session,
                "at": _stamp(moment),
                "forced": live,
                "from": held.session if held is not None else "",
            }
        )
        _put_lease(con, lease)
        _save(repo, data)
        _put_job(con, repo, data)
        return lease


def beat(
    repo: Repo, config: Config, job_id: str, session: str, *, now: float | None = None
) -> Lease:
    """Renew the holder's lease, even an expired one no one else has claimed (spec AC-12). With
    no lease at all, the record's owner takes it back: the index may have been lost."""
    _check_session(session)
    moment = _now(now)
    data = read_job(repo, job_id)
    with _index(repo) as con, _transaction(con):
        held = _lease(con, job_id)
        mine = held.session == session if held is not None else data["owner"] == session
        if not mine:
            holder = held.session if held is not None else "no one"
            raise Refused(f"session {session} doesn't hold job {job_id}'s lease ({holder} does)")
        lease = Lease(
            job_id, session, moment, moment + config.lease_minutes * 60, config.lease_minutes
        )
        if held is not None:
            lease = Lease(job_id, session, held.acquired, lease.expires, lease.minutes)
        _put_lease(con, lease)
        return lease


def release(repo: Repo, job_id: str, session: str) -> None:
    """End the holder's lease; the job is unclaimed again (spec AC-12)."""
    _check_session(session)
    read_job(repo, job_id)
    with _index(repo) as con, _transaction(con):
        held = _lease(con, job_id)
        if held is None or held.session != session:
            holder = held.session if held is not None else "no one"
            raise Refused(f"session {session} doesn't hold job {job_id}'s lease ({holder} does)")
        con.execute("DELETE FROM leases WHERE job = ?", (job_id,))


# --- new, set, sidecars -------------------------------------------------------------------------


def new_job(
    repo: Repo,
    title: str,
    *,
    job_id: str | None = None,
    track: str = "full",
    task: str | None = None,
    branch: str = "",
    worktree: str = "",
    now: float | None = None,
) -> dict[str, Any]:
    """Create a job and return its record (spec AC-02)."""
    _require_sqlite()
    _check_field("title", title)
    _check_field("track", track)
    _check_field("branch", branch)
    _check_field("worktree", worktree)
    if job_id is not None:
        _check_job_id(job_id)
    if task is not None:
        _check_task(task)
    _refuse_a_newer_index(repo)
    moment = _stamp(_now(now))
    reserved = _reserve_id(repo, job_id)
    the_task = reserved if task is None else task
    try:
        _check_task(the_task)
        _reserve_task(repo, the_task, reserved)
    except (BadInput, Refused):
        os.rmdir(repo.work / ".ids" / reserved)  # the id isn't burnt by a refused task
        raise
    data: dict[str, Any] = {
        "version": RECORD_VERSION,
        "id": reserved,
        "title": title,
        "track": track,
        "phase": "spec",
        "status": "open",
        "task": the_task,
        "tasks": [the_task],
        "branch": branch,
        "worktree": worktree,
        "owner": "",
        "created": moment,
        "updated": moment,
        "claims": [],
    }
    _save(repo, data)
    _index_job(repo, data)
    return data


def set_job(
    repo: Repo, job_id: str, session: str, *, now: float | None = None, **fields: str
) -> dict[str, Any]:
    """Change a job's fields; only the session holding its live lease may (spec AC-04)."""
    _check_session(session)
    for key, value in fields.items():
        if key not in SETTABLE:
            raise BadInput(f"{key} can't be set; settable: {', '.join(SETTABLE)}")
        _check_field(key, value)
    moment = _now(now)
    read_job(repo, job_id)
    with _index(repo) as con, _transaction(con):
        _held(con, job_id, session, moment)
        data = read_job(repo, job_id)
        was_ended = data["status"] in ENDED
        task = fields.get("task")
        if task is not None and task != data["task"]:
            _reserve_task(repo, task, job_id)
            if task not in data["tasks"]:
                data["tasks"].append(task)
        data.update(fields)
        data["updated"] = _stamp(moment)
        if data["status"] in ENDED and not was_ended:
            _release_tasks(repo, data)
        elif was_ended and data["status"] not in ENDED:
            for held_task in data["tasks"]:
                _reserve_task(repo, held_task, job_id)
        _save(repo, data)
        _put_job(con, repo, data)
        return data


def write_sidecar(
    repo: Repo, job_id: str, name: str, text: str, session: str, *, now: float | None = None
) -> Path:
    """Write another epic's sidecar atomically, while `session` holds the job's live lease."""
    path = sidecar_path(repo, job_id, name)
    _check_session(session)
    moment = _now(now)
    data = read_job(repo, job_id)
    with _index(repo) as con, _transaction(con):
        _held(con, job_id, session, moment)
        _write_atomic(path, text)
        _put_job(con, repo, data)
    return path


# --- reading the index (spec AC-05, AC-10) ----------------------------------------------------

_BELONGS = (
    "SELECT jt.job FROM job_tasks jt JOIN jobs j ON j.id = jt.job"
    " WHERE jt.task = ? AND j.status NOT IN ('done', 'cancelled') ORDER BY j.created, j.id LIMIT 1"
)


def _job_entries(con: sqlite3.Connection, now: float, timeout: float) -> list[dict[str, Any]]:
    stale_jobs: set[str] = set()
    for daemon in _daemon_entries(con, now, timeout):
        for runner_id in daemon["stale_runner_jobs"]:
            task = con.execute("SELECT task FROM runner_jobs WHERE id = ?", (runner_id,)).fetchone()
            owner = con.execute(_BELONGS, (task[0],)).fetchone() if task else None
            if owner:
                stale_jobs.add(owner[0])
    rows = con.execute(
        "SELECT id, title, track, phase, status, task, tasks, branch, worktree, owner, created,"
        " updated FROM jobs ORDER BY created, id"
    ).fetchall()
    found: list[dict[str, Any]] = []
    for row in rows:
        keys = ("id", "title", "track", "phase", "status", "task", "tasks", "branch")
        entry: dict[str, Any] = dict(zip(keys, row[:8], strict=True))
        entry["tasks"] = json.loads(row[6] or "[]")
        entry.update(worktree=row[8], owner=row[9], created=row[10], updated=row[11])
        lease = _lease(con, entry["id"])
        entry["state"] = _state(entry, lease, now)
        entry["stale"] = entry["id"] in stale_jobs  # a running runner job of a dead daemon
        entry["lease"] = (
            None if lease is None else {k: v for k, v in lease.as_json().items() if k != "job"}
        )
        found.append(entry)
    return found


def _runner_entries(con: sqlite3.Connection) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for task, data in con.execute("SELECT task, data FROM runner_jobs ORDER BY id").fetchall():
        view: dict[str, Any] = json.loads(data)
        owner = con.execute(_BELONGS, (task,)).fetchone()
        view["belongs_to"] = owner[0] if owner else ""
        found.append(view)
    return found


def _worktree_entries(con: sqlite3.Connection) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    rows = con.execute(
        "SELECT path, branch, head, phase, active_task, blockers FROM worktrees ORDER BY path"
    ).fetchall()
    for path, branch, head, phase, active, blockers in rows:
        tasks = [
            {
                "id": task,
                "status": status,
                "review_round": review_round,
                "open_findings": json.loads(findings),
                "handoff": handoff,
                "next": next_text,
            }
            for task, status, review_round, findings, handoff, next_text in con.execute(
                "SELECT task, status, review_round, open_findings, handoff, next FROM tasks"
                " WHERE worktree = ? ORDER BY task",
                (path,),
            ).fetchall()
        ]
        found.append(
            {
                "path": path,
                "branch": branch,
                "head": head,
                "phase": phase,
                "active_task": active,
                "blockers": json.loads(blockers),
                "tasks": tasks,
            }
        )
    return found


def index_listing(
    repo: Repo, *, status: str | None = None, now: float | None = None, cached: bool = False
) -> dict[str, Any]:
    """Refresh the index from the files (unless `cached`), then return what it holds (spec
    AC-05, AC-10). `cached` answers from the rows alone, as a dashboard would."""
    config = load_config(repo)
    if not cached:
        _refresh(repo)
    moment = _now(now)
    with _index(repo) as con:
        jobs = _job_entries(con, moment, config.daemon_timeout_seconds)
        data = {
            "jobs": [j for j in jobs if status is None or j["status"] == status],
            "runner_jobs": _runner_entries(con),
            "usage": [
                {"runner_job": r, "file": f, "usd": u, "at": a}
                for r, f, u, a in con.execute(
                    "SELECT runner_job, file, usd, at FROM usage ORDER BY runner_job, file"
                ).fetchall()
            ],
            "worktrees": _worktree_entries(con),
            "problems": [
                {"path": path, "problem": problem}
                for path, problem in con.execute(
                    "SELECT path, problem FROM problems ORDER BY path"
                ).fetchall()
            ],
        }
    return data


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def job_context(repo: Repo, job_id: str, listing: dict[str, Any]) -> dict[str, Any]:
    """The job's runner jobs, oldest first, and the state of the worktree it works in."""
    data = read_job(repo, job_id)
    runners = sorted(
        (r for r in listing["runner_jobs"] if r["belongs_to"] == job_id),
        key=lambda r: (str(r.get("created", "")), r["id"]),
    )
    worktree = data["worktree"] or next(
        (str(r.get("worktree", "")) for r in reversed(runners) if r.get("worktree")), ""
    )
    tree = next(
        (w for w in listing["worktrees"] if worktree and _same_path(w["path"], worktree)), None
    )
    return {"runner_jobs": runners, "worktree_state": tree}


# --- resume (spec AC-15, AC-16) -----------------------------------------------------------------

RESUME_COMMANDS = 5  # the last commands shown for each runner job
STATE_FILE = ".agentic/STATE.md"
TASKS_DIR = ".agentic/tasks/"
HANDOFFS_DIR = ".agentic/handoffs/"


def _git_bytes(
    cwd: Path, *args: str, stdin: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    """git with raw output, decoded by the caller as UTF-8 whatever the locale says."""
    try:
        return subprocess.run(
            ["git", *args], cwd=cwd, input=stdin, capture_output=True, check=False
        )
    except OSError as exc:
        raise BadInput(f"cannot run git: {exc}") from exc


def _branch_exists(repo: Repo, branch: str) -> bool:
    if not branch:
        return False
    found = _git_bytes(repo.main, "rev-parse", "--verify", "-q", f"refs/heads/{branch}^{{commit}}")
    return found.returncode == 0


def _registered(repo: Repo, worktree: str) -> bool:
    """Whether git still lists the worktree, even with its folder gone (`prunable`)."""
    listing = _listing(repo.main)
    paths = [
        ln[len("worktree ") :] for ln in listing.stdout.splitlines() if ln.startswith("worktree ")
    ]
    return any(_same_path(p, worktree) for p in paths)


def _state_rel(rel: str, task: str) -> bool:
    """The state files resume reads: STATE.md, the job's task file, and every handoff."""
    if rel == STATE_FILE or rel == f"{TASKS_DIR}{task}.md":
        return True
    name = rel[len(HANDOFFS_DIR) :]
    return rel.startswith(HANDOFFS_DIR) and name.endswith(".md") and "/" not in name


def _worktree_files(path: Path, task: str) -> dict[str, str]:
    agentic = path / ".agentic"
    candidates = [agentic / "STATE.md", agentic / "tasks" / f"{task}.md"]
    if (agentic / "handoffs").is_dir():
        candidates += sorted((agentic / "handoffs").glob("*.md"))
    files: dict[str, str] = {}
    for file in candidates:
        rel = file.relative_to(path).as_posix()
        if file.is_file() and _state_rel(rel, task):
            with contextlib.suppress(OSError, UnicodeDecodeError):
                files[rel] = file.read_text(encoding="utf-8")
    return files


def _branch_files(repo: Repo, branch: str, task: str) -> dict[str, str]:
    """The state files committed on a branch, read with `git ls-tree` and `git cat-file`."""
    ref = f"refs/heads/{branch}"
    listed = _git_bytes(repo.main, "ls-tree", "-r", "-z", "--name-only", ref, "--", ".agentic/")
    if listed.returncode != 0:
        return {}
    names = [raw.decode("utf-8", "replace") for raw in listed.stdout.split(b"\0") if raw]
    wanted = [rel for rel in names if "\n" not in rel and _state_rel(rel, task)]
    if not wanted:
        return {}
    batch = _git_bytes(
        repo.main,
        "cat-file",
        "--batch",
        stdin="".join(f"{ref}:{rel}\n" for rel in wanted).encode("utf-8"),
    )
    files: dict[str, str] = {}
    out, pos = batch.stdout, 0
    for rel in wanted:
        end = out.find(b"\n", pos)
        if end < 0:
            break
        header = out[pos:end].split()
        pos = end + 1
        if len(header) != 3 or not header[2].isdigit():
            continue  # "<ref>:<path> missing"
        size = int(header[2])
        files[rel] = out[pos : pos + size].decode("utf-8", "replace")
        pos += size + 1
    return files


def _state_from_files(files: dict[str, str], task: str, source: str, place: str) -> dict[str, Any]:
    """The phase, active task, the job's task and its newest handoff, from state file texts."""
    found: dict[str, Any] = {
        "source": source,
        "place": place,
        "phase": "",
        "active_task": "",
        "task": None,
        "handoff": None,
        "next": "",
        "problems": [],
    }
    state = _state_module()
    if state is None:
        found["problems"].append("the kit's state.py isn't installed")
        return found

    def parsed(rel: str) -> tuple[dict[str, Any], str] | None:
        result = state.parse(files[rel])
        if isinstance(result, str):
            found["problems"].append(f"{rel}: {result}")
            return None
        return result[0], result[1]

    text = files.get(STATE_FILE)
    if text is not None and text.replace("\r\n", "\n") != state.E01_PLACEHOLDER:
        got = parsed(STATE_FILE)
        if got is not None:
            found["phase"] = str(got[0].get("phase", ""))
            found["active_task"] = str(got[0].get("active_task", ""))
    task_rel = f"{TASKS_DIR}{task}.md"
    if task_rel in files:
        got = parsed(task_rel)
        if got is not None:
            front = got[0]
            findings = front.get("findings", [])
            found["task"] = {
                "id": task,
                "title": str(front.get("title", "")),
                "status": str(front.get("status", "")),
                "review_round": front.get("review_round", 0),
                "open_findings": [
                    {k: f.get(k) for k in ("id", "severity", "summary")}
                    for f in (findings if isinstance(findings, list) else [])
                    if isinstance(f, dict) and f.get("status") == "open"
                ],
            }
    best: tuple[Any, str, dict[str, Any], str] | None = None
    for rel in sorted(r for r in files if r.startswith(HANDOFFS_DIR)):
        got = parsed(rel)
        if got is None or str(got[0].get("task", "")) != task:
            continue
        order = state._handoff_order(rel, got[0])
        if best is None or order > best[0]:
            best = (order, rel, got[0], got[1])
    if best is not None:
        _, rel, front, body = best
        found["handoff"] = {
            "path": rel,
            "from": str(front.get("from", "")),
            "to": str(front.get("to", "")),
            "created": str(_jsonable(front.get("created", ""))),
            "body": body,
        }
        found["next"] = _section(body, "## Next")
    return found


def _state_from_index(tree: dict[str, Any], task: str) -> dict[str, Any]:
    """What the index still holds about a worktree that has gone, with its branch."""
    entry = next((t for t in tree["tasks"] if t["id"] == task), None)
    return {
        "source": "index",
        "place": tree["path"],
        "phase": tree["phase"],
        "active_task": tree["active_task"],
        "task": None
        if entry is None
        else {
            "id": task,
            "title": "",
            "status": entry["status"],
            "review_round": entry["review_round"],
            "open_findings": entry["open_findings"],
        },
        "handoff": None if entry is None or not entry["handoff"] else {"path": entry["handoff"]},
        "next": "" if entry is None else entry["next"],
        "problems": [],
    }


def _where_from(data: dict[str, Any], runners: list[dict[str, Any]]) -> tuple[str, str]:
    """The job's branch and worktree, each from its record or else its newest runner job that
    has left the queue (a queued one has no worktree yet), else its newest runner job."""
    started = [r for r in runners if r.get("status") != "queued"] or runners
    newest = started[-1] if started else {}
    branch = data["branch"] or str(newest.get("branch") or "")
    worktree = data["worktree"] or str(newest.get("worktree") or "")
    return branch, worktree


def _command_line(argv: list[str]) -> str:
    return subprocess.list2cmdline(argv) if sys.platform == "win32" else shlex.join(argv)


def resume(
    repo: Repo,
    config: Config,
    job_id: str,
    session: str,
    *,
    force: bool = False,
    now: float | None = None,
) -> dict[str, Any]:
    """Claim the job by `claim`'s rules, then gather what a new session needs to carry on:
    the job and its lease, where it works, its runner jobs and cost, and its state (AC-15,
    AC-16). A live lease held by another session is Refused, unless `force`."""
    moment = _now(now)
    lease = claim(repo, config, job_id, session, force=force, now=moment)
    data = read_job(repo, job_id)
    before = index_listing(repo, cached=True, now=moment)
    old_runners = [r for r in before["runner_jobs"] if r["belongs_to"] == job_id]
    _, old_tree = _where_from(data, sorted(old_runners, key=lambda r: str(r.get("created", ""))))
    cached = next(
        (w for w in before["worktrees"] if old_tree and _same_path(w["path"], old_tree)), None
    )
    listing = index_listing(repo, now=moment)
    context = job_context(repo, job_id, listing)
    runners: list[dict[str, Any]] = context["runner_jobs"]
    branch, worktree = _where_from(data, runners)
    trees = [w["path"] for w in listing["worktrees"]]
    worktree_exists = bool(worktree) and any(_same_path(p, worktree) for p in trees)
    branch_exists = _branch_exists(repo, branch)
    notes: list[str] = []
    rebuild: list[list[str]] = []
    if not branch and not worktree:
        notes.append("the job names no branch or worktree, and no runner job has one")
    elif branch and not branch_exists:
        notes.append(f"the branch {branch} doesn't exist")
    if worktree and not worktree_exists:
        if branch_exists:
            if _registered(repo, worktree):
                rebuild.append(["git", "worktree", "prune"])
            rebuild.append(["git", "worktree", "add", worktree, branch])
            notes.append(
                f"the worktree {worktree} has gone; rebuild it from the branch {branch} with: "
                + " && ".join(_command_line(argv) for argv in rebuild)
            )
            notes.append(f"the task and handoff are read from the branch {branch}'s commits")
        elif branch:
            notes.append(
                f"the worktree {worktree} and the branch {branch} have both gone; "
                "this is what the index still has"
            )
        else:
            notes.append(f"the worktree {worktree} has gone, and the job names no branch")
    task = data["task"]
    if worktree_exists:
        state = _state_from_files(_worktree_files(Path(worktree), task), task, "worktree", worktree)
    elif branch_exists:
        state = _state_from_files(_branch_files(repo, branch, task), task, "branch", branch)
    elif cached is not None:
        state = _state_from_index(cached, task)
    else:
        state = _state_from_files({}, task, "none", "")
    usd_by_runner: dict[str, decimal.Decimal] = {}
    for row in listing["usage"]:
        amount = usd_by_runner.get(row["runner_job"], decimal.Decimal(0))
        usd_by_runner[row["runner_job"]] = amount + decimal.Decimal(row["usd"])
    with _index(repo) as con:
        stale = {
            runner_id
            for daemon in _daemon_entries(con, moment, config.daemon_timeout_seconds)
            for runner_id in daemon["stale_runner_jobs"]
        }
    runner_entries: list[dict[str, Any]] = []
    total = decimal.Decimal(0)
    for runner in runners:
        commands = list(enumerate(runner.get("commands", []), start=1))[-RESUME_COMMANDS:]
        usd = usd_by_runner.get(runner["id"], decimal.Decimal(0))
        total += usd
        runner_entries.append(
            {
                "id": runner["id"],
                "status": runner.get("status", ""),
                "stale": runner["id"] in stale,
                "task": runner.get("task", ""),
                "branch": runner.get("branch", ""),
                "worktree": runner.get("worktree", ""),
                "commands": [
                    {"n": n, "argv": c.get("argv"), "exit_code": c.get("exit_code")}
                    for n, c in commands
                ],
                "usd": str(usd),
            }
        )
    shown: dict[str, Any] = dict(data)
    shown["state"] = _state(data, lease, moment)
    shown["lease"] = lease.as_json()
    shown["sidecars"] = sidecars(repo, job_id)
    result = {
        "job": shown,
        "where": {
            "branch": branch,
            "branch_exists": branch_exists,
            "worktree": worktree,
            "worktree_exists": worktree_exists,
            "rebuild": rebuild,
            "notes": notes,
        },
        "runner_jobs": runner_entries,
        "cost": {"usd": str(total)},
        "state": state,
    }
    found = _jsonable(result)
    assert isinstance(found, dict)
    return found


def _exists(value: str, exists: bool) -> str:
    return "(none)" if not value else f"{value} ({'exists' if exists else 'gone'})"


def render_resume(data: dict[str, Any]) -> str:
    """`resume`'s text form: the same five sections as its JSON."""
    job, where, state = data["job"], data["where"], data["state"]
    lease = job["lease"]
    lines = [
        f"--- job {job['id']}: {job['title']}",
        f"state: {job['state']}, held by {lease['session']} until {lease['expires']}",
        f"track: {job['track']}   phase: {job['phase']}   status: {job['status']}",
        f"task: {job['task']}   tasks: {', '.join(job['tasks'])}",
        f"owner: {job['owner']}   created: {job['created']}   updated: {job['updated']}",
    ]
    lines += [f"sidecar {name}: {path}" for name, path in job["sidecars"].items()]
    lines += [
        "--- where",
        f"branch: {_exists(where['branch'], where['branch_exists'])}",
        f"worktree: {_exists(where['worktree'], where['worktree_exists'])}",
    ]
    lines += [f"rebuild: {_command_line(argv)}" for argv in where["rebuild"]]
    lines += [f"note: {note}" for note in where["notes"]]
    lines.append("--- runner jobs")
    for runner in data["runner_jobs"]:
        stale = "   STALE: its daemon is dead" if runner["stale"] else ""
        lines.append(f"{runner['id']}: {runner['status']}   cost {runner['usd']}{stale}")
        for command in runner["commands"]:
            code = "not run" if command["exit_code"] is None else f"exit {command['exit_code']}"
            lines.append(f"  {command['n']}. [{code}] {_command_line(command['argv'] or [])}")
    if not data["runner_jobs"]:
        lines.append("(none)")
    lines += ["--- cost", f"total: {data['cost']['usd']}"]
    source = {
        "worktree": f"from the worktree {state['place']}",
        "branch": f"from the branch {state['place']}",
        "index": f"from the index, for the worktree {state['place']}",
        "none": "none found",
    }[state["source"]]
    lines += [
        f"--- state ({source})",
        f"phase: {state['phase']}   active task: {state['active_task']}",
    ]
    task = state["task"]
    if task is None:
        lines.append(f"task {job['task']}: no task file")
    else:
        lines.append(f"task {task['id']}: {task['status']}   review round: {task['review_round']}")
        lines.append("open findings:" if task["open_findings"] else "open findings: none")
        lines += [f"  {f['id']} [{f['severity']}] {f['summary']}" for f in task["open_findings"]]
    handoff = state["handoff"]
    if handoff is None:
        lines.append("no handoff for this task")
    elif "body" in handoff:
        to = handoff["to"] or "anyone"
        lines.append(f"--- newest handoff: {handoff['path']} (from {handoff['from']} to {to})")
        lines.append(handoff["body"].strip("\n"))
    else:
        lines += [f"--- newest handoff: {handoff['path']} (gone; its ## Next, from the index)"]
        lines.append(state["next"])
    lines += [f"problem: {p}" for p in state["problems"]]
    return "\n".join(lines) + "\n"


# --- the command line ---------------------------------------------------------------------------


def _jsonable(value: object) -> object:
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _generated_session() -> str:
    host = re.sub(r"[^a-z0-9-]+", "-", socket.gethostname().lower()).strip("-") or "host"
    return f"s-{host[:32]}-{os.getpid()}-{secrets.token_hex(2)}"


def _session(args: argparse.Namespace, *, generate: bool = False) -> str:
    session: str | None = args.session
    if session is None:
        session = os.environ.get("FACTORY_SESSION") or None
    if session is None:
        if not generate:
            raise BadInput("give --session, or set FACTORY_SESSION")
        session = _generated_session()
    _check_session(session)
    return session


def _repo_and_config() -> tuple[Repo, Config]:
    repo = find_repo(Path.cwd())
    return repo, load_config(repo)


def _new(args: argparse.Namespace) -> int:
    repo, _ = _repo_and_config()
    data = new_job(
        repo,
        args.title,
        job_id=args.id,
        track=args.track,
        task=args.task,
        branch=args.branch,
        worktree=args.worktree,
    )
    print(data["id"])
    return 0


def _show(args: argparse.Namespace) -> int:
    repo, _ = _repo_and_config()
    data = read_job(repo, args.job)
    listing = index_listing(repo)
    moment = time.time()
    with _index(repo) as con:
        lease = _lease(con, args.job)
    shown: dict[str, Any] = dict(data)
    shown["state"] = _state(data, lease, moment)
    shown["lease"] = None if lease is None else lease.as_json()
    shown["sidecars"] = sidecars(repo, args.job)
    if args.json:
        shown.update(job_context(repo, args.job, listing))
        print(json.dumps(_jsonable(shown), indent=2))
    else:
        if shown["lease"] is None:
            del shown["lease"]  # TOML has no null
        sys.stdout.write(dumps(shown))
    return 0


def _list(args: argparse.Namespace) -> int:
    repo, _ = _repo_and_config()
    data = index_listing(repo, status=args.status, cached=args.cached)
    if args.json:
        print(json.dumps(data, indent=2))
        return 0
    for job in data["jobs"]:
        state = job["state"] + (",stale" if job["stale"] else "")
        owner = job["lease"]["session"] if job["lease"] else "-"
        cells = (job["id"], state, job["track"], job["phase"], job["status"], job["task"], owner)
        print("  ".join(cells) + "  " + job["title"])
    for problem in data["problems"]:
        print(f"problem: {problem['path']}: {problem['problem']}")
    return 0


def _daemons(args: argparse.Namespace) -> int:
    repo, _ = _repo_and_config()
    found = daemons(repo)
    if args.json:
        print(json.dumps(found, indent=2))
        return 0
    for entry in found:
        stale = ", ".join(entry["stale_runner_jobs"]) or "none"
        print(f"{entry['id']}  {entry['state']}  beat {entry['beat'] or 'never'}  stale: {stale}")
    return 0


def _rebuild(args: argparse.Namespace) -> int:
    repo, _ = _repo_and_config()
    snap = _refresh(repo)
    print(
        f"rebuilt the index: {len(snap.records)} jobs, {len(snap.runners)} runner jobs, "
        f"{len(snap.worktrees)} worktrees, {len(snap.problems)} problems"
    )
    return 0


def _set(args: argparse.Namespace) -> int:
    repo, _ = _repo_and_config()
    fields = {key: getattr(args, key) for key in SETTABLE if getattr(args, key) is not None}
    if not fields:
        raise BadInput("set needs at least one field to change")
    set_job(repo, args.job, _session(args), **fields)
    return 0


def _print_lease(lease: Lease, as_json: bool) -> None:
    if as_json:
        print(json.dumps(lease.as_json(), indent=2))
    else:
        print(f"session {lease.session}")
        print(f"expires {_iso(lease.expires)}")


def _claim(args: argparse.Namespace) -> int:
    repo, config = _repo_and_config()
    session = _session(args, generate=True)
    _print_lease(claim(repo, config, args.job, session, force=args.force), args.json)
    return 0


def _beat(args: argparse.Namespace) -> int:
    repo, config = _repo_and_config()
    _print_lease(beat(repo, config, args.job, _session(args)), args.json)
    return 0


def _release(args: argparse.Namespace) -> int:
    repo, _ = _repo_and_config()
    release(repo, args.job, _session(args))
    print(f"released {args.job}")
    return 0


def _resume(args: argparse.Namespace) -> int:
    repo, config = _repo_and_config()
    session = _session(args, generate=True)
    data = resume(repo, config, args.job, session, force=args.force)
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        sys.stdout.write(render_resume(data))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jobs.py", description="Software Factory job index: job records and leases."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    new = commands.add_parser("new", help="create a job and print its id")
    new.add_argument("title")
    new.add_argument("--id", help="the job id (default: job-<n>)")
    new.add_argument("--track", default="full", help="full, lite or pass-through")
    new.add_argument("--task", help="the state.py task (default: the job id)")
    new.add_argument("--branch", default="")
    new.add_argument("--worktree", default="")
    new.set_defaults(run=_new)

    show = commands.add_parser("show", help="print a job's record")
    show.add_argument("job")
    show.add_argument("--json", action="store_true", help="print it as JSON")
    show.set_defaults(run=_show)

    list_ = commands.add_parser("list", help="list every job, refreshed from the files")
    list_.add_argument("--status", choices=STATUSES, help="only jobs with this status")
    list_.add_argument("--json", action="store_true", help="print the whole index as JSON")
    list_.add_argument(
        "--cached", action="store_true", help="answer from the index without re-reading files"
    )
    list_.set_defaults(run=_list)

    daemons_ = commands.add_parser("daemons", help="list the runner daemons, alive or dead")
    daemons_.add_argument("--json", action="store_true")
    daemons_.set_defaults(run=_daemons)

    rebuild = commands.add_parser("rebuild", help="rebuild the index from the files")
    rebuild.set_defaults(run=_rebuild)

    set_ = commands.add_parser("set", help="change a job's fields (lease holder only)")
    set_.add_argument("job")
    set_.add_argument("--session")
    for key in SETTABLE:
        set_.add_argument(f"--{key}")
    set_.set_defaults(run=_set)

    claim_ = commands.add_parser("claim", help="take a job's lease")
    claim_.add_argument("job")
    claim_.add_argument("--session")
    claim_.add_argument("--force", action="store_true", help="take a live lease from another")
    claim_.add_argument("--json", action="store_true")
    claim_.set_defaults(run=_claim)

    beat_ = commands.add_parser("beat", help="renew a job's lease")
    beat_.add_argument("job")
    beat_.add_argument("--session")
    beat_.add_argument("--json", action="store_true")
    beat_.set_defaults(run=_beat)

    release_ = commands.add_parser("release", help="end a job's lease")
    release_.add_argument("job")
    release_.add_argument("--session")
    release_.set_defaults(run=_release)

    resume_ = commands.add_parser(
        "resume", help="claim a job and print what a new session needs to carry on"
    )
    resume_.add_argument("job")
    resume_.add_argument("--session")
    resume_.add_argument("--force", action="store_true", help="take a live lease from another")
    resume_.add_argument("--json", action="store_true")
    resume_.set_defaults(run=_resume)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    run: Callable[[argparse.Namespace], int] = args.run
    try:
        _require_sqlite()
        return run(args)
    except BadInput as exc:
        print(f"jobs.py: {exc}", file=sys.stderr)
        return 2
    except Refused as exc:
        print(f"jobs.py: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"jobs.py: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
