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
    jobs.py set <job> [--session S] [--title T] [--track T] [--phase P] [--status S]
                [--task TASK] [--branch B] [--worktree PATH]
    jobs.py claim <job> [--session S] [--force] [--json]
    jobs.py beat <job> [--session S] [--json]
    jobs.py release <job> [--session S]

The session is --session, else $FACTORY_SESSION; `claim` generates one if neither is given.
Exit codes: 0 done, 1 refused, 2 bad input (arguments, config, unknown job, no git repo).
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import time
import tomllib
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
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
    listing = _git(cwd, "worktree", "list", "--porcelain")
    first = next((ln for ln in listing.stdout.splitlines() if ln.startswith("worktree ")), "")
    if listing.returncode != 0 or not first:
        raise BadInput("cannot find the repository's main worktree")
    return Repo(main=Path(first[len("worktree ") :]), store=Path(common.stdout.strip()) / "factory")


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
    (
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
)
SCHEMA_VERSION = len(MIGRATIONS)
LIVE_TABLES = ("leases",)  # not derived from files: kept by a rebuild


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


def _migrate(con: sqlite3.Connection, repo: Repo) -> None:
    found = _version(con)
    if found > SCHEMA_VERSION:
        raise IndexTooNew(
            f"{repo.index} has schema version {found}, newer than this tool's {SCHEMA_VERSION}"
        )
    if found == SCHEMA_VERSION:
        return
    with _transaction(con):
        found = _version(con)  # another process may have migrated it meanwhile
        for statements in MIGRATIONS[found:]:
            for statement in statements:
                con.execute(statement)
        con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        _reindex(con, repo)


@contextlib.contextmanager
def _index(repo: Repo) -> Iterator[sqlite3.Connection]:
    """An open, migrated index connection; closed on exit, because Windows holds open files."""
    _require_sqlite()
    repo.store.mkdir(parents=True, exist_ok=True)
    try:
        con = sqlite3.connect(repo.index, timeout=BUSY_TIMEOUT_S, isolation_level=None)
    except sqlite3.Error as exc:
        raise IndexUnavailable(f"index unavailable: {exc}") from exc
    try:
        _migrate(con, repo)
        yield con
    except sqlite3.Error as exc:
        raise IndexUnavailable(f"index unavailable: {exc}") from exc
    finally:
        con.close()


def _put_job(con: sqlite3.Connection, repo: Repo, data: dict[str, Any]) -> None:
    job_id = data["id"]
    con.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    con.execute("DELETE FROM job_tasks WHERE job = ?", (job_id,))
    con.execute("DELETE FROM claims WHERE job = ?", (job_id,))
    con.execute(
        "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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


def _reindex(con: sqlite3.Connection, repo: Repo) -> None:
    """Replace every derived row with what the files say. Leases are kept (ADR 0051)."""
    for table in ("jobs", "job_tasks", "claims", "problems"):
        con.execute(f"DELETE FROM {table}")  # fixed table names, never input
    if repo.work.is_dir():
        for path in sorted(repo.work.glob("*.toml")):
            job_id = path.name[: -len(".toml")]
            if not JOB_ID.fullmatch(job_id):
                continue  # a sidecar
            try:
                _put_job(con, repo, read_job(repo, job_id))
            except BadInput as exc:
                con.execute("INSERT OR REPLACE INTO problems VALUES (?, ?)", (str(path), str(exc)))
    con.execute("DELETE FROM leases WHERE job NOT IN (SELECT id FROM jobs)")


def _index_job(repo: Repo, data: dict[str, Any]) -> None:
    """Write-through for a record written without a lease check: a failure is only a warning."""
    try:
        with _index(repo) as con, _transaction(con):
            _put_job(con, repo, data)
    except (IndexUnavailable, IndexTooNew) as exc:
        _warn(f"the index wasn't updated: {exc}")


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
    moment = time.time()
    with _index(repo) as con:
        lease = _lease(con, args.job)
    shown: dict[str, Any] = dict(data)
    shown["state"] = _state(data, lease, moment)
    shown["lease"] = None if lease is None else lease.as_json()
    shown["sidecars"] = sidecars(repo, args.job)
    if args.json:
        print(json.dumps(_jsonable(shown), indent=2))
    else:
        if shown["lease"] is None:
            del shown["lease"]  # TOML has no null
        sys.stdout.write(dumps(shown))
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
