#!/usr/bin/env python3
"""Software Factory full-track pipeline (E13, ADRs 0040 to 0044). Standard library only.

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
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

HERE = Path(__file__).resolve().parent
FACTORY = HERE.parent
DOCS_PATH = HERE / "docs.py"
EVIDENCE_PATH = HERE / "evidence.py"
AGENTS_PATH = FACTORY / "agents" / "agents.py"

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


def _check_gate(c: Checkout) -> Found:
    report = c.gate_report
    if report is None:
        return [(GATE, f"no gate report for {c.task or 'the task'}")]
    found: Found = []
    verdict = report.get("verdict")
    if verdict != "pass":
        checks = report.get("checks", [])
        failed = [str(ch.get("name")) for ch in checks if ch.get("status") == "fail"]
        if report.get("locks", {}).get("broken"):
            failed.append("locks")
        if report.get("docs", {}).get("problems"):
            failed.append("docs")
        found.append((GATE, f"the verdict is {verdict}: {', '.join(failed) or 'no check named'}"))
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


def _check_ship(c: Checkout) -> Found:
    found: Found = []
    if c.pr_body is None:
        found.append((BODY, "no PR body"))
    else:
        docs = _docs()
        commits = c.commits()
        problems = docs.lint_pr(c.pr_body, BODY) + docs.lint_pr_strict(
            c.pr_body, BODY, c.root, commits
        )
        found += [(p.path, f"{p.where}: {p.message}") for p in problems]
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


def session_argv(template: Sequence[str], role: str, allowed: str, prompt: str) -> list[str]:
    """The agent command: each whole-element placeholder filled in, so a prompt stays one arg."""
    values = {"{role}": role, "{allowed_tools}": allowed, "{prompt}": prompt}
    return [values.get(item, item) for item in template]


def session_env(role: str) -> dict[str, str]:
    """What a session's environment adds, so the E03 hook knows the role."""
    return {"FACTORY_ROLE": role}


def prompt(
    name: str,
    role: str,
    *,
    job: str,
    epic: str,
    task: str,
    reads: Sequence[str] = (),
    note: str = "",
) -> str:
    """The stage prompt for one role's session: plain text, the same for the same inputs."""
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
    lines.append("Work only in this worktree. Commit your work and stop.")
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    try:
        code: int = args.func(args)
    except BadInput as exc:
        print(f"pipeline.py: {exc}", file=sys.stderr)
        return 2
    return code


if __name__ == "__main__":
    sys.exit(main())
