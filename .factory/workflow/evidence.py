"""Software Factory PR evidence drafter (E08, ADR 0025). Standard library only.

    python .factory/workflow/evidence.py [--root PATH] <task> --gate-report PATH [--out FILE]
    python .factory/workflow/evidence.py --summary REPORT

The first form drafts one task's PR body from the gate's JSON report (`gate.py --json-out`), the
task file, the epic's spec and the task's lock record. It never reruns the gate. The author
replaces each `TODO(author)` placeholder, then checks the body with `docs.py check-pr --strict`.
The second form prints the short Markdown summary CI writes to a job page.

Exit codes: 0 drafted, 1 refused input (a missing file, a report from a dirty tree, a tag the
spec doesn't have), 2 a usage error. `--summary` always exits 0.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

HERE = Path(__file__).resolve().parent
DOCS_PATH = HERE / "docs.py"
GATE_PATH = HERE.parent / "gates" / "gate.py"
TODO = "TODO(author)"
TASK_ID = re.compile(r"(E\d+)-(T\d+)")
ISSUE = re.compile(r"^Issue: \[#(\d+)\]", re.MULTILINE)
SHORT_SHA = 12

# A test definition per stack, and the group holding its name (design note: how tags bind).
PYTHON_TEST = re.compile(r"^\s*(?:async\s+)?def (test_\w+)", re.MULTILINE)
TS_TEST = re.compile(r"\b(?:test|it)(?:\.\w+)?\(\s*(['\"`])(.+?)\1")
STACKS = {
    ".py": (PYTHON_TEST, 1),
    **{ext: (TS_TEST, 2) for ext in (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")},
}


class Refused(Exception):
    """Input the draft can't be built from (exit 1)."""


def _load(path: Path, name: str) -> ModuleType:
    """A sibling kit module, loaded under the name the gate uses (ADR 0016)."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise Refused(f"evidence.py needs {path.name} at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses look the module up by name
    spec.loader.exec_module(module)
    return module


def _modules() -> tuple[Any, Any]:
    """(docs, gate): docs.py brings state.py with it."""
    for path in (DOCS_PATH, GATE_PATH):
        if not path.is_file():
            raise Refused(f"evidence.py needs {path} beside it")
    # Names of their own, so a gate that loaded another repo's docs.py can't swap them.
    return _load(DOCS_PATH, "factory_evidence_docs"), _load(GATE_PATH, "factory_evidence_gate")


# --- reading ------------------------------------------------------------------------------------


@dataclass
class Traced:
    """What one locked file holds: its test count, and per AC id the tests that carry its tag."""

    path: str
    tests: int = 0
    acs: dict[str, list[str]] = field(default_factory=dict)


def trace_file(path: str, text: str, epic: str) -> Traced:
    """Bind each `<EPIC>-AC-nn` tag to the next test definition in the file (ADR 0025).

    A tag inside a definition, such as a TS test's title, binds to that definition. A tag with no
    test after it, or in a stack with no known form, is listed under the file alone.
    """
    tag = re.compile(rf"(?<![\w-]){re.escape(epic)}-(AC-\d\d[a-z]?)(?![\w-])")
    stack = STACKS.get(Path(path).suffix.lower())
    found = [] if stack is None else [(m.end(), m.group(stack[1])) for m in stack[0].finditer(text)]
    traced = Traced(path, tests=len(found))
    for match in tag.finditer(text):
        names = traced.acs.setdefault(match.group(1), [])
        name = next((name for end, name in found if end > match.start()), None)
        if name is not None and name not in names:
            names.append(name)
    return traced


def _read_spec(root: Path, docs: Any, epic: str) -> tuple[list[str], str]:
    """(the spec's AC ids in order, its issue number)."""
    folder = root / "docs" / "specs"
    specs = sorted(folder.glob(f"{epic}-*.md")) if folder.is_dir() else []
    if len(specs) != 1:
        found = "no spec" if not specs else f"{len(specs)} specs"
        raise Refused(f"{found} for {epic} in docs/specs/ ({epic}-*.md)")
    rel = specs[0].relative_to(root).as_posix()
    text = specs[0].read_text(encoding="utf-8")
    issue = ISSUE.search(text)
    if issue is None:
        raise Refused(f"{rel}: no 'Issue: [#N]' line")
    return [ac for ac in docs.AC_ID.findall(text) if docs.AC_FORM.fullmatch(ac)], issue.group(1)


def _read_task(root: Path, state: Any, task: str) -> list[dict[str, object]]:
    """The task file's findings."""
    rel = f"{state.TASKS_REL}/{task}.md"
    path = root / rel
    if not path.is_file():
        raise Refused(f"no task file {rel} for {task}")
    parsed = state.parse(path.read_text(encoding="utf-8"))
    if isinstance(parsed, str):
        raise Refused(f"{rel}: {parsed}")
    findings = parsed[0].get("findings", [])
    return [f for f in findings if isinstance(f, dict)] if isinstance(findings, list) else []


def _read_report(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Refused(f"no gate report {path}") from None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Refused(f"{path}: not a gate JSON report: {exc}") from None
    if not isinstance(data, dict):
        raise Refused(f"{path}: not a gate JSON report")
    return data


def _git(root: Path, *args: str) -> str:
    try:
        done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


@dataclass
class Locked:
    record: str
    commit: str  # "" when the record isn't committed
    files: list[Traced]


def _read_locks(root: Path, task: str, epic: str) -> Locked | None:
    rel = f".agentic/locks/{task}.toml"
    path = root / rel
    if not path.is_file():
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise Refused(f"{rel}: invalid TOML: {exc}") from None
    entries = data.get("files", [])
    paths = [str(e["path"]) for e in entries if isinstance(e, dict) and "path" in e]
    files: list[Traced] = []
    for file in paths:
        target = root / file
        if not target.is_file():
            raise Refused(f"{rel} locks {file}, which does not exist")
        files.append(trace_file(file, target.read_text(encoding="utf-8"), epic))
    return Locked(rel, _git(root, "log", "-1", "--format=%h", "--", rel), files)


# --- rendering ----------------------------------------------------------------------------------


def _took(seconds: object) -> str | None:
    return f"{seconds:.2f} s" if isinstance(seconds, int | float) else None


def summary_line(report: Any) -> str:
    """The verdict, the commit, the locks and docs lines, and each check with its time."""
    if report.commit is None:
        where = "with no commit"
    else:
        where = f"on `{report.commit[:SHORT_SHA]}`"
        if report.dirty:
            where += " (uncommitted changes)"
    text = report.to_text().split("\n")
    parts = [f"**{report.verdict.upper()}** {where}"]
    parts += [line for line in text if line.startswith(("Locks: ", "Docs: "))]
    for r in report.results:
        took = _took(r.duration_s)
        parts.append(f"{r.profile} {r.check} {r.status}" + (f" {took}" if took else ""))
    return " · ".join(parts)


def _join(items: Sequence[str]) -> str:
    if len(items) < 2:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def covers(ids: Sequence[str], order: Sequence[str]) -> str:
    """`**AC-01** to **AC-03** and **AC-05**`: runs of three or more in spec order as a range."""
    index = sorted(order.index(ac) for ac in ids)
    runs: list[list[int]] = []
    for i in index:
        if runs and i == runs[-1][-1] + 1:
            runs[-1].append(i)
        else:
            runs.append([i])
    items: list[str] = []
    for run in runs:
        if len(run) >= 3:
            items.append(f"**{order[run[0]]}** to **{order[run[-1]]}**")
        else:
            items += [f"**{order[i]}**" for i in run]
    return _join(items)


def _trace_lines(ac: str, files: list[Traced]) -> list[str]:
    def entry(traced: Traced) -> str:
        names = traced.acs[ac]
        listed = ", ".join(f"`{name}`" for name in names)
        return f"`{traced.path}`" + (f": {listed}" if names else "")

    holders = [traced for traced in files if ac in traced.acs]
    if len(holders) == 1:
        return [f"- **{ac}** {entry(holders[0])}"]
    return [f"- **{ac}**", *(f"  - {entry(traced)}" for traced in holders)]


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _fence(text: str) -> str:
    runs = [len(run) for run in re.findall(r"`{3,}", text)]
    return "`" * max([3, *(n + 1 for n in runs)])


def draft(root: Path, task: str, report_path: Path) -> str:
    """The PR body for one task (spec AC-03 to AC-08)."""
    docs, gate = _modules()
    named = TASK_ID.fullmatch(task)
    if named is None:
        raise Refused(f"task {task} does not name an epic: expected <EPIC>-Tn, such as E08-T2")
    epic, slice_ = named.groups()
    findings = _read_task(root, docs.state, task)
    order, issue = _read_spec(root, docs, epic)
    data = _read_report(report_path)
    try:
        report = gate.Report.from_json(data)
    except (KeyError, TypeError, ValueError) as exc:
        raise Refused(f"{report_path}: not a gate JSON report: {exc}") from None
    if report.commit is None:
        raise Refused(f"{report_path}: the gate ran with no commit, so it proves none")
    if report.dirty:
        raise Refused(
            f"{report_path}: the gate ran on {report.commit[:SHORT_SHA]} with uncommitted changes,"
            " so it proves no commit. Commit, rerun the gate with --json-out, and draft again"
        )
    locked = _read_locks(root, task, epic)

    files = locked.files if locked else []
    for file in files:
        for ac in file.acs:
            if ac not in order:
                raise Refused(f"{file.path}: {epic}-{ac} is not in the {epic} spec")
    ids = [ac for ac in order if any(ac in file.acs for file in files)]

    what = covers(ids, order) if ids else f"{TODO}: the ACs it covers"
    lines = [
        f"{epic}/{slice_}: {TODO}: what this PR delivers. Covers {epic} {what}. Refs #{issue}.",
        "",
        "## What changes",
        "",
        f"- {TODO}: what each change does, and why.",
        "",
        "## Acceptance criteria",
        "",
    ]
    if ids:
        for ac in ids:
            lines += _trace_lines(ac, files)
    else:
        lines.append(f"- {TODO}: each **AC-nn** and the tests that prove it.")
    lines += ["", "## Tests", ""]
    if locked is None:
        lines.append("No locked tests.")
    else:
        tests = sum(traced.tests for traced in locked.files)
        lines.append(
            f"{_plural(tests, 'test')} in {_plural(len(locked.files), 'file')},"
            f" locked in `{locked.record}` ({locked.commit or 'not committed'})."
        )
    text = report.to_text()
    fence = _fence(text)
    line = summary_line(report)
    pid = docs.patch_id(root, report.commit)  # ADR 0027: a clean rebase still matches
    if pid:
        shown = f"on `{report.commit[:SHORT_SHA]}`"
        line = line.replace(shown, f"{shown} (patch-id `{pid}`)", 1)
    lines += [
        "",
        "## Gate evidence",
        "",
        line,
        "",
        "<details><summary>Full gate report</summary>",
        "",
        f"{fence}text",
        text,
        fence,
        "",
        "</details>",
        "",
        "## Findings",
        "",
    ]
    if findings:
        lines += [
            f"- {f.get('id')} [{f.get('severity')}] ({f.get('status')}) {f.get('summary')}"
            for f in findings
        ]
    else:
        lines.append("None.")
    return "\n".join(lines) + "\n"


def summary(report_path: Path) -> str:
    """CI's job summary: the summary line and a table of checks, or `No gate report.`"""
    try:
        _, gate = _modules()
        report = gate.Report.from_json(_read_report(report_path))
        rows = [
            f"| {r.profile} | {r.check} | {r.status} | {_took(r.duration_s) or '-'} |"
            for r in report.results
        ]
        head = [summary_line(report), "", "| Profile | Check | Status | Time |"]
        return "\n".join([*head, "| --- | --- | --- | --- |", *rows]) + "\n"
    except (Refused, KeyError, TypeError, ValueError, AttributeError):
        return "No gate report.\n"


# --- entry point --------------------------------------------------------------------------------


def _emit(text: str) -> None:
    """Print with LF line endings on every OS (spec AC-03)."""
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(text)
        return
    sys.stdout.flush()
    buffer.write(text.encode("utf-8"))
    buffer.flush()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evidence.py", description=__doc__.split("\n")[0])
    parser.add_argument(
        "--root", help="repository root (default: the nearest folder holding .agentic/)"
    )
    parser.add_argument("task", nargs="?", help="the task to draft for, such as E08-T2")
    parser.add_argument("--gate-report", metavar="PATH", help="the gate's JSON report")
    parser.add_argument("--out", metavar="FILE", help="write the body to FILE, not stdout")
    parser.add_argument(
        "--summary", metavar="REPORT", help="print a job-page summary of a gate JSON report"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        if args.summary is not None:
            if args.task or args.gate_report or args.out:
                parser.error("--summary takes no task, --gate-report or --out")
        elif not args.task or not args.gate_report:
            parser.error("give a task and --gate-report PATH, or --summary REPORT")
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    if args.summary is not None:
        _emit(summary(Path(args.summary)))
        return 0
    try:
        docs, _ = _modules()
        root = Path(args.root).resolve() if args.root else docs.state.find_root(Path.cwd())
        body = draft(root, args.task, Path(args.gate_report))
    except Refused as exc:
        print(f"evidence: {exc}", file=sys.stderr)
        return 1
    if args.out:
        Path(args.out).write_text(body, encoding="utf-8", newline="\n")
        print(f"evidence: wrote {args.out}", file=sys.stderr)
    else:
        _emit(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
