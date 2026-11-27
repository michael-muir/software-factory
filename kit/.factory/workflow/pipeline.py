#!/usr/bin/env python3
"""Software Factory full-track pipeline (E13, ADRs 0040 to 0044). Standard library only.

    python .factory/workflow/pipeline.py new <job> --epic EPIC (--request-file FILE | --issue N)
    python .factory/workflow/pipeline.py run <job> [--session S]
    python .factory/workflow/pipeline.py approve|reject <job> <checkpoint> --by NAME [--note TEXT]
    python .factory/workflow/pipeline.py resume <job> [--note TEXT] | cancel <job> | status <job>
    python .factory/workflow/pipeline.py check <job> [<stage>]
    python .factory/workflow/pipeline.py check <stage> --worktree PATH --epic EPIC [--task TASK]
        [--base REF] [--gate-report FILE] [--pr-body FILE] [--job JOB]

A full-track job goes through nine stages: spec, design, test, build, gate, review, docs, ship
and learn. `STAGES` is the one table of them: each stage's roles, skills, scope, checkpoint and
the plain-text condition under which it passes. A stage passes only by its check, which reads a
checkout's committed files and history, never what an agent says it did (ADR 0040).

The job is E18's record, `<git-common-dir>/factory/work/<id>.toml`. The pipeline keeps its own
record beside it in the sidecar `work/<id>.pipeline.toml`, and the job's summary in
`work/<id>.summary.toml`. `check` reads them and changes nothing.

Exit codes: 0 the check passed, 1 it failed (or the job isn't ready for it), 2 bad input (a bad
argument, an invalid config, an unknown or damaged job, or not a git repo).
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import decimal
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol

HERE = Path(__file__).resolve().parent
FACTORY = HERE.parent
DOCS_PATH = HERE / "docs.py"
EVIDENCE_PATH = HERE / "evidence.py"
AGENTS_PATH = FACTORY / "agents" / "agents.py"
STATE_PATH = FACTORY / "state" / "state.py"

JOB_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,29}", re.ASCII)
EPIC_ID = re.compile(r"E[0-9]+", re.ASCII)
TASK_ID = re.compile(r"[A-Za-z0-9._-]+", re.ASCII)  # mirrors state.TASK_ID (E02)
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
SHORT = 12

COMMANDS = ("new", "run", "check", "approve", "reject", "resume", "cancel", "status")
STATUSES = (
    "ready",
    "running",
    "awaiting-approval",
    "awaiting-merge",
    "needs-human",
    "cancelled",
    "done",
)
CHECKPOINTS = ("spec", "design", "merge")
FORGES = ("github", "git")
PLACEHOLDERS = ("{role}", "{allowed_tools}", "{prompt}")
SHELLS = ("Bash", "PowerShell")
HANDOFF_HEADINGS = ("## Done", "## Next", "## Open questions")  # mirrors state.HANDOFF_HEADINGS


class BadInput(Exception):
    """A bad argument, config, job or repo: exit 2."""


@dataclass(frozen=True)
class Problem:
    path: str  # the file, folder or commit the problem is about
    where: str  # the stage
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.where}: {self.message}"


# --- sibling modules ----------------------------------------------------------------------------

_LOADED: dict[str, ModuleType] = {}


def _load(path: Path, name: str) -> ModuleType:
    if name in _LOADED:
        return _LOADED[name]
    if not path.is_file():
        raise BadInput(f"pipeline.py needs {path} beside it")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - a .py path always has a loader
        raise BadInput(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses look the module up by name
    spec.loader.exec_module(module)
    _LOADED[name] = module
    return module


def _docs() -> Any:
    """docs.py, which brings state.py with it (as `.state`)."""
    return _load(DOCS_PATH, "factory_pipeline_docs")


def _state() -> Any:
    return _docs().state


def _evidence() -> Any:
    return _load(EVIDENCE_PATH, "factory_pipeline_evidence")


def _agents() -> Any:
    return _load(AGENTS_PATH, "factory_pipeline_agents")


# --- the stage table (ADR 0040) -----------------------------------------------------------------


@dataclass(frozen=True)
class Stage:
    name: str  # one of state.PHASES
    roles: tuple[str, ...]  # its sessions, in order; () when the driver does the work
    skills: tuple[tuple[str, ...], ...]  # the skills of each role, in the same order
    scope: str  # "plan", "slice" or "main"
    checkpoint: str  # "", "spec", "design" or "merge"
    passes: str  # the pass condition, in plain words; {epic} stands for the epic


REVIEWERS = (
    "verifier",
    "spec-reviewer",
    "standards-reviewer",
    "security-reviewer",
    "perf-reviewer",
    "adversary",
)

STAGES: tuple[Stage, ...] = (
    Stage(
        "spec",
        ("spec-writer",),
        (("spec-interview",),),
        "plan",
        "spec",
        "the spec for {epic} is committed in docs/specs, passes docs.py check and has at least "
        "one acceptance criterion.",
    ),
    Stage(
        "design",
        ("architect",),
        (("design-note",),),
        "plan",
        "design",
        "the design note for {epic} is committed in docs/design and passes docs.py check, and "
        "the task files cover every acceptance criterion of the spec, each naming only the "
        "spec's.",
    ),
    Stage(
        "test",
        ("test-designer",),
        (("tdd-slices", "lock-tests"),),
        "slice",
        "",
        "the task's lock record is committed with the failing tests, every acceptance criterion "
        "of the task is tagged in a locked test, and no code is committed before the lock.",
    ),
    Stage(
        "build",
        ("implementer",),
        (("tdd-slices",),),
        "slice",
        "",
        "a commit follows the lock commit, the worktree is clean, and no locked test has changed.",
    ),
    Stage(
        "gate",
        ("debugger",),
        (("debugging",),),
        "slice",
        "",
        "the full gate passes on the branch's head commit, from a clean tree.",
    ),
    Stage(
        "review",
        REVIEWERS,
        (
            ("verify-with-evidence",),
            ("spec-review",),
            ("standards-review",),
            ("threat-check",),
            ("perf-budget",),
            ("adversarial-testing",),
        ),
        "slice",
        "",
        "all six review sessions have run, the task's review round is 1, and no blocker or "
        "major finding is open.",
    ),
    Stage(
        "docs",
        ("docs-writer",),
        ((),),
        "slice",
        "",
        "the branch adds an entry under the Unreleased section of CHANGELOG.md, and the full "
        "gate still passes on the new head.",
    ),
    Stage(
        "ship",
        ("integrator",),
        (("pull-request-evidence",),),
        "slice",
        "merge",
        "the PR body passes docs.py check-pr --strict for the branch's commits, the branch is "
        "pushed, and the PR is open.",
    ),
    Stage("learn", (), (), "main", "", "every task has merged, and the job's summary is written."),
)
STAGE_NAMES = tuple(stage.name for stage in STAGES)


def stage(name: str) -> Stage:
    for found in STAGES:
        if found.name == name:
            return found
    raise ValueError(f"unknown stage {name!r}; the stages are {', '.join(STAGE_NAMES)}")


# --- git ----------------------------------------------------------------------------------------


class GitError(Exception):
    pass


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise GitError(f"cannot run git: {exc}") from None
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def _lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line]


# --- checkouts and the checks -------------------------------------------------------------------


@dataclass(frozen=True)
class Checkout:
    """A worktree at its HEAD, with what a check needs beyond its committed files."""

    root: Path
    epic: str
    task: str = ""
    base: str = ""  # the commit the scope started from; "" means the whole history
    gate_report: Mapping[str, Any] | None = None  # the newest gate JSON report for the task
    pr_body: str | None = None
    pr: str = ""  # the forge's reference for the task's open PR
    reviews: tuple[str, ...] = ()  # review roles whose sessions finished for the task
    tasks: tuple[tuple[str, bool], ...] = ()  # (task, merged) for every task of the job
    summary: Mapping[str, Any] | None = None  # the job's summary sidecar

    def head(self) -> str:
        return _git(self.root, "rev-parse", "HEAD").strip()

    def show(self, rel: str) -> str | None:
        """A file's committed text at HEAD, or None."""
        try:
            return _git(self.root, "show", f"HEAD:{rel}")
        except GitError:
            return None

    def tracked(self, folder: str) -> list[str]:
        return _lines(_git(self.root, "ls-tree", "-r", "--name-only", "HEAD", "--", folder))

    def span(self) -> str:
        return f"{self.base}..HEAD" if self.base else "HEAD"

    def changed(self) -> set[str]:
        """Files that differ between the base and HEAD."""
        old = self.base or EMPTY_TREE
        return set(_lines(_git(self.root, "diff", "--name-only", old, "HEAD")))

    def commits(self) -> list[str]:
        """The commits after the base, oldest first."""
        return _lines(_git(self.root, "rev-list", "--reverse", self.span()))

    def files_of(self, commit: str) -> list[str]:
        parents = _git(self.root, "rev-list", "--parents", "-n", "1", commit).split()[1:]
        old = parents[0] if parents else EMPTY_TREE
        return _lines(_git(self.root, "diff", "--name-only", old, commit))

    def added_in(self, rel: str) -> str | None:
        """The oldest commit after the base that adds `rel`."""
        found = _lines(
            _git(self.root, "log", "--diff-filter=A", "--format=%H", self.span(), "--", rel)
        )
        return found[-1] if found else None


Found = list[tuple[str, str]]  # (path, message), before the stage is attached


def _one_doc(c: Checkout, folder: str, kind: str) -> tuple[Found, str | None]:
    name = re.compile(rf"{re.escape(folder)}/{re.escape(c.epic)}-[^/]+\.md")
    docs = [rel for rel in c.tracked(folder) if name.fullmatch(rel)]
    if not docs:
        return [(f"{folder}/", f"no {kind} {c.epic}-*.md is committed")], None
    if len(docs) > 1:
        return [(f"{folder}/", f"{len(docs)} {kind}s for {c.epic}: {', '.join(docs)}")], None
    return [], docs[0]


def _changed_since_base(c: Checkout, rel: str) -> Found:
    if rel in c.changed():
        return []
    return [(rel, f"not changed since the base {c.base[:SHORT]}")]


def _lint(kind: str, rel: str, text: str, root: Path) -> Found:
    return [(rel, f"{p.where}: {p.message}") for p in _docs().lint(kind, rel, text, root)]


def _check_spec(c: Checkout) -> Found:
    found, rel = _one_doc(c, "docs/specs", "spec")
    if rel is None:
        return found
    found += _changed_since_base(c, rel)
    return found + _lint("spec", rel, c.show(rel) or "", c.root)


def _section(body: str, heading: str) -> str:
    lines = body.split("\n")
    start = next((i for i, line in enumerate(lines) if line.rstrip() == heading), None)
    if start is None:
        return ""
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[start + 1 : end])


AC_RANGE = re.compile(r"AC-(\d\d) to AC-(\d\d)")
AC_ONE = re.compile(r"AC-\d\d[a-z]?")


def task_acs(text: str) -> list[str]:
    """The AC ids a task file names under `## Acceptance criteria`, ranges expanded, in order."""
    section = _section(_state().normalise(text), "## Acceptance criteria")
    named: list[str] = []
    for match in AC_RANGE.finditer(section):
        low, high = int(match.group(1)), int(match.group(2))
        named += [f"AC-{n:02d}" for n in range(low, high + 1)]
    named += AC_ONE.findall(AC_RANGE.sub("", section))
    return list(dict.fromkeys(named))


def _task_problems(rel: str, text: str) -> list[str]:
    """E02's rules for a task file, applied to its committed text."""
    state = _state()
    parsed = state.parse(text)
    if isinstance(parsed, str):
        return [f"front matter: {parsed}"]
    data, body = parsed
    findings = data.pop("findings", [])
    found = list(state.check_fields(rel, data, state.TASK_SCHEMA))
    if isinstance(findings, list) and all(isinstance(item, dict) for item in findings):
        for index, finding in enumerate(findings):
            found += state.check_fields(rel, finding, state.FINDING_SCHEMA, f"findings[{index}].")
    else:
        found.append(state.Problem(rel, "findings", "must be [[findings]] tables"))
    stem = Path(rel).stem
    if isinstance(data.get("id"), str) and data["id"] != stem:
        found.append(state.Problem(rel, "id", f"must match the file name ({stem})"))
    found += state.check_headings(rel, body, state.TASK_HEADINGS)
    return [f"{p.where}: {p.message}" for p in found]


def _spec_acs(c: Checkout) -> tuple[Found, str, list[str]]:
    found, rel = _one_doc(c, "docs/specs", "spec")
    if rel is None:
        return found, "", []
    text = _docs().AC_ID.findall(c.show(rel) or "")
    return [], rel, [ac for ac in text if AC_ONE.fullmatch(ac)]


def _check_design(c: Checkout) -> Found:
    found, rel = _one_doc(c, "docs/design", "design note")
    if rel is not None:
        found += _changed_since_base(c, rel)
        found += _lint("design", rel, c.show(rel) or "", c.root)
    missing, spec_rel, spec_acs = _spec_acs(c)
    found += missing
    name = re.compile(rf"\.agentic/tasks/{re.escape(c.epic)}-T\d+\.md")
    tasks = [t for t in c.tracked(".agentic/tasks") if name.fullmatch(t)]
    if not tasks:
        return [*found, (".agentic/tasks/", f"no {c.epic}-T<n> task file is committed")]
    named: set[str] = set()
    for rel in tasks:
        text = c.show(rel) or ""
        found += [(rel, message) for message in _task_problems(rel, text)]
        acs = task_acs(text)
        if not acs:
            found.append((rel, "names no acceptance criterion"))
        if spec_rel:
            found += [(rel, f"{ac} is not in the spec") for ac in acs if ac not in spec_acs]
        named |= set(acs)
    found += [(spec_rel, f"{ac} is in no task") for ac in spec_acs if ac not in named]
    return found


def _lock_rel(task: str) -> str:
    return f".agentic/locks/{task}.toml"


def _check_test(c: Checkout) -> Found:
    rel = _lock_rel(c.task)
    text = c.show(rel)
    if text is None:
        return [(rel, "the lock record is not committed")]
    found: Found = []
    lock_commit = c.added_in(rel)
    if lock_commit is None:
        found.append((rel, f"not added since the base {c.base[:SHORT]}"))
    try:
        entries = tomllib.loads(text).get("files", [])
    except tomllib.TOMLDecodeError as exc:
        return [*found, (rel, f"invalid TOML: {exc}")]
    paths = [str(e["path"]) for e in entries if isinstance(e, dict) and "path" in e]
    task_text = c.show(f".agentic/tasks/{c.task}.md")
    if task_text is None:
        found.append((f".agentic/tasks/{c.task}.md", "the task file is not committed"))
    else:
        tagged: set[str] = set()
        for path in paths:
            tagged |= set(_evidence().trace_file(path, c.show(path) or "", c.epic).acs)
        found += [
            (rel, f"{c.epic}-{ac} is not tagged in a locked test")
            for ac in task_acs(task_text)
            if ac not in tagged
        ]
    if lock_commit is not None:
        for commit in c.commits():
            code = [f for f in c.files_of(commit) if not f.startswith(".agentic/")]
            if code:
                if commit != lock_commit:
                    message = f"changes {code[0]} before the tests are locked"
                    found.append((commit[:SHORT], f"{message} in {lock_commit[:SHORT]}"))
                break
    return found


def _check_build(c: Checkout) -> Found:
    rel = _lock_rel(c.task)
    lock_commit = c.added_in(rel) if c.show(rel) is not None else None
    found: Found = []
    if lock_commit is None:
        found.append((rel, "no lock record is committed on this branch"))
    elif not _lines(_git(c.root, "rev-list", f"{lock_commit}..HEAD")):
        found.append((lock_commit[:SHORT], "no commit follows the lock commit"))
    dirty = [line[3:] for line in _lines(_git(c.root, "status", "--porcelain"))]
    if dirty:
        found.append((dirty[0], f"uncommitted changes: {', '.join(dirty)}"))
    for line in _agents().verify_locks(c.root):
        found.append((line.split(": ", 1)[0], line))
    return found


GATE = "gate report"


def failed_checks(report: Mapping[str, Any]) -> list[str]:
    """The names of a gate report's failing checks (`<profile> <check>`, as `gate.py --json-out`
    writes them), with `locks` and `docs` when they failed."""
    failed = [
        " ".join(str(part) for part in (ch.get("profile"), ch.get("check", ch.get("name"))) if part)
        for ch in report.get("checks", [])
        if isinstance(ch, dict) and ch.get("status") == "fail"
    ]
    if report.get("locks", {}).get("broken"):
        failed.append("locks")
    if report.get("docs", {}).get("problems"):
        failed.append("docs")
    return failed


def _check_gate(c: Checkout) -> Found:
    report = c.gate_report
    if report is None:
        return [(GATE, f"no gate report for {c.task or 'the task'}")]
    found: Found = []
    verdict = report.get("verdict")
    if verdict != "pass":
        failed = ", ".join(failed_checks(report)) or "no check named"
        found.append((GATE, f"the verdict is {verdict}: {failed}"))
    head = c.head()
    commit = report.get("commit")
    if commit != head:
        found.append((GATE, f"is for {str(commit)[:SHORT]}, not the head {head[:SHORT]}"))
    if report.get("dirty") is not False:
        found.append((GATE, "ran on a tree with uncommitted changes"))
    return found


def _check_review(c: Checkout) -> Found:
    rel = f".agentic/tasks/{c.task}.md"
    found: Found = [
        (rel, f"{role} has not reviewed {c.task}") for role in REVIEWERS if role not in c.reviews
    ]
    text = c.show(rel)
    parsed = _state().parse(text) if text is not None else "the task file is not committed"
    if isinstance(parsed, str):
        return [*found, (rel, parsed)]
    data, _body = parsed
    if data.get("review_round") != 1:
        found.append((rel, f"the review round is {data.get('review_round')}, not 1"))
    findings = data.get("findings", [])
    for finding in findings if isinstance(findings, list) else []:
        if (
            isinstance(finding, dict)
            and finding.get("status") == "open"
            and finding.get("severity") in ("blocker", "major")
        ):
            summary = f"{finding.get('id')} is an open {finding.get('severity')} finding"
            found.append((rel, f"{summary}: {finding.get('summary')}"))
    return found


CHANGELOG = "CHANGELOG.md"
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
UNRELEASED = "## [Unreleased]"


def _unreleased_entry(c: Checkout) -> bool:
    text = c.show(CHANGELOG)
    if text is None:
        return False
    lines = _state().normalise(text).split("\n")
    start = next((i for i, line in enumerate(lines) if line.strip() == UNRELEASED), None)
    if start is None:
        return False
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    diff = _git(c.root, "diff", "-U0", c.base or EMPTY_TREE, "HEAD", "--", CHANGELOG)
    number = 0
    for line in diff.splitlines():
        hunk = HUNK.match(line)
        if hunk:
            number = int(hunk.group(1))
        elif line.startswith("+") and not line.startswith("+++"):
            if start < number - 1 < end and line[1:].strip():
                return True
            number += 1
    return False


def _check_docs(c: Checkout) -> Found:
    found: Found = []
    if not _unreleased_entry(c):
        found.append((CHANGELOG, f"the branch adds no entry under {UNRELEASED}"))
    return found + _check_gate(c)


BODY = "PR body"


def _body_problems(c: Checkout) -> Found:
    """`check-pr --strict --commits <base..HEAD>` on the PR body: the ship check's first part."""
    if c.pr_body is None:
        return [(BODY, "no PR body")]
    docs = _docs()
    commits = c.commits()
    problems = docs.lint_pr(c.pr_body, BODY) + docs.lint_pr_strict(c.pr_body, BODY, c.root, commits)
    return [(p.path, f"{p.where}: {p.message}") for p in problems]


def _check_ship(c: Checkout) -> Found:
    found = _body_problems(c)
    if not c.pr:
        found.append(("PR", "no PR is open for the branch"))
    return found


def _check_learn(c: Checkout) -> Found:
    found: Found = []
    if not c.tasks:
        found.append(("tasks", "the job has no tasks"))
    found += [(task, "is not merged") for task, merged in c.tasks if not merged]
    if c.summary is None:
        found.append(("summary", "the job's summary is not written"))
    else:
        handoff = str(c.summary.get("handoff", ""))
        lines = {line.rstrip() for line in handoff.replace("\r\n", "\n").split("\n")}
        found += [
            ("summary", f"the closing handoff has no {heading} heading")
            for heading in HANDOFF_HEADINGS
            if heading not in lines
        ]
    return found


CHECKS: dict[str, Callable[[Checkout], Found]] = {
    "spec": _check_spec,
    "design": _check_design,
    "test": _check_test,
    "build": _check_build,
    "gate": _check_gate,
    "review": _check_review,
    "docs": _check_docs,
    "ship": _check_ship,
    "learn": _check_learn,
}


def check(name: str, checkout: Checkout) -> list[Problem]:
    """The stage's exit check: one problem per unmet condition; [] when the stage passes."""
    found = stage(name)
    if found.scope == "slice" and not checkout.task:
        raise ValueError(f"the {name} stage checks one task: give its id")
    return [Problem(path, name, message) for path, message in CHECKS[name](checkout)]


# --- sessions (ADR 0042) ------------------------------------------------------------------------


def allowed_tools(tools: Sequence[str], run_scope: Sequence[str]) -> str:
    """A role's Claude Code allow-list, from its neutral tools and its `[scope].run` prefixes."""
    names = _agents().CLAUDE_CODE_AGENT_TOOLS
    rules: list[str] = []
    for tool in tools:
        if tool not in names:
            raise ValueError(f"unknown tool {tool!r}")
        if tool == "run" and run_scope:
            add = [f"{shell}({prefix} *)" for prefix in run_scope for shell in SHELLS]
        else:
            add = list(names[tool])
        rules += [rule for rule in add if rule not in rules]
    return ",".join(dict.fromkeys(rules))


def _role_card(root: Path, role: str) -> dict[str, Any]:
    folder = root / ".factory" / "agents"
    for path in sorted(folder.rglob("*.md")) if folder.is_dir() else []:
        if path.name.startswith("_"):
            continue
        parsed = _state().parse(path.read_text(encoding="utf-8"))
        if not isinstance(parsed, str) and parsed[0].get("name") == role:
            return dict(parsed[0])
    raise ValueError(f"no role card for {role!r} under {folder}")


def role_allowed_tools(root: Path, role: str) -> str:
    """The allow-list for a role, read from its card under `<root>/.factory/agents`."""
    data = _role_card(root, role)
    scope = data.get("scope", {})
    run = scope.get("run", []) if isinstance(scope, dict) else []
    return allowed_tools([str(t) for t in data.get("tools", [])], [str(p) for p in run])


def has_shell(root: Path, role: str) -> bool:
    """Whether the role can run any command, so can commit its own work: `run` in its card's
    tools with no `[scope].run` prefixes."""
    data = _role_card(root, role)
    scope = data.get("scope", {})
    run = scope.get("run", []) if isinstance(scope, dict) else []
    return "run" in [str(t) for t in data.get("tools", [])] and not run


def session_argv(template: Sequence[str], role: str, allowed: str, prompt: str) -> list[str]:
    """The agent command: each whole-element placeholder filled in, so a prompt stays one arg."""
    values = {"{role}": role, "{allowed_tools}": allowed, "{prompt}": prompt}
    return [values.get(item, item) for item in template]


def session_env(role: str, **more: str) -> dict[str, str]:
    """What a session's environment adds, so the E03 hook knows the role, plus the files the
    driver hands it (`FACTORY_GATE_REPORT`, `FACTORY_PR_BODY`)."""
    return {"FACTORY_ROLE": role, **more}


NO_SHELL_LAST_LINE = (
    "Don't commit: the driver commits your files. End with your handoff note as your final "
    "reply, and stop."
)


def prompt(
    name: str,
    role: str,
    *,
    job: str,
    epic: str,
    task: str,
    reads: Sequence[str] = (),
    note: str = "",
    request: str = "",
    extra: Sequence[str] = (),
    shell: bool = True,
) -> str:
    """The stage prompt for one role's session: plain text, the same for the same inputs.
    `extra` lines say what the driver hands this session (a gate report, where the PR body goes).
    A role without a `shell` can't commit, so it ends with its handoff note as its reply instead
    (the product owner's decision of 26 Nov 2026, ADR 0046)."""
    found = stage(name)
    if role not in found.roles:
        raise ValueError(f"{role} has no session in the {name} stage")
    skills = found.skills[found.roles.index(role)]
    lines = [
        f"You are the {role} on job {job}, at the {name} stage of the full track.",
        f"Epic: {epic}. Task: {task}.",
    ]
    if len(skills) == 1:
        lines.append(f"Follow the skill: {skills[0]}.")
    elif skills:
        lines.append(f"Follow the skills: {', '.join(skills)}.")
    if reads:
        lines.append(f"Read: {', '.join(reads)}.")
    lines.append(f"The stage passes when: {found.passes.replace('{epic}', epic)}")
    if note:
        lines.append(f"The last review of this stage said: {note}")
    if request:
        lines.append(f"The request:\n{request.strip()}")
    lines += extra
    if shell:
        lines.append("Work only in this worktree. Commit your work and stop.")
    else:
        lines += ["Work only in this worktree.", NO_SHELL_LAST_LINE]
    return "\n".join(lines)


# --- config (mirrors factory_installer/config_schema.py's [pipeline]) ---------------------------

PIPELINE_DEFAULTS: dict[str, Any] = {
    "checkpoints": ["spec", "merge"],
    "agent_command": [
        "claude",
        "-p",
        "--agent",
        "{role}",
        "--output-format",
        "json",
        "--permission-mode",
        "acceptEdits",
        "--permission-prompts",
        "none",
        "--allowedTools",
        "{allowed_tools}",
        "--",
        "{prompt}",
    ],
    "forge": "github",
    "gate_retries": 2,
}
PLACEHOLDER = re.compile(r"\{[^{}]*\}")


def _strings(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _checkpoints_rule(value: object) -> str | None:
    if not _strings(value):
        return "must be a list of strings"
    assert isinstance(value, list)
    unknown = [item for item in value if item not in CHECKPOINTS]
    if unknown:
        return f"unknown checkpoint(s) {', '.join(unknown)}; valid: {', '.join(CHECKPOINTS)}"
    if len(set(value)) != len(value):
        return "must not repeat a checkpoint"
    if "spec" not in value or "merge" not in value:
        return 'must include "spec" and "merge"'
    return None


def _command_rule(value: object) -> str | None:
    if not _strings(value):
        return "must be a list of strings"
    assert isinstance(value, list)
    if not value:
        return "must not be empty"
    if not all(item.strip() for item in value):
        return "must not contain empty items"
    for item in value:
        if PLACEHOLDER.search(item) and item not in PLACEHOLDERS:
            return f"{item!r}: a placeholder must be a whole item, one of {', '.join(PLACEHOLDERS)}"
    if value.count("{prompt}") != 1:
        return "must contain {prompt} exactly once"
    return None


def _forge_rule(value: object) -> str | None:
    return None if value in FORGES else "must be one of " + ", ".join(f'"{f}"' for f in FORGES)


def _retries_rule(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return "must be an integer"
    return None if 0 <= value <= 5 else "must be at least 0 and at most 5"


PIPELINE_RULES: dict[str, Callable[[object], str | None]] = {
    "checkpoints": _checkpoints_rule,
    "agent_command": _command_rule,
    "forge": _forge_rule,
    "gate_retries": _retries_rule,
}


def config_problems(config: Mapping[str, Any]) -> list[tuple[str, str]]:
    """(dotted key, reason) for each bad `[pipeline]` value in a parsed config."""
    section = config.get("pipeline")
    if section is None:
        return []
    if not isinstance(section, dict):
        return [("pipeline", "must be a table")]
    found: list[tuple[str, str]] = []
    for key, value in section.items():
        rule = PIPELINE_RULES.get(key)
        reason = "unknown key" if rule is None else rule(value)
        if reason is not None:
            found.append((f"pipeline.{key}", reason))
    return found


def pipeline_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """The `[pipeline]` section with defaults filled in. Validate it first."""
    section = config.get("pipeline")
    return {**PIPELINE_DEFAULTS, **(section if isinstance(section, dict) else {})}


# --- the pipeline record (ADR 0041) -------------------------------------------------------------

SCALARS = ("version", "id", "epic", "issue", "status", "reason", "stage", "task", "base")
OPTIONAL = {"request": "", "warnings": []}
TABLES = ("tasks", "runs", "sessions", "gates", "decisions")


def _toml(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")
    if isinstance(value, list):
        return "[" + ", ".join(_toml(item) for item in value) + "]"
    raise TypeError(f"cannot write {value!r} to a pipeline record")


def dump_record(data: Mapping[str, Any]) -> str:
    """The record as TOML: its scalars in a fixed order, then each table's entries."""
    keys = [
        *SCALARS,
        *OPTIONAL,
        *(k for k in data if k not in SCALARS + TABLES and k not in OPTIONAL),
    ]
    lines = [f"{key} = {_toml(data[key])}" for key in keys if key in data]
    for table in TABLES:
        for entry in data.get(table, []):
            lines += ["", f"[[{table}]]"]
            lines += [f"{key} = {_toml(value)}" for key, value in entry.items()]
    return "\n".join(lines) + "\n"


def record_problems(data: Mapping[str, Any]) -> list[str]:
    found: list[str] = []
    for key in SCALARS:
        if key not in data:
            found.append(f"{key}: missing")
    if "version" in data and data["version"] != 1:
        found.append("version: must be 1")
    if "status" in data and data["status"] not in STATUSES:
        found.append(f"status: must be one of {', '.join(STATUSES)}")
    if "stage" in data and data["stage"] not in STAGE_NAMES:
        found.append(f"stage: must be one of {', '.join(STAGE_NAMES)}")
    for key in ("id", "epic", "reason", "task", "base", "request"):
        if key in data and not isinstance(data[key], str):
            found.append(f"{key}: must be a string")
    if "issue" in data and (isinstance(data["issue"], bool) or not isinstance(data["issue"], int)):
        found.append("issue: must be an integer")
    for table in TABLES:
        entries = data.get(table, [])
        if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
            found.append(f"{table}: must be [[{table}]] tables")
    return found


def load_record(text: str) -> dict[str, Any]:
    """Parse and check a record; raises BadInput naming what's wrong."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise BadInput(f"invalid TOML: {exc}") from None
    problems = record_problems(data)
    if problems:
        raise BadInput("; ".join(problems))
    for key, default in OPTIONAL.items():
        data.setdefault(key, type(default)())
    for table in TABLES:
        data.setdefault(table, [])
    return data


# --- the repo, the config and the job -----------------------------------------------------------


def _toplevel(path: Path) -> Path:
    try:
        return Path(_git(path, "rev-parse", "--show-toplevel").strip())
    except (GitError, OSError):
        raise BadInput(f"{path} is not in a git repo") from None


def _main_worktree(root: Path) -> Path:
    listing = _git(root, "worktree", "list", "--porcelain")
    first = next((line for line in listing.splitlines() if line.startswith("worktree ")), None)
    return Path(first[len("worktree ") :]) if first else root


def _factory_dir(root: Path) -> Path:
    common = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    return Path(common) / "factory"


def sidecar_path(root: Path, job: str, name: str) -> Path:
    """E18's sidecar, `<git-common-dir>/factory/work/<id>.<name>.toml`."""
    return _factory_dir(root) / "work" / f"{job}.{name}.toml"


def load_config(root: Path) -> dict[str, Any]:
    """The repo's `.agentic/config.toml` (from its main worktree), checked; {} if there's none."""
    path = _main_worktree(root) / ".agentic" / "config.toml"
    if not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise BadInput(f"{path}: {exc}") from None
    problems = config_problems(data)
    if problems:
        raise BadInput("invalid config: " + "; ".join(f"{k}: {r}" for k, r in problems))
    return data


def read_record(root: Path, job: str) -> dict[str, Any]:
    if not JOB_ID.fullmatch(job):
        raise BadInput(f"{job!r} is not a job id ([a-z0-9][a-z0-9-]{{0,29}})")
    path = sidecar_path(root, job, "pipeline")
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise BadInput(f"unknown job {job}: no {path}") from None
    try:
        return load_record(text)
    except BadInput as exc:
        raise BadInput(f"{path}: {exc}") from None


def _read_summary(root: Path, job: str) -> dict[str, Any] | None:
    path = sidecar_path(root, job, "summary")
    if not path.is_file():
        return None
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise BadInput(f"{path}: invalid TOML: {exc}") from None


def _resolve(root: Path, ref: str) -> str:
    try:
        return _git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").strip()
    except GitError:
        raise BadInput(f"{ref!r} is not a commit in {root}") from None


def _record_facts(record: Mapping[str, Any], task: str) -> dict[str, Any]:
    """What a check needs from the record, beyond the checkout's files."""
    gates = [g for g in record["gates"] if g.get("task") == task]
    report = json.loads(gates[-1]["report"]) if gates and gates[-1].get("report") else None
    entry: dict[str, Any] = next((t for t in record["tasks"] if t.get("id") == task), {})
    reviews = tuple(
        str(s.get("role"))
        for s in record["sessions"]
        if s.get("stage") == "review" and s.get("task") == task and s.get("exit_code") == 0
    )
    tasks = tuple((str(t.get("id")), bool(t.get("merged"))) for t in record["tasks"])
    return {
        "gate_report": report,
        "pr_body": entry.get("pr_body"),
        "pr": str(entry.get("pr", "")),
        "reviews": reviews,
        "tasks": tasks,
    }


# --- errors and the ports to E16 and E18 (ADR 0041) ---------------------------------------------


class Refused(Exception):
    """The command was refused: a live lease held by another session, or the job's state. Exit 1."""


class RunnerError(Exception):
    """E16 refused or failed a command; the job stops for a human."""


RUN_PY = FACTORY / "runner" / "run.py"
JOBS_PY = FACTORY / "control" / "jobs.py"


class Runner(Protocol):
    """E16's command line, one method per command (E16 AC-02 to AC-04, AC-14, AC-16)."""

    def submit(self, job_id: str, base: str, task: str) -> None: ...
    def send(self, job_id: str, argv: Sequence[str]) -> None: ...
    def close(self, job_id: str) -> None: ...
    def status(self, job_id: str) -> dict[str, Any]: ...
    def usage(self, job_id: str, usd: str) -> None: ...
    def cancel(self, job_id: str) -> None: ...


class CliRunner:
    """`run.py` beside this kit, run from the repo's main worktree."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _run(self, *args: str) -> str:
        argv = [sys.executable, str(RUN_PY), *args]
        try:
            done = subprocess.run(
                argv, cwd=self.root, capture_output=True, text=True, encoding="utf-8", check=False
            )
        except OSError as exc:
            raise RunnerError(f"cannot run run.py: {exc}") from None
        if done.returncode != 0:
            message = done.stderr.strip() or done.stdout.strip()
            raise RunnerError(f"run.py {args[0]} exited {done.returncode}: {message}")
        return done.stdout

    def submit(self, job_id: str, base: str, task: str) -> None:
        self._run("submit", "--id", job_id, "--base", base, "--task", task, "--open")

    def send(self, job_id: str, argv: Sequence[str]) -> None:
        self._run("send", job_id, "--", *argv)

    def close(self, job_id: str) -> None:
        self._run("close", job_id)

    def status(self, job_id: str) -> dict[str, Any]:
        data = json.loads(self._run("status", job_id, "--json"))
        return dict(data)

    def usage(self, job_id: str, usd: str) -> None:
        self._run("usage", job_id, "--usd", usd)

    def cancel(self, job_id: str) -> None:
        self._run("cancel", job_id)


def runner_for(root: Path) -> Runner:
    """The runner the driver talks to; tests replace this."""
    return CliRunner(root)


# --- forges (ADR 0043) --------------------------------------------------------------------------


class ForgeError(Exception):
    """The forge refused or failed a call."""


class Forge(Protocol):
    """Where PRs open and merge: one small interface, so other forges can be added."""

    def open(self, branch: str, base: str, title: str, body: str) -> str: ...  # the PR's ref
    def state(self, ref: str, branch: str, base: str, head: str) -> str: ...  # open|merged|closed


class GitHubForge:
    """GitHub's REST API through `gh api`, never GraphQL; owner and repo from origin's URL."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _api(self, path: str, *fields: str) -> dict[str, Any]:
        gh = shutil.which("gh")
        if gh is None:
            raise ForgeError("the github forge needs the gh command")
        try:
            endpoint = f"repos/{_github_repo(self.root)}/{path}"
        except BadInput as exc:
            raise ForgeError(str(exc)) from None
        try:
            done = subprocess.run(
                [gh, "api", endpoint, *fields],
                cwd=self.root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except OSError as exc:
            raise ForgeError(f"cannot run gh: {exc}") from None
        if done.returncode != 0:
            raise ForgeError(f"gh api {endpoint}: {done.stderr.strip() or done.stdout.strip()}")
        try:
            data = json.loads(done.stdout)
        except json.JSONDecodeError:
            raise ForgeError(f"gh api {endpoint} gave no JSON") from None
        if not isinstance(data, dict):
            raise ForgeError(f"gh api {endpoint} gave no JSON object")
        return data

    def open(self, branch: str, base: str, title: str, body: str) -> str:
        with tempfile.TemporaryDirectory(prefix="factory-pr-") as temp:
            path = Path(temp) / "body.md"
            path.write_bytes(body.encode("utf-8"))
            fields = ["-f", f"title={title}", "-f", f"head={branch}", "-f", f"base={base}"]
            data = self._api("pulls", *fields, "-F", f"body=@{path}")
        number = data.get("number")
        if isinstance(number, bool) or not isinstance(number, int):
            raise ForgeError("the new PR has no number")
        return str(number)

    def state(self, ref: str, branch: str, base: str, head: str) -> str:
        data = self._api(f"pulls/{ref}")
        if data.get("merged") is True:
            return "merged"
        return "closed" if data.get("state") == "closed" else "open"


class GitForge:
    """Plain git, for tests and forge-less repos: the pushed branch is the PR."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def open(self, branch: str, base: str, title: str, body: str) -> str:
        return branch

    def state(self, ref: str, branch: str, base: str, head: str) -> str:
        try:
            _git(self.root, "fetch", "-q", "origin")
            listed = _git(self.root, "ls-remote", "--heads", "origin", f"refs/heads/{branch}")
        except GitError as exc:
            raise ForgeError(f"git: {exc}") from None
        try:
            _git(self.root, "merge-base", "--is-ancestor", head, f"origin/{base}")
            return "merged"
        except GitError:
            return "open" if listed.strip() else "closed"


def forge_for(root: Path, name: str) -> Forge:
    """The forge `pipeline.forge` names."""
    return GitHubForge(root) if name == "github" else GitForge(root)


def _jobs() -> Any:
    """E18's jobs.py, by path: its API is a contract E18's tests pin."""
    return _load(JOBS_PY, "factory_pipeline_jobs")


def _session_id(given: str | None) -> str:
    import os
    import socket

    session = given or os.environ.get("FACTORY_SESSION", "")
    if session:
        return session
    host = re.sub(r"[^A-Za-z0-9.-]", "-", socket.gethostname())[:30] or "host"
    return f"pipeline-{host}-{os.getpid()}"


def _now() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- the job, held under E18's lease -------------------------------------------------------------


class Job:
    """One pipeline job: E18's record and lease, and the pipeline sidecar beside it."""

    def __init__(self, root: Path, job_id: str, session: str) -> None:
        self.jobs = _jobs()
        try:
            self.repo = self.jobs.find_repo(root)
            self.jobs_config = self.jobs.load_config(self.repo)
        except self.jobs.BadInput as exc:
            raise BadInput(str(exc)) from None
        self.root = Path(self.repo.main)
        self.id = job_id
        self.session = session
        self.record = read_record(self.root, job_id)
        self.held = False
        self.last_beat = 0.0

    def claim(self) -> None:
        try:
            self.jobs.claim(self.repo, self.jobs_config, self.id, self.session)
        except self.jobs.Refused as exc:
            raise Refused(str(exc)) from None
        except self.jobs.BadInput as exc:
            raise BadInput(str(exc)) from None
        self.held = True
        self.last_beat = time.monotonic()
        self.record = read_record(self.root, self.id)  # what the last holder left

    def beat(self) -> None:
        self.jobs.beat(self.repo, self.jobs_config, self.id, self.session)
        self.last_beat = time.monotonic()

    def beat_if_due(self) -> None:
        if time.monotonic() - self.last_beat >= self.jobs_config.lease_minutes * 60 / 3:
            self.beat()

    def release(self) -> None:
        if self.held:
            self.held = False
            with contextlib.suppress(self.jobs.Refused):
                self.jobs.release(self.repo, self.id, self.session)

    def save(self) -> None:
        """Write the record, renewing the lease first so a long session never loses it."""
        self.beat()
        text = dump_record(self.record)
        self.jobs.write_sidecar(self.repo, self.id, "pipeline", text, self.session)

    def write_summary(self, text: str) -> None:
        """The learn stage's sidecar, `work/<id>.summary.toml`."""
        self.beat()
        self.jobs.write_sidecar(self.repo, self.id, "summary", text, self.session)

    def set_e18(self, **fields: str) -> None:
        current = self.jobs.read_job(self.repo, self.id)
        changed = {k: v for k, v in fields.items() if current.get(k) != v}
        if changed:
            self.beat()
            self.jobs.set_job(self.repo, self.id, self.session, **changed)

    def __enter__(self) -> Job:
        self.claim()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


E18_STATUS = {
    "needs-human": "blocked",
    "awaiting-approval": "blocked",
    "awaiting-merge": "blocked",
    "done": "done",
    "cancelled": "cancelled",
}


# --- the driver (ADR 0041) ----------------------------------------------------------------------

STOP_OK, STOP_HUMAN, GO = 0, 1, -1
DRIVER_ROLES = ("gate", "commit", "round", "push", "relock", "finding")  # the driver's own
SCRATCH = "factory-pipeline"  # in the runner worktree's own git dir: never tracked or dirty


class Driver:
    """Takes a job from where it stands to its next wait point, one recorded action per step."""

    def __init__(self, job: Job, runner: Runner, *, poll: float = 1.0) -> None:
        self.job = job
        self.runner = runner
        self.poll = poll
        self.config = load_config(job.root)
        self.pipeline = pipeline_config(self.config)
        self.forge = forge_for(job.root, str(self.pipeline["forge"]))

    @property
    def rec(self) -> dict[str, Any]:
        return self.job.record

    # -- the loop

    def run(self) -> int:
        status = self.rec["status"]
        if status in ("done", "cancelled"):
            raise Refused(f"job {self.job.id} is {status}")
        if status == "needs-human":
            raise Refused(f"job {self.job.id} needs a human: {self.rec['reason']}")
        if status == "awaiting-approval":
            print(f"{self.job.id}: {status} at the {self.rec['stage']} stage")
            return STOP_OK
        if status == "awaiting-merge":
            code = self._await_merge()
            if code != GO:
                return code
        else:
            self.rec["status"] = "running"
            self.job.save()
            self._sync_e18()
        while True:
            code = self.step()
            if code != GO:
                return code
            self.job.beat_if_due()

    def step(self) -> int:
        current = stage(self.rec["stage"])
        if current.name == "learn":
            return self._learn()
        task = self._task()
        outstanding = self._outstanding()
        if outstanding is not None:
            return self._collect(outstanding)
        sessions = self._sessions(current.name, task)
        relock = self._relock(current, task, sessions)
        if relock is not None:
            return relock
        sessions = [s for s in sessions if not s.get("relock")]
        plan = SLICE_PLANS.get(current.name)
        if plan is None:
            left = self._leftovers(current, task, sessions)
            if left is not None:
                return left
            done = {s["role"] for s in sessions if s.get("exit_code") == 0}
            pending = [role for role in current.roles if role not in done]
            if pending:
                return self._send(current, task, pending[0])
            return self._judge(current, task)
        try:
            run = self._open_run(task) or self._new_run(current, task)
        except _Stop as stop:
            return self._stop(str(stop))
        return plan(self, current, task, run, sessions)

    # -- the parts of a step

    def _task(self) -> str:
        key = "id" if stage(self.rec["stage"]).scope == "plan" else "task"
        return str(self.rec[key])

    def _attempt(self) -> int:
        return int(self.rec.get("attempt", 1))

    def _sessions(self, name: str, task: str) -> list[dict[str, Any]]:
        return [
            s
            for s in self.rec["sessions"]
            if s.get("stage") == name
            and s.get("task") == task
            and s.get("attempt", 1) == self._attempt()
        ]

    def _outstanding(self) -> dict[str, Any] | None:
        sessions = self.rec["sessions"]
        if sessions and "exit_code" not in sessions[-1]:
            return dict(sessions[-1])
        return None

    def _open_run(self, task: str) -> dict[str, Any] | None:
        runs = [r for r in self.rec["runs"] if r.get("task") == task]
        return runs[-1] if runs and not runs[-1].get("closed") else None

    def _new_run(self, current: Stage, task: str) -> dict[str, Any]:
        same = [r for r in self.rec["runs"] if r.get("task") == task]
        plan = [r for r in self.rec["runs"] if r.get("task") == self.rec["id"]]
        if same:
            base = f"factory/{same[-1]['id']}"
        elif current.scope == "slice" and plan and self._task_number(task) == 1:
            base = f"factory/{plan[-1]['id']}"
        else:
            base = self._origin_base()
        if current.scope == "plan":
            run_id = f"{self.job.id}-p{len(same) + 1}"
        else:
            run_id = f"{self.job.id}-t{self._task_number(task)}-{len(same) + 1}"
        try:
            self.runner.submit(run_id, base, task)
            status = self.runner.status(run_id)
        except RunnerError as exc:
            raise _Stop(str(exc)) from None
        run = {
            "id": run_id,
            "task": task,
            "base": base,
            "stages": [current.name],
            "branch": str(status.get("branch", f"factory/{run_id}")),
            "worktree": str(status.get("worktree", "")),
            "closed": False,
        }
        self.rec["runs"].append(run)
        self.job.save()
        self._sync_e18()
        return run

    def _task_number(self, task: str) -> int:
        match = re.search(r"-T(\d+)$", task)
        return int(match.group(1)) if match else 0

    def _base_ref(self) -> str:
        return str(self.config.get("gates", {}).get("base_ref", self.rec["base"]) or "main")

    def _origin_base(self) -> str:
        ref = self._base_ref()
        try:
            _resolve(self.job.root, f"origin/{ref}")
            return f"origin/{ref}"
        except BadInput:
            return ref

    def _reads(self, current: Stage, task: str, worktree: Path) -> list[str]:
        found = [
            str(p.relative_to(worktree).as_posix())
            for p in sorted((worktree / "docs" / "specs").glob(f"{self.rec['epic']}-*.md"))
        ]
        design = sorted((worktree / "docs" / "design").glob(f"{self.rec['epic']}-*.md"))
        if current.name == "spec":
            return [".factory/workflow/templates/spec.md"]
        if current.name == "design":
            return [*found, ".factory/workflow/templates/design.md"]
        found += [str(p.relative_to(worktree).as_posix()) for p in design]
        return [*found, f".agentic/tasks/{task}.md"]

    def _note(self, name: str, task: str) -> str:
        for decision in reversed(self.rec["decisions"]):
            if (
                decision.get("checkpoint") == name
                and decision.get("task", task) == task
                and decision.get("attempt") == self._attempt()
                and decision.get("verdict") in ("reject", "resume")
            ):
                return str(decision.get("note", ""))
        return ""

    def _send(
        self,
        current: Stage,
        task: str,
        role: str,
        *,
        env: Mapping[str, str] | None = None,
        extra: Sequence[str] = (),
    ) -> int:
        """Send one role's session, as the role, with its allow-list and the stage prompt."""
        try:
            run = self._open_run(task) or self._new_run(current, task)
        except _Stop as stop:
            return self._stop(str(stop))
        worktree = Path(run["worktree"])
        text = prompt(
            current.name,
            role,
            job=self.job.id,
            epic=self.rec["epic"],
            task=task,
            reads=self._reads(current, task, worktree),
            note=self._note(current.name, task),
            request=self.rec["request"] if current.name == "spec" else "",
            extra=extra,
            shell=has_shell(self.job.root, role),
        )
        allowed = role_allowed_tools(self.job.root, role)
        argv = session_argv(self.pipeline["agent_command"], role, allowed, text)
        pairs = [f"{k}={v}" for k, v in session_env(role, **(env or {})).items()]
        wrapped = [sys.executable, str(Path(__file__).resolve()), "_env", *pairs, "--", *argv]
        return self._command(current, task, run, role, wrapped)

    def _command(
        self,
        current: Stage,
        task: str,
        run: dict[str, Any],
        role: str,
        argv: Sequence[str],
        **more: str,
    ) -> int:
        """Write the command down, then send it on the runner job (so a crash never sends it
        twice). `role` is the session's role, or one of DRIVER_ROLES."""
        if current.name not in run["stages"]:
            run["stages"].append(current.name)
        try:
            index = len(self.runner.status(run["id"]).get("commands", [])) + 1
        except RunnerError as exc:
            return self._stop(str(exc))
        self.rec["sessions"].append(
            {
                "run": run["id"],
                "index": index,
                "stage": current.name,
                "task": task,
                "role": role,
                "attempt": self._attempt(),
                "sent": _now(),
                "argv": list(argv),
                **more,
            }
        )
        self.job.save()  # written down before it's sent
        return self._dispatch(self.rec["sessions"][-1])

    def _dispatch(self, session: dict[str, Any]) -> int:
        try:
            self.runner.send(session["run"], session["argv"])
        except RunnerError as exc:
            self.rec["sessions"][-1]["exit_code"] = -1
            self.rec["sessions"][-1]["finished"] = _now()
            return self._stop(
                f"{session['stage']}: the runner refused the {session['role']} session: {exc}"
            )
        return GO

    def _collect(self, session: dict[str, Any]) -> int:
        try:
            status = self.runner.status(session["run"])
        except RunnerError as exc:
            return self._stop(str(exc))
        commands = status.get("commands", [])
        if len(commands) < session["index"]:
            return self._dispatch(session)  # recorded, never sent: a crash in between
        ran = commands[session["index"] - 1]
        if ran.get("exit_code") is None:
            if status.get("status") in ("halted", "failed"):
                self._finish(session, -1)
                return self._stop(_halted(session, status))
            time.sleep(self.poll)
            return GO
        code = int(ran["exit_code"])
        ours = session["role"] in DRIVER_ROLES
        self._finish(session, code, None if ours else Path(str(ran.get("log", ""))))
        if status.get("status") in ("halted", "failed"):
            return self._stop(_halted(session, status))
        if session["role"] == "gate":
            problem = self._take_report(session, code)
            return GO if problem is None else self._stop(problem)
        if code != 0:
            what = "command" if ours else "session"
            return self._stop(f"{session['stage']}: the {session['role']} {what} exited {code}")
        return GO

    def _finish(self, session: dict[str, Any], code: int, log: Path | None = None) -> None:
        entry = self.rec["sessions"][-1]
        entry["exit_code"] = code
        entry["finished"] = _now()
        usd = _cost(log) if log is not None else None
        if usd is None:
            if log is not None:
                where = f"{session['run']}#{session['index']}"
                self.rec["warnings"].append(
                    f"no cost reported by the {session['role']} session {where}"
                )
        else:
            try:
                self.runner.usage(session["run"], usd)
            except RunnerError as exc:
                self.rec["warnings"].append(f"cost {usd} not reported to the runner: {exc}")
            entry["usd"] = usd
        self.job.save()

    def _checkout(self, task: str, run: Mapping[str, Any], **facts: Any) -> Checkout:
        root = Path(run["worktree"])
        runs = [r for r in self.rec["runs"] if r.get("task") == task]
        base = _resolve(root, runs[0]["base"])
        found = {**_record_facts(self.rec, task), **facts}
        return Checkout(root=root, epic=self.rec["epic"], task=task, base=base, **found)

    def _judge(self, current: Stage, task: str) -> int:
        run = self._open_run(task)
        if run is None:
            return self._stop(f"{current.name}: no runner job is open for {task}")
        checkout = self._checkout(task, run)
        problems = check(current.name, checkout)
        if problems:
            return self._stop("; ".join(str(p) for p in problems))
        if current.name == "design":
            self._take_tasks(checkout)
        if current.checkpoint and current.checkpoint in self.pipeline["checkpoints"]:
            self._close(run)
            self.rec["status"] = (
                "awaiting-merge" if current.checkpoint == "merge" else "awaiting-approval"
            )
            self.job.save()
            self._sync_e18()
            print(f"{self.job.id}: {self.rec['status']} at the {current.name} stage")
            return STOP_OK
        self._advance()
        return GO

    def _take_tasks(self, checkout: Checkout) -> None:
        name = re.compile(rf"\.agentic/tasks/{re.escape(self.rec['epic'])}-T(\d+)\.md")
        found = sorted(
            (int(m.group(1)), Path(rel).stem)
            for rel in checkout.tracked(".agentic/tasks")
            if (m := name.fullmatch(rel))
        )
        known = {t.get("id") for t in self.rec["tasks"]}
        for _, task in found:
            if task not in known:
                self.rec["tasks"].append({"id": task, "branch": "", "pr": "", "merged": False})
        self.job.save()

    def _entry(self, task: str) -> dict[str, Any]:
        for entry in self.rec["tasks"]:
            if entry.get("id") == task:
                return dict_of(entry)
        raise _Stop(f"{task} is not one of the job's tasks")

    def _advance(self) -> None:
        """Move to the next stage (spec AC-05: the only way forward). After a merge, the next
        unmerged task starts at the test stage; after the last, the job goes on to learn."""
        old = stage(self.rec["stage"])
        index = STAGE_NAMES.index(old.name)
        nxt = STAGES[index + 1]
        if old.scope == "plan" and nxt.scope == "slice":
            run = self._open_run(self.rec["id"])
            if run is not None:
                self._close(run)
            if not self.rec["tasks"]:
                raise _Stop("design: the design made no tasks")
            self.rec["task"] = self.rec["tasks"][0]["id"]
        if old.name == "ship":
            left = [t for t in self.rec["tasks"] if not t.get("merged")]
            if left:
                self.rec["task"] = left[0]["id"]
                nxt = stage("test")
        self.rec["stage"] = nxt.name
        self.rec["attempt"] = 1
        self.job.save()
        self._sync_e18()

    def _close(self, run: dict[str, Any]) -> None:
        if run.get("closed"):
            return
        run["closed"] = True
        try:
            self.runner.close(run["id"])
        except RunnerError as exc:
            self.rec["warnings"].append(f"closing runner job {run['id']}: {exc}")
        self.job.save()

    def _stop(self, reason: str) -> int:
        """Stop for a human: record why, end the open runner job, and mark the E18 job blocked."""
        run = self._open_run(self._task())
        if run is not None:
            self._close(run)
        self.rec["status"] = "needs-human"
        self.rec["reason"] = reason
        self.job.save()
        self._sync_e18()
        print(f"{self.job.id}: needs a human: {reason}", file=sys.stderr)
        return STOP_HUMAN

    def _sync_e18(self) -> None:
        fields = {
            "phase": self.rec["stage"],
            "status": E18_STATUS.get(self.rec["status"], "open"),
        }
        if self.rec["task"] != self.rec["id"] or stage(self.rec["stage"]).scope == "plan":
            fields["task"] = self.rec["task"]
        run = next((r for r in reversed(self.rec["runs"]) if r.get("task") == self._task()), None)
        if run is not None:
            fields["branch"] = str(run["branch"])
            fields["worktree"] = str(run["worktree"])
        self.job.set_e18(**fields)

    # -- the slice stages the driver takes part in (spec AC-12 to AC-16)

    def _commit_argv(self, message: str, paths: Sequence[str]) -> list[str]:
        return [sys.executable, str(Path(__file__).resolve()), "_commit", message, "--", *paths]

    def _leftovers(self, current: Stage, task: str, sessions: list[dict[str, Any]]) -> int | None:
        """Commit what a role without a shell left in the tree (the product owner's decision of
        23 Nov 2026), once, right after its session. None when there's nothing to commit."""
        if not sessions:
            return None
        last = sessions[-1]
        role = str(last["role"])
        if role in DRIVER_ROLES and role != "commit":
            return None
        if role != "commit" and (last.get("exit_code") != 0 or has_shell(self.job.root, role)):
            return None
        run = self._open_run(task)
        if run is None or not _dirty(Path(run["worktree"])):
            return None
        if role == "commit":
            return self._stop(f"{current.name}: the tree is still dirty after the driver's commit")
        scope = self.rec["epic"] if current.scope == "plan" else task
        message = f"docs({scope}): {current.name} from the {role}"
        return self._command(current, task, run, "commit", self._commit_argv(message, ["."]))

    def _gate_command(self, current: Stage, task: str, run: dict[str, Any]) -> int:
        """The full gate, as a runner command, with its JSON report in the scratch folder."""
        n = sum(1 for s in self.rec["sessions"] if s.get("role") == "gate") + 1
        out = _scratch(Path(run["worktree"])) / f"gate-{n}.json"
        python = [str(item) for item in self.config.get("gates", {}).get("python_command", [])]
        argv = [*(python or ["python"]), ".factory/gates/gate.py", "--json-out", str(out)]
        return self._command(current, task, run, "gate", argv, out=str(out))

    def _take_report(self, session: Mapping[str, Any], code: int) -> str | None:
        """Read a finished gate's JSON report into the record; a problem if there is none."""
        out = Path(str(session.get("out", "")))
        try:
            report = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            report = None
        if not isinstance(report, dict) or "verdict" not in report:
            return f"gate: the gate (exit {code}) wrote no JSON report to {out}"
        self.rec["gates"].append(
            {
                "task": session["task"],
                "commit": str(report.get("commit", "")),
                "verdict": str(report["verdict"]),
                "run": session["run"],
                "index": session["index"],
                "report": json.dumps(report),
            }
        )
        self.job.save()
        return None

    def _latest_gate(self, task: str) -> dict[str, Any] | None:
        gates = [g for g in self.rec["gates"] if g.get("task") == task]
        return gates[-1] if gates else None

    def _hand_report(self, task: str, run: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
        """Put the task's newest gate report in the worktree's scratch folder for a session."""
        latest = self._latest_gate(task)
        if latest is None:
            raise _Stop(f"{self.rec['stage']}: no gate report for {task}")
        path = _scratch(Path(run["worktree"])) / "gate-report.json"
        path.write_text(str(latest["report"]), encoding="utf-8")
        return path, dict(json.loads(str(latest["report"])))

    def _gate(
        self, current: Stage, task: str, run: dict[str, Any], sessions: list[dict[str, Any]]
    ) -> int:
        """Gate, then the Debugger and the gate again on red, up to `gate_retries` times. A new
        open blocker finding after a Debugger session stops for a human (ADR 0047)."""
        last = sessions[-1]["role"] if sessions else ""
        if last in ("debugger", "commit"):
            asked = self._new_blockers(task, run)
            if asked:
                rel = f".agentic/tasks/{task}.md"
                if last == "debugger" and _dirty(Path(run["worktree"]), rel):
                    argv = self._commit_argv(
                        f"chore({task}): the debugger's blocker findings", [rel]
                    )
                    return self._command(current, task, run, "commit", argv)
                debugger = [s for s in sessions if s["role"] == "debugger"][-1]
                debugger["blockers"] = [str(f.get("id")) for f in asked]
                listed = "; ".join(f"{f.get('id')} [blocker] {f.get('summary')}" for f in asked)
                return self._stop(f"gate: the debugger needs a human: {listed}")
        if last != "gate":
            return self._gate_command(current, task, run)
        latest = self._latest_gate(task)
        if latest is not None and latest.get("verdict") == "pass":
            return self._judge(current, task)
        debugged = sum(1 for s in sessions if s["role"] == "debugger")
        if debugged >= int(self.pipeline["gate_retries"]):
            return self._judge(current, task)
        try:
            path, report = self._hand_report(task, run)
        except _Stop as stop:
            return self._stop(str(stop))
        failed = ", ".join(failed_checks(report)) or "no check named"
        commit = str(report.get("commit", ""))[:SHORT]
        line = (
            f"The full gate failed on {commit}: {failed}. Its JSON report is {path} "
            "($FACTORY_GATE_REPORT). Fix the cause, commit, and stop: the driver runs the gate "
            "again."
        )
        env = {"FACTORY_GATE_REPORT": str(path)}
        return self._send(current, task, "debugger", env=env, extra=[line])

    def _new_blockers(self, task: str, run: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Open blocker findings in the worktree's task file that the gated commit didn't have."""
        rel = f".agentic/tasks/{task}.md"
        try:
            after = (Path(run["worktree"]) / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []
        latest = self._latest_gate(task)
        before = ""
        if latest is not None and latest.get("commit"):
            try:
                before = _git(Path(run["worktree"]), "show", f"{latest['commit']}:{rel}")
            except GitError:
                before = ""
        known = {f.get("id") for f in _open_blockers(before)}
        return [f for f in _open_blockers(after) if f.get("id") not in known]

    # -- a relock the product owner approved (spec AC-23, ADR 0047)

    def _relock_decision(self, task: str) -> dict[str, Any] | None:
        for decision in reversed(self.rec["decisions"]):
            if decision.get("attempt") == self._attempt() and decision.get("task", task) == task:
                return decision if decision.get("checkpoint") == "relock" else None
        return None

    def _relock(self, current: Stage, task: str, sessions: list[dict[str, Any]]) -> int | None:
        """Carry out an approved relock before the stopped stage reruns: check that only the
        approved files' hashes changed, `agents.py lock --replace` every locked file plus the
        approved ones, mark the Debugger's blocker findings fixed, and commit. None once done,
        or when no relock was approved for this attempt."""
        decision = None if current.scope != "slice" else self._relock_decision(task)
        if decision is None:
            return None
        steps = {str(s["relock"]) for s in sessions if s.get("relock") and s.get("exit_code") == 0}
        if "commit" in steps:
            return None
        try:
            run = self._open_run(task) or self._new_run(current, task)
        except _Stop as stop:
            return self._stop(str(stop))
        root = Path(run["worktree"])
        lock_task, by = str(decision["lock_task"]), str(decision["by"])
        rel = _lock_rel(lock_task)
        if "lock" not in steps:
            try:
                files = _relock_files(root, lock_task, [str(f) for f in decision["files"]])
            except _Stop as stop:
                return self._stop(f"relock: {stop}")
            argv = [sys.executable, str(AGENTS_PATH), "lock", "--replace", lock_task, *files]
            argv += ["--approved-by", by]
            return self._command(current, task, run, "relock", argv, relock="lock")
        findings = [str(f) for f in decision.get("findings", [])]
        for fid in findings:
            if f"finding:{fid}" not in steps:
                argv = [sys.executable, str(STATE_PATH), "finding", "set", task, fid]
                argv += ["--status", "fixed"]
                return self._command(current, task, run, "finding", argv, relock=f"finding:{fid}")
        paths = [rel, *([f".agentic/tasks/{task}.md"] if findings else [])]
        argv = self._commit_argv(f"test({lock_task}): relock approved by {by}", paths)
        return self._command(current, task, run, "commit", argv, relock="commit")

    def _review(
        self, current: Stage, task: str, run: dict[str, Any], sessions: list[dict[str, Any]]
    ) -> int:
        """The Verifier and the five reviewers, each in its own session; the driver commits the
        task file's findings after each, then sets the review round to 1."""
        root = Path(run["worktree"])
        rel = f".agentic/tasks/{task}.md"
        try:
            handoff = self._reviewer_handoff(task, run, sessions)
        except _Stop as stop:
            return self._stop(str(stop))
        if handoff is not None:
            return self._command(current, task, run, "commit", handoff)
        if _dirty(root, rel):
            last = sessions[-1]["role"] if sessions else ""
            if last == "commit":
                return self._stop(f"review: {rel} is still uncommitted after the findings commit")
            what = {"round": "review round 1", "": "the task file before review"}.get(
                last, f"review findings from {last}"
            )
            argv = self._commit_argv(f"chore({task}): {what}", [rel])
            return self._command(current, task, run, "commit", argv)
        done = {s["role"] for s in sessions if s.get("exit_code") == 0}
        pending = [role for role in REVIEWERS if role not in done]
        if pending:
            try:
                report, _ = self._hand_report(task, run)
            except _Stop as stop:
                return self._stop(str(stop))
            env = {"FACTORY_GATE_REPORT": str(report)}
            return self._send(
                current, task, pending[0], env=env, extra=[_review_line(pending[0], report)]
            )
        if _review_round(root / rel) != 1 and "round" not in done:
            argv = [sys.executable, str(STATE_PATH), "task", "set", task, "--round", "1"]
            return self._command(current, task, run, "round", argv)
        self._keep_findings(root, task)
        return self._judge(current, task)

    def _reviewer_handoff(
        self, task: str, run: Mapping[str, Any], sessions: list[dict[str, Any]]
    ) -> list[str] | None:
        """After a reviewer without a shell: its reply, recorded as its handoff and committed
        with the findings (ADR 0046). None when there's nothing to record; a reply without the
        three headings adds a warning instead. The session's entry says which, so a second
        step never records it twice."""
        last = sessions[-1] if sessions else {}
        role = str(last.get("role", ""))
        if role not in REVIEWERS or last.get("exit_code") != 0 or "handoff" in last:
            return None
        if has_shell(self.job.root, role):
            return None
        try:
            commands = self.runner.status(str(run["id"])).get("commands", [])
        except RunnerError as exc:
            raise _Stop(str(exc)) from None
        log = commands[int(last["index"]) - 1].get("log", "") if commands else ""
        text = session_reply(Path(str(log))) if log else ""
        missing = _state().check_headings("reply", text, _state().HANDOFF_HEADINGS)
        if not text.strip() or missing:
            last["handoff"] = "missing"
            where = f"{last['run']}#{last['index']}"
            lacks = ", ".join(p.where for p in missing) or "any text"
            self.rec["warnings"].append(
                f"no handoff from the {role} session {where}: its reply lacks {lacks}"
            )
            self.job.save()
            return None
        last["handoff"] = "recorded"  # saved with the command that records it
        root = Path(str(run["worktree"]))
        body = _scratch(root) / f"handoff-{role}.md"
        body.write_bytes(text.encode("utf-8"))
        rel = f".agentic/tasks/{task}.md"
        what = "review findings and handoff" if _dirty(root, rel) else "handoff"
        message = f"chore({task}): {what} from {role}"
        here = str(Path(__file__).resolve())
        return [sys.executable, here, "_handoff", task, role, str(body), message]

    def _keep_findings(self, root: Path, task: str) -> None:
        """The task's committed findings, kept in the record for the job's summary."""
        try:
            text = _git(root, "show", f"HEAD:.agentic/tasks/{task}.md")
        except GitError:
            return
        parsed = _state().parse(text)
        findings = [] if isinstance(parsed, str) else parsed[0].get("findings", [])
        kept = [
            {str(k): str(v) for k, v in f.items()}
            for f in (findings if isinstance(findings, list) else [])
            if isinstance(f, dict)
        ]
        self._entry(task)["findings"] = json.dumps(kept)
        self.job.save()

    def _docs(
        self, current: Stage, task: str, run: dict[str, Any], sessions: list[dict[str, Any]]
    ) -> int:
        """The docs-writer's entry (committed by the driver: the role has no shell), then the
        full gate again on the new head."""
        root = Path(run["worktree"])
        done = {s["role"] for s in sessions if s.get("exit_code") == 0}
        if "docs-writer" not in done:
            return self._send(current, task, "docs-writer")
        if _dirty(root):
            if sessions[-1]["role"] == "commit":
                return self._stop("docs: the tree is still dirty after the docs commit")
            argv = self._commit_argv(f"docs({task}): changelog entry from the docs-writer", ["."])
            return self._command(current, task, run, "commit", argv)
        latest = self._latest_gate(task)
        head = _git(root, "rev-parse", "HEAD").strip()
        gated = any(s["role"] == "gate" for s in sessions)
        if not gated and (latest is None or latest.get("commit") != head):
            return self._gate_command(current, task, run)
        return self._judge(current, task)

    def _ship(
        self, current: Stage, task: str, run: dict[str, Any], sessions: list[dict[str, Any]]
    ) -> int:
        """The Integrator's body, `check-pr --strict`, the push, then the forge opens the PR."""
        root = Path(run["worktree"])
        done = {s["role"] for s in sessions if s.get("exit_code") == 0}
        body_path = _scratch(root) / "pr-body.md"
        branch = f"factory/{self.job.id}-t{self._task_number(task)}"
        try:
            entry = self._entry(task)
            if "integrator" not in done:
                report, _ = self._hand_report(task, run)
                body_path.unlink(missing_ok=True)
                env = {"FACTORY_PR_BODY": str(body_path), "FACTORY_GATE_REPORT": str(report)}
                line = (
                    f"Write the filled-in PR body to {body_path} ($FACTORY_PR_BODY), drafted "
                    f"from the gate report {report} ($FACTORY_GATE_REPORT). Don't push or open "
                    "the PR: the driver does, once the body passes check-pr --strict."
                )
                return self._send(current, task, "integrator", env=env, extra=[line])
            if "push" not in done:
                return self._check_and_push(current, task, run, entry, body_path, branch)
        except _Stop as stop:
            return self._stop(str(stop))
        if entry.get("opened") != self._attempt():
            body = str(entry.get("pr_body", ""))
            try:
                ref = self.forge.open(branch, self._base_ref(), pr_title(body), body)
            except ForgeError as exc:
                return self._stop(f"ship: the forge didn't open the PR: {exc}")
            head = _git(root, "rev-parse", "HEAD").strip()
            entry.update(pr=ref, branch=branch, head=head, opened=self._attempt(), merged=False)
            self.job.save()
        return self._judge(current, task)

    def _check_and_push(
        self,
        current: Stage,
        task: str,
        run: dict[str, Any],
        entry: dict[str, Any],
        body_path: Path,
        branch: str,
    ) -> int:
        try:
            body = body_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return self._stop(f"ship: {BODY}: the integrator wrote none to {body_path}")
        entry["pr_body"] = body
        self.job.save()
        checkout = self._checkout(task, run, pr_body=body)
        problems = [Problem(path, "ship", message) for path, message in _body_problems(checkout)]
        if problems:
            return self._stop("; ".join(str(p) for p in problems))
        argv = ["git", "push", "origin", f"HEAD:refs/heads/{branch}"]
        return self._command(current, task, run, "push", argv)

    def _await_merge(self) -> int:
        """`run` at the merge checkpoint: nothing changes until a human has merged the PR."""
        task = self._task()
        try:
            entry = self._entry(task)
        except _Stop as stop:
            return self._stop(str(stop))
        ref = str(entry.get("pr", ""))
        try:
            state = self.forge.state(
                ref, str(entry.get("branch", "")), self._base_ref(), str(entry.get("head", ""))
            )
        except ForgeError as exc:
            print(f"{self.job.id}: can't read the PR {ref}: {exc}", file=sys.stderr)
            return STOP_HUMAN
        if state == "open":
            print(f"{self.job.id}: awaiting-merge of {ref} for {task}")
            return STOP_OK
        self.rec["status"] = "running"
        if state != "merged":
            return self._stop(f"ship: the PR {ref} for {task} was closed without merging")
        entry["merged"] = True
        try:
            _git(self.job.root, "fetch", "-q", "origin")
        except GitError as exc:
            return self._stop(f"ship: {task} merged, but git fetch origin failed: {exc}")
        self._advance()
        return GO

    # -- learn (spec AC-17)

    def _learn(self) -> int:
        summary = self._summary()
        self.job.write_summary(dump_tables(summary, SUMMARY_TABLES))
        tasks = tuple((str(t.get("id")), bool(t.get("merged"))) for t in self.rec["tasks"])
        checkout = Checkout(root=self.job.root, epic=self.rec["epic"], tasks=tasks, summary=summary)
        problems = check("learn", checkout)
        if problems:
            return self._stop("; ".join(str(p) for p in problems))
        self.rec["status"], self.rec["reason"] = "done", ""
        self.job.save()
        self._sync_e18()
        print(f"{self.job.id}: done")
        return STOP_OK

    def _summary(self) -> dict[str, Any]:
        rec = self.rec
        total = sum(
            (decimal.Decimal(str(s.get("usd", "0"))) for s in rec["sessions"]),
            start=decimal.Decimal(0),
        )
        findings = [
            {"task": str(t.get("id")), **finding}
            for t in rec["tasks"]
            for finding in json.loads(str(t.get("findings") or "[]"))
        ]
        prs = [
            {
                "task": str(t.get("id")),
                "pr": str(t.get("pr", "")),
                "branch": str(t.get("branch", "")),
                "merged": bool(t.get("merged")),
            }
            for t in rec["tasks"]
        ]
        gates = [
            {
                "task": str(g.get("task")),
                "commit": str(g.get("commit")),
                "verdict": str(g.get("verdict")),
            }
            for g in rec["gates"]
        ]
        title = str(self.job.jobs.read_job(self.job.repo, self.job.id).get("title", ""))
        usd = str(total.normalize()) if total else "0"
        return {
            "version": 1,
            "job": rec["id"],
            "epic": rec["epic"],
            "issue": rec["issue"],
            "title": title,
            "status": "done",
            "finished": _now(),
            "total_usd": usd,
            "handoff": _closing_handoff(rec, title, usd, prs, findings),
            "stages": _stages(rec),
            "gates": gates,
            "findings": findings,
            "prs": prs,
        }


SLICE_PLANS: dict[str, Callable[..., int]] = {
    "gate": Driver._gate,
    "review": Driver._review,
    "docs": Driver._docs,
    "ship": Driver._ship,
}
SUMMARY_TABLES = ("stages", "gates", "findings", "prs")


def _open_blockers(text: str) -> list[dict[str, Any]]:
    """The open blocker findings in a task file's text; none when it doesn't parse."""
    parsed = _state().parse(text) if text else "empty"
    findings = [] if isinstance(parsed, str) else parsed[0].get("findings", [])
    return [
        dict(f)
        for f in (findings if isinstance(findings, list) else [])
        if isinstance(f, dict) and f.get("status") == "open" and f.get("severity") == "blocker"
    ]


def _locked_files(text: str) -> dict[str, str]:
    """A lock record's files and their hashes, in the record's order."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise _Stop(f"the lock record is not valid TOML: {exc}") from None
    files = data.get("files", [])
    return {
        str(f.get("path")): str(f.get("sha256"))
        for f in (files if isinstance(files, list) else [])
        if isinstance(f, dict)
    }


def _changed_locked(read: Callable[[str], bytes | None], locked: Mapping[str, str]) -> list[str]:
    """The locked files whose hash no longer matches (or that are gone); `read(rel)` gives a
    file's bytes, or None."""
    sha = _agents().lf_sha256
    return [rel for rel, want in locked.items() if (data := read(rel)) is None or sha(data) != want]


def _relock_files(root: Path, lock_task: str, approved: Sequence[str]) -> list[str]:
    """Every file in the committed lock record, then the approved files it doesn't hold. Stops
    when a file that isn't approved has a new hash in the worktree."""
    try:
        text = _git(root, "show", f"HEAD:{_lock_rel(lock_task)}")
    except GitError:
        raise _Stop(f"{_lock_rel(lock_task)} is not committed") from None
    locked = _locked_files(text)

    def read(rel: str) -> bytes | None:
        try:
            return (root / rel).read_bytes()
        except OSError:
            return None

    others = [rel for rel in _changed_locked(read, locked) if rel not in approved]
    if others:
        raise _Stop(f"{', '.join(others)} changed but the relock didn't approve it")
    return [*locked, *(rel for rel in approved if rel not in locked)]


def dict_of(entry: Any) -> dict[str, Any]:
    """A record table entry, as the mutable dict it is."""
    assert isinstance(entry, dict)
    return entry


def _scratch(worktree: Path) -> Path:
    """The runner worktree's scratch folder, in its own git dir (created if missing)."""
    path = Path(
        _git(worktree, "rev-parse", "--path-format=absolute", "--git-path", SCRATCH).strip()
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


def _dirty(root: Path, *paths: str) -> bool:
    return bool(_git(root, "status", "--porcelain", "--", *(paths or (".",))).strip())


def _review_line(role: str, report: Path) -> str:
    """What a review session is told about the driver's gate report (ADR 0046)."""
    given = f"The driver's newest full gate report is {report} ($FACTORY_GATE_REPORT)."
    if role == "verifier":
        return (
            f"{given} Check it, and don't run the gate: its verdict is pass, no check was "
            "skipped as not selected (it ran with no --checks), it isn't dirty, and its commit "
            "is HEAD or differs from HEAD only under .agentic/. Then map each acceptance "
            "criterion to a passing test tagged with its id."
        )
    return (
        f"{given} Use it as the gate's evidence. Don't run the full gate: if you need more, "
        "run one check with gate.py --checks <name>."
    )


def session_reply(log: Path) -> str:
    """A session's final reply: the `result` of its JSON output, or its plain output when it
    printed no JSON. Empty when the log can't be read."""
    try:
        text = log.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    for candidate in [text, *reversed(text.splitlines())]:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "result" in data:
            result = data["result"]
            return result.strip() if isinstance(result, str) else ""
    return text


def _review_round(path: Path) -> object:
    try:
        parsed = _state().parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None
    return None if isinstance(parsed, str) else parsed[0].get("review_round")


def pr_title(body: str) -> str:
    """The PR's title: the body's first line, up to its first full stop."""
    first = next((line.strip() for line in body.splitlines() if line.strip()), "")
    return re.split(r"\.(?:\s|$)", first, maxsplit=1)[0].strip() or "Untitled"


def _closing_handoff(
    rec: Mapping[str, Any],
    title: str,
    usd: str,
    prs: Sequence[Mapping[str, Any]],
    findings: Sequence[Mapping[str, Any]],
) -> str:
    """The closing handoff, in E02's form: what shipped, what's left, the open questions."""
    lines = ["## Done", "", f"- Job {rec['id']} ({rec['epic']}): {title}. Every slice merged:"]
    lines += [f"  - {p['task']}: PR {p['pr']} on {p['branch']}, merged." for p in prs]
    lines += [f"- The sessions reported ${usd} in all.", "", "## Next", ""]
    left = [f for f in findings if f.get("status") == "open"]
    if left:
        lines.append("- Follow up the findings still open:")
        lines += [
            f"  - {f['task']} {f.get('id')} [{f.get('severity')}] {f.get('summary')}" for f in left
        ]
    else:
        lines.append("- Nothing is left in this job: no finding is open.")
    lines += ["", "## Open questions", "", "None.", ""]
    return "\n".join(lines)


def dump_tables(data: Mapping[str, Any], tables: Sequence[str]) -> str:
    """A flat TOML document: the scalars in order, then each table's entries."""
    lines = [f"{key} = {_toml(value)}" for key, value in data.items() if key not in tables]
    for table in tables:
        for entry in data.get(table, []):
            lines += ["", f"[[{table}]]"]
            lines += [f"{key} = {_toml(value)}" for key, value in entry.items()]
    return "\n".join(lines) + "\n"


class _Stop(Exception):
    pass


def _halted(session: Mapping[str, Any], status: Mapping[str, Any]) -> str:
    state = status.get("status")
    reason = status.get("reason") or state
    return f"{session['stage']}: runner job {session['run']} {state}: {reason}"


def _cost(log: Path) -> str | None:
    """`total_cost_usd` from a session's JSON output, as a decimal string; None without one."""
    try:
        text = log.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    candidates = [text, *reversed(text.splitlines())]
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        value = data.get("total_cost_usd") if isinstance(data, dict) else None
        if isinstance(value, int | float) and not isinstance(value, bool) and value >= 0:
            return str(decimal.Decimal(str(value)).normalize())
    return None


# --- approvals and rejections (ADR 0044) ---------------------------------------------------------


def commit_file(
    root: Path, branch: str, rel: str, text: str, message: str, *, old: str | None = None
) -> str:
    """Commit one file's new text on `branch` without a checkout; refused if the branch moved."""
    import os

    ref = f"refs/heads/{branch}"
    current = _git(root, "rev-parse", "--verify", ref).strip()
    parent = old or current
    if parent != current:
        raise Refused(f"{branch} moved from {parent[:SHORT]} to {current[:SHORT]}")
    with tempfile.TemporaryDirectory(prefix="factory-commit-") as temp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(temp) / "index")}

        def run(*args: str, stdin: str | None = None) -> str:
            done = subprocess.run(
                ["git", *args],
                cwd=root,
                env=env,
                input=stdin,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            if done.returncode != 0:
                raise GitError(done.stderr.strip() or f"git {args[0]} failed")
            return done.stdout.strip()

        blob = run("hash-object", "-w", "--stdin", stdin=text)
        run("read-tree", parent)
        run("update-index", "--add", "--cacheinfo", f"100644,{blob},{rel}")
        tree = run("write-tree")
        commit = run("commit-tree", tree, "-p", parent, "-m", message)
        try:
            run("update-ref", ref, commit, parent)
        except GitError as exc:
            raise Refused(f"{branch} moved: {exc}") from None
    return commit


BOLD_STATUS = re.compile(r"^(Status: )\*\*[^*]+\*\*", re.MULTILINE)


def _date() -> str:
    now = dt.datetime.now(dt.UTC)
    return f"{now.day} {now:%b %Y}"


def _approve(job: Job, checkpoint: str, by: str) -> None:
    rec = job.record
    epic = rec["epic"]
    plan = [r for r in rec["runs"] if r.get("task") == rec["id"]]
    if not plan:
        raise Refused("the job has no plan branch")
    branch = str(plan[-1]["branch"])
    folder, kind, word = (
        ("docs/specs", "spec", "Approved")
        if checkpoint == "spec"
        else ("docs/design", "design", "Accepted")
    )
    listing = _lines(_git(job.root, "ls-tree", "-r", "--name-only", branch, "--", folder))
    docs = [rel for rel in listing if re.fullmatch(rf"{folder}/{re.escape(epic)}-[^/]+\.md", rel)]
    if len(docs) != 1:
        raise Refused(f"{branch} has {len(docs)} {kind} documents for {epic}")
    rel = docs[0]
    text = _git(job.root, "show", f"{branch}:{rel}")
    new, count = BOLD_STATUS.subn(rf"\1**{word} by {by}, {_date()}**", text, count=1)
    if not count:
        raise Refused(f"{rel} has no bold status to change")
    problems = _docs().lint(kind, rel, new)
    if problems:
        raise Refused(f"{rel}: the new status line fails docs.py: {problems[0]}")
    verb = "approved" if checkpoint == "spec" else "accepted"
    commit_file(job.root, branch, rel, new, f"docs({epic}): {kind} {verb} by {by}")


def _approve_relock(args: argparse.Namespace) -> int:
    """`approve <job> relock --task <id> --by NAME [--files f...]` (spec AC-23, ADR 0047)."""
    if not args.task or not TASK_ID.fullmatch(args.task):
        raise BadInput("approve relock needs --task, the task whose lock is relocked")
    files = [Path(f).as_posix() for f in args.files or []]
    here = _toplevel(Path.cwd())
    with Job(here, args.job, _session_id(args.session)) as job:
        rec = job.record
        if rec["status"] != "needs-human":
            raise Refused(f"job {args.job} is {rec['status']}, not needs-human")
        if stage(rec["stage"]).scope != "slice":
            raise Refused(f"a relock is for a slice stage, and the job is at {rec['stage']}")
        task = str(rec["task"])
        runs = [r for r in rec["runs"] if r.get("task") == task]
        if not runs:
            raise Refused(f"no runner job has worked on {task} yet")
        branch = str(runs[-1]["branch"])
        rel = _lock_rel(args.task)
        try:
            locked = _locked_files(_git(job.root, "show", f"{branch}:{rel}"))
        except GitError:
            raise Refused(f"{branch} has no lock record for {args.task} ({rel})") from None
        except _Stop as stop:
            raise Refused(f"{branch}: {rel}: {stop}") from None

        def read(path: str) -> bytes | None:
            try:
                return _git(job.root, "show", f"{branch}:{path}").encode("utf-8")
            except GitError:
                return None

        changed = _changed_locked(read, locked)
        if not files and not changed:
            raise Refused(f"nothing to relock: every file in {rel} on {branch} still matches")
        files = files or changed
        missing = [f for f in files if read(f) is None]
        if missing:
            raise Refused(f"{', '.join(missing)} is not on {branch}")
        others = [f for f in changed if f not in files]
        if others:
            raise Refused(f"{', '.join(others)} changed on {branch} too; approve it with --files")
        attempt = int(rec.get("attempt", 1))
        debugger = [
            s
            for s in rec["sessions"]
            if s.get("role") == "debugger"
            and s.get("task") == task
            and s.get("attempt", 1) == attempt
        ]
        findings = [str(f) for f in (debugger[-1].get("blockers", []) if debugger else [])]
        rec["attempt"] = attempt + 1
        rec["decisions"].append(
            {
                "checkpoint": "relock",
                "verdict": "approve",
                "by": args.by,
                "at": _now(),
                "note": args.note or "",
                "task": task,
                "attempt": attempt + 1,
                "lock_task": args.task,
                "files": files,
                "findings": findings,
            }
        )
        if rec["sessions"] and "exit_code" not in rec["sessions"][-1]:
            rec["sessions"][-1]["exit_code"] = -1
        rec["status"], rec["reason"] = "ready", ""
        job.save()
        Driver(job, runner_for(job.root))._sync_e18()
    print(f"{args.job}: relock of {args.task} approved by {args.by}: {', '.join(files)}")
    return 0


def _decide(args: argparse.Namespace, verdict: str) -> int:
    if args.checkpoint == "relock" and verdict == "approve":
        return _approve_relock(args)
    if args.checkpoint not in CHECKPOINTS:
        raise BadInput(f"unknown checkpoint {args.checkpoint!r}; one of {', '.join(CHECKPOINTS)}")
    here = _toplevel(Path.cwd())
    with Job(here, args.job, _session_id(args.session)) as job:
        rec = job.record
        waiting = stage(rec["stage"]).checkpoint
        if args.checkpoint == "merge" and verdict == "approve":
            raise Refused("a merge is approved by merging the PR, not by a command")
        if rec["status"] != "awaiting-approval" or waiting != args.checkpoint:
            raise Refused(f"job {args.job} isn't waiting at the {args.checkpoint} checkpoint")
        task = rec["id"] if stage(rec["stage"]).scope == "plan" else rec["task"]
        attempt = int(rec.get("attempt", 1))
        if verdict == "approve":
            _approve(job, args.checkpoint, args.by)
            decision_attempt = attempt
        else:
            decision_attempt = attempt + 1
            rec["attempt"] = decision_attempt
        rec["decisions"].append(
            {
                "checkpoint": args.checkpoint,
                "verdict": verdict,
                "by": args.by,
                "at": _now(),
                "note": args.note or "",
                "task": task,
                "attempt": decision_attempt,
            }
        )
        rec["status"] = "ready"
        driver = Driver(job, runner_for(job.root))
        if verdict == "approve":
            driver._advance()
        else:
            job.save()
            driver._sync_e18()
    print(f"{args.job}: {verdict}d at the {args.checkpoint} checkpoint")
    return 0


# --- new, status, run, resume and cancel ---------------------------------------------------------


def _title_of(text: str) -> str:
    for line in text.splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line[:200]
    return "Untitled request"


def _github_repo(root: Path) -> str:
    """`<owner>/<repo>` from origin's configured URL (https or ssh form), as written: an
    `insteadOf` rewrite changes where git goes, not which GitHub repository it is."""
    try:
        url = _git(root, "config", "--get", "remote.origin.url").strip()
    except GitError:
        raise BadInput("the repo has no origin remote") from None
    match = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$", url)
    if not match:
        raise BadInput(f"origin ({url}) is not a GitHub repository")
    return f"{match.group(1)}/{match.group(2)}"


def _issue(root: Path, number: int) -> tuple[str, str]:
    gh = shutil.which("gh")
    if gh is None:
        raise BadInput("--issue needs the gh command")
    path = f"repos/{_github_repo(root)}/issues/{number}"
    done = subprocess.run([gh, "api", path], cwd=root, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise BadInput(f"gh api {path}: {done.stderr.strip()}")
    try:
        data = json.loads(done.stdout)
    except json.JSONDecodeError:
        raise BadInput(f"gh api {path} gave no JSON") from None
    return str(data.get("title", "")), str(data.get("body") or "")


def _new(args: argparse.Namespace) -> int:
    if not JOB_ID.fullmatch(args.job):
        raise BadInput(f"{args.job!r} is not a job id ([a-z0-9][a-z0-9-]{{0,29}})")
    if not EPIC_ID.fullmatch(args.epic):
        raise BadInput(f"--epic must name the epic, like E13 (got {args.epic!r})")
    if (args.request_file is None) == (args.issue is None):
        raise BadInput("give the request with --request-file FILE or --issue N, not both")
    here = _toplevel(Path.cwd())
    main_root = _main_worktree(here)
    config = load_config(here)
    settings = pipeline_config(config)
    if list((main_root / "docs" / "specs").glob(f"{args.epic}-*.md")):
        raise BadInput(f"{args.epic} already has a spec in docs/specs")
    if args.issue is not None:
        if settings["forge"] != "github":
            raise BadInput('--issue reads GitHub issues: it needs pipeline.forge = "github"')
        title, body = _issue(here, args.issue)
        request = f"{title}\n\n{body}\n"
    else:
        request = _read_text(Path(args.request_file))
        title = _title_of(request)
    title = args.title or title
    jobs = _jobs()
    try:
        repo = jobs.find_repo(here)
        if sidecar_path(here, args.job, "pipeline").exists():
            raise BadInput(f"job {args.job} already has a pipeline record")
        try:
            existing = jobs.read_job(repo, args.job)
        except jobs.UnknownJob:
            existing = None
        if existing is None:
            jobs.new_job(repo, title, job_id=args.job, track="full", task=args.job)
        elif existing["track"] != "full" or existing["status"] != "open":
            raise BadInput(f"job {args.job} is used ({existing['track']}, {existing['status']})")
    except jobs.BadInput as exc:
        raise BadInput(str(exc)) from None
    except jobs.Refused as exc:
        raise Refused(str(exc)) from None
    base = str(config.get("gates", {}).get("base_ref", "main"))
    record: dict[str, Any] = {
        "version": 1,
        "id": args.job,
        "epic": args.epic,
        "issue": args.issue or 0,
        "status": "ready",
        "reason": "",
        "stage": "spec",
        "task": args.job,
        "base": base,
        "request": request,
        "warnings": [],
        "tasks": [],
        "runs": [],
        "sessions": [],
        "gates": [],
        "decisions": [],
    }
    session = _session_id(getattr(args, "session", None))
    jobs.claim(repo, jobs.load_config(repo), args.job, session)
    try:
        jobs.write_sidecar(repo, args.job, "pipeline", dump_record(record), session)
    finally:
        jobs.release(repo, args.job, session)
    print(args.job)
    return 0


def _stages(rec: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Each stage that ran, per task and attempt: its times, its commands and its cost."""
    out: list[dict[str, Any]] = []
    for session in rec["sessions"]:
        key = (session.get("stage"), session.get("task"), session.get("attempt", 1))
        if not out or (out[-1]["stage"], out[-1]["task"], out[-1]["attempt"]) != key:
            out.append(
                {
                    "stage": key[0],
                    "task": key[1],
                    "attempt": key[2],
                    "started": session.get("sent", ""),
                    "finished": "",
                    "commands": [],
                    "usd": "0",
                }
            )
        entry = out[-1]
        entry["commands"].append(f"{session.get('run')}#{session.get('index')}")
        entry["finished"] = session.get("finished", "")
        total = decimal.Decimal(entry["usd"]) + decimal.Decimal(str(session.get("usd", "0")))
        entry["usd"] = str(total.normalize()) if total else "0"
    return out


def _status(args: argparse.Namespace) -> int:
    here = _toplevel(Path.cwd())
    record = read_record(here, args.job)
    jobs = _jobs()
    try:
        job = jobs.read_job(jobs.find_repo(here), args.job)
    except jobs.BadInput as exc:
        raise BadInput(str(exc)) from None
    summary = _read_summary(here, args.job)
    data = {
        "job": json.loads(json.dumps(job, default=str)),
        "pipeline": record,
        "stages": _stages(record),
        "summary": summary,
    }
    if args.json:
        print(json.dumps(data, indent=2))
        return 0
    print(f"{args.job}: {record['status']} at the {record['stage']} stage, task {record['task']}")
    if record["reason"]:
        print(f"  reason: {record['reason']}")
    print(f"  epic {record['epic']}, E18 job {job['status']}, phase {job['phase']}")
    for entry in data["stages"]:
        count = len(entry["commands"])
        print(f"  {entry['stage']} ({entry['task']}): {count} sessions, ${entry['usd']}")
    for decision in record["decisions"]:
        who = f"{decision['verdict']} by {decision['by']} at {decision['at']}"
        print(f"  {decision['checkpoint']} {who}")
    for entry in record["tasks"]:
        merged = "merged" if entry.get("merged") else "not merged"
        print(f"  {entry.get('id')}: PR {entry.get('pr') or '-'}, {merged}")
    if summary is not None:
        usd, when = summary.get("total_usd", "0"), summary.get("finished", "")
        print(f"  summary: ${usd} in all, finished {when}")
        print("  closing handoff:")
        for line in str(summary.get("handoff", "")).splitlines():
            print(f"    {line}" if line else "")
    return 0


def _run(args: argparse.Namespace) -> int:
    here = _toplevel(Path.cwd())
    with Job(here, args.job, _session_id(args.session)) as job:
        return Driver(job, runner_for(job.root)).run()


def _resume(args: argparse.Namespace) -> int:
    here = _toplevel(Path.cwd())
    with Job(here, args.job, _session_id(args.session)) as job:
        rec = job.record
        if rec["status"] != "needs-human":
            raise Refused(f"job {args.job} is {rec['status']}, not waiting for a human")
        attempt = int(rec.get("attempt", 1)) + 1
        rec["attempt"] = attempt
        task = rec["id"] if stage(rec["stage"]).scope == "plan" else rec["task"]
        rec["decisions"].append(
            {
                "checkpoint": rec["stage"],
                "verdict": "resume",
                "by": job.session,
                "at": _now(),
                "note": args.note or "",
                "task": task,
                "attempt": attempt,
            }
        )
        if rec["sessions"] and "exit_code" not in rec["sessions"][-1]:
            rec["sessions"][-1]["exit_code"] = -1
        rec["status"], rec["reason"] = "ready", ""
        job.save()
        Driver(job, runner_for(job.root))._sync_e18()
    print(f"{args.job}: ready to rerun the {rec['stage']} stage")
    return 0


def _cancel(args: argparse.Namespace) -> int:
    here = _toplevel(Path.cwd())
    with Job(here, args.job, _session_id(args.session)) as job:
        rec = job.record
        if rec["status"] in ("done", "cancelled"):
            raise Refused(f"job {args.job} is {rec['status']}")
        runner = runner_for(job.root)
        for run in rec["runs"]:
            if not run.get("closed"):
                try:
                    runner.cancel(run["id"])
                except RunnerError as exc:
                    rec["warnings"].append(f"cancelling runner job {run['id']}: {exc}")
                run["closed"] = True
        rec["status"], rec["reason"] = "cancelled", "cancelled"
        job.save()
        Driver(job, runner)._sync_e18()
    print(f"{args.job}: cancelled")
    return 0


def _env(argv: Sequence[str]) -> int:
    """`_env KEY=VALUE ... -- argv`: run argv with the variables added (E16 passes none)."""
    import os

    if "--" not in argv:
        raise BadInput("_env needs -- before the command")
    split = list(argv).index("--")
    pairs, command = list(argv)[:split], list(argv)[split + 1 :]
    env = dict(os.environ)
    for pair in pairs:
        key, _, value = pair.partition("=")
        env[key] = value
    if not command:
        raise BadInput("_env needs a command")
    return subprocess.run(command, env=env, check=False).returncode


def _commit(argv: Sequence[str]) -> int:
    """`_commit MESSAGE -- PATH...`: commit what changed under the paths, if anything did. The
    driver sends it for roles that can't commit (the spec-writer, the architect, the reviewers'
    findings, the docs-writer)."""
    if len(argv) < 3 or argv[1] != "--":
        raise BadInput("_commit needs a message, then -- and the paths")
    message, paths = argv[0], list(argv[2:])
    root = Path.cwd()
    _git(root, "add", "-A", "--", *paths)
    if not _git(root, "diff", "--cached", "--name-only", "--", *paths).strip():
        return 0
    _git(root, "commit", "-q", "-m", message, "--", *paths)
    return 0


def _handoff(argv: Sequence[str]) -> int:
    """`_handoff TASK ROLE BODY MESSAGE`: record a reviewer's reply as its handoff with
    `state.py handoff`, then commit it with the task file's findings (ADR 0046)."""
    if len(argv) != 4:
        raise BadInput("_handoff needs a task, a role, a body file and a message")
    task, role, body, message = argv
    argv_ = [sys.executable, str(STATE_PATH), "handoff", task, "--from", role, "--body-file", body]
    done = subprocess.run(argv_, check=False)
    if done.returncode != 0:
        return done.returncode
    return _commit([message, "--", f".agentic/tasks/{task}.md", ".agentic/handoffs"])


# --- the command line ---------------------------------------------------------------------------


def _report(name: str, problems: Sequence[Problem]) -> int:
    for problem in problems:
        print(problem)
    if problems:
        return 1
    print(f"{name}: passes")
    return 0


def _check_worktree(args: argparse.Namespace) -> int:
    name = args.target
    if name not in STAGE_NAMES:
        raise BadInput(f"unknown stage {name!r}; the stages are {', '.join(STAGE_NAMES)}")
    if args.stage is not None:
        raise BadInput("with --worktree, give the stage once, as the first argument")
    found = stage(name)
    root = _toplevel(Path(args.worktree))
    config = load_config(root)
    epic = args.epic or ""
    if name != "learn" and not EPIC_ID.fullmatch(epic):
        raise BadInput(f"--epic must name the epic, like E13 (got {epic!r})")
    if found.scope == "slice" and not (args.task and TASK_ID.fullmatch(args.task)):
        raise BadInput(f"the {name} stage checks one task: give --task")
    if name in ("review", "ship", "learn") and not args.job:
        raise BadInput(f"the {name} stage needs the job's record: give --job")
    facts: dict[str, Any] = {}
    if args.job:
        facts = _record_facts(read_record(root, args.job), args.task or "")
        if name == "learn":
            facts["summary"] = _read_summary(root, args.job)
    if args.gate_report:
        facts["gate_report"] = _read_json(Path(args.gate_report))
    if args.pr_body:
        facts["pr_body"] = _read_text(Path(args.pr_body))
    base = ""
    if name != "learn":
        default = config.get("gates", {}).get("base_ref", "main")
        base = _resolve(root, args.base or str(default))
    checkout = Checkout(root=root, epic=epic, task=args.task or "", base=base, **facts)
    return _report(name, check(name, checkout))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BadInput(f"{path}: {exc}") from None
    if not isinstance(data, dict):
        raise BadInput(f"{path}: not a JSON object")
    return data


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise BadInput(f"{path}: {exc}") from None


def _check_job(args: argparse.Namespace) -> int:
    here = _toplevel(Path.cwd())
    load_config(here)
    record = read_record(here, args.target)
    name = args.stage or record["stage"]
    if name not in STAGE_NAMES:
        raise BadInput(f"unknown stage {name!r}; the stages are {', '.join(STAGE_NAMES)}")
    found = stage(name)
    task = record["id"] if found.scope == "plan" else record["task"]
    facts = _record_facts(record, task)
    if found.scope == "main":
        facts["summary"] = _read_summary(here, record["id"])
        checkout = Checkout(root=here, epic=record["epic"], **facts)
        return _report(name, check(name, checkout))
    runs = [run for run in record["runs"] if run.get("task") == task]
    if not runs:
        return _report(name, [Problem(task, name, "no runner job has worked on it yet")])
    worktree = Path(str(runs[-1].get("worktree", "")))
    if worktree.is_dir():
        root = _toplevel(worktree)
        return _check_in(name, record, task, runs, root, facts)
    temp = Path(tempfile.mkdtemp(prefix="factory-check-"))
    path = temp / "worktree"
    try:
        _git(here, "worktree", "add", "--detach", str(path), str(runs[-1].get("branch")))
    except GitError as exc:
        shutil.rmtree(temp, ignore_errors=True)
        raise BadInput(f"cannot check out {runs[-1].get('branch')}: {exc}") from None
    try:
        return _check_in(name, record, task, runs, path, facts)
    finally:
        try:
            _git(here, "worktree", "remove", "--force", str(path))
        finally:
            shutil.rmtree(temp, ignore_errors=True)


def _check_in(
    name: str,
    record: Mapping[str, Any],
    task: str,
    runs: Sequence[Mapping[str, Any]],
    root: Path,
    facts: dict[str, Any],
) -> int:
    base = _resolve(root, str(runs[0].get("base", ""))) if runs[0].get("base") else ""
    checkout = Checkout(root=root, epic=record["epic"], task=task, base=base, **facts)
    return _report(name, check(name, checkout))


def _check_command(args: argparse.Namespace) -> int:
    try:
        return _check_worktree(args) if args.worktree is not None else _check_job(args)
    except GitError as exc:
        raise BadInput(str(exc)) from None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pipeline.py", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    chk = commands.add_parser("check", help="run a stage's exit check; changes nothing")
    chk.add_argument("target", help="a job id, or with --worktree a stage")
    chk.add_argument("stage", nargs="?", help="the stage to check (default: the job's)")
    chk.add_argument("--worktree", metavar="PATH", help="check this checkout, without a job")
    chk.add_argument("--epic", help="the epic, such as E13 (with --worktree)")
    chk.add_argument("--task", help="the task, for a slice stage (with --worktree)")
    chk.add_argument("--base", help="the commit the scope started from (default: gates.base_ref)")
    chk.add_argument("--gate-report", metavar="FILE", help="a gate JSON report (gate, docs)")
    chk.add_argument("--pr-body", metavar="FILE", help="the PR body (ship)")
    chk.add_argument("--job", help="read the rest from this job's record (with --worktree)")
    chk.set_defaults(func=_check_command)

    new = commands.add_parser("new", help="create a job and its pipeline record")
    new.add_argument("job")
    new.add_argument("--epic", required=True, help="the epic the job's spec will have, like E31")
    new.add_argument("--request-file", metavar="FILE", help="the request, as text")
    new.add_argument("--issue", type=int, help="read the request from this GitHub issue")
    new.add_argument("--title", help="the job's title (default: the request's first line)")
    new.set_defaults(func=_new)

    run = commands.add_parser("run", help="drive the job to its next wait point")
    run.add_argument("job")
    run.add_argument("--session", help="the session id (default: $FACTORY_SESSION, or made up)")
    run.set_defaults(func=_run)

    for verdict in ("approve", "reject"):
        sub = commands.add_parser(verdict, help=f"{verdict} the checkpoint the job waits at")
        sub.add_argument("job")
        names = "spec, design, merge or relock" if verdict == "approve" else "spec, design or merge"
        sub.add_argument("checkpoint", help=names)
        sub.add_argument("--by", required=True, help="who decides")
        sub.add_argument("--note", required=verdict == "reject", help="for the role's next try")
        if verdict == "approve":
            sub.add_argument("--task", help="relock: the task whose lock record is relocked")
            sub.add_argument(
                "--files", nargs="+", help="relock: the approved files (default: those changed)"
            )
        sub.add_argument("--session", help="the session id")
        sub.set_defaults(func=lambda a, v=verdict: _decide(a, v))

    res = commands.add_parser("resume", help="rerun a stage that stopped for a human")
    res.add_argument("job")
    res.add_argument("--note", help="for the role's next try")
    res.add_argument("--session", help="the session id")
    res.set_defaults(func=_resume)

    can = commands.add_parser("cancel", help="cancel the job and its open runner job")
    can.add_argument("job")
    can.add_argument("--session", help="the session id")
    can.set_defaults(func=_cancel)

    sta = commands.add_parser("status", help="print the job and its pipeline record")
    sta.add_argument("job")
    sta.add_argument("--json", action="store_true")
    sta.set_defaults(func=_status)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    try:
        if argv[:1] == ["_env"]:
            return _env(argv[1:])
        if argv[:1] == ["_commit"]:
            return _commit(argv[1:])
        if argv[:1] == ["_handoff"]:
            return _handoff(argv[1:])
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    except BadInput as exc:
        print(f"pipeline.py: {exc}", file=sys.stderr)
        return 2
    try:
        code: int = args.func(args)
    except BadInput as exc:
        print(f"pipeline.py: {exc}", file=sys.stderr)
        return 2
    except Refused as exc:
        print(f"pipeline.py: refused: {exc}", file=sys.stderr)
        return 1
    except GitError as exc:
        print(f"pipeline.py: {exc}", file=sys.stderr)
        return 2
    return code


if __name__ == "__main__":
    sys.exit(main())
