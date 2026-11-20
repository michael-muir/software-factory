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

Usage:
    run.py submit [--id ID] [--base REF] [--task TASK] [--open] [-- argv ...]
    run.py send <job> -- argv ...
    run.py close <job>
    run.py status <job> [--json]

Exit codes: 0 done, 1 refused, 2 bad input (arguments, config, unknown job, no git repo).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import secrets
import subprocess
import sys
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

JOB_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,39}", re.ASCII)
TASK_ID = re.compile(r"[A-Za-z0-9._-]+", re.ASCII)  # mirrors state.TASK_ID (E02)
FINISHED = ("succeeded", "failed", "halted")
REQUEST_VERSION = 1
CONFIG_REL = Path(".agentic") / "config.toml"


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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run.py", description="Software Factory runner: jobs in their own git worktrees."
    )
    commands = parser.add_subparsers(dest="command", required=True)

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

    status = commands.add_parser("status", help="print a job's record")
    status.add_argument("job")
    status.add_argument("--json", action="store_true", help="print it as JSON")
    status.set_defaults(run=_status)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    words = list(sys.argv[1:] if argv is None else argv)
    command: list[str] | None = None
    if "--" in words:  # everything after the first -- is the job's command, untouched
        cut = words.index("--")
        words, command = words[:cut], words[cut + 1 :]
    try:
        args = _parser().parse_args(words)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
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
