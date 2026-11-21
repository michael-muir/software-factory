"""Software Factory document linter (E04, ADRs 0019 and 0020). Standard library only.

    python .factory/workflow/docs.py [--root PATH] check
    python .factory/workflow/docs.py check-pr [FILE]      # PR evidence; stdin without FILE
    python .factory/workflow/docs.py check-pr --strict [FILE] [--commits SHA ...]   # E08

Specs (docs/specs/), design notes (docs/design/) and ADRs (docs/adr/) must have the parts their
templates in templates/ show: a title, a Status line, required lines and headings, and for a
spec at least one acceptance criterion. Each kind's rules are one row of data (ADR 0019). This
module is built on its sibling `state.py`, which supplies the root finder and the problem type.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import subprocess
import sys
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from state import Problem

STATE_PATH = Path(__file__).resolve().parent.parent / "state" / "state.py"
NEEDS_STATE = "docs.py needs .factory/state/state.py beside it"


def _load_state() -> ModuleType | None:
    """The sibling state module, loaded under the name the gate uses (ADR 0016)."""
    if not STATE_PATH.is_file():
        return None
    spec = importlib.util.spec_from_file_location("factory_state", STATE_PATH)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules["factory_state"] = module  # dataclasses look the module up by name
    spec.loader.exec_module(module)
    return module


state: Any = _load_state()

AC_ID = re.compile(r"^- \*\*(AC-[^*]+)\*\*", re.MULTILINE)
AC_FORM = re.compile(r"AC-\d\d[a-z]?")
BOLD = re.compile(r"\*\*(.+?)\*\*")
LINK = re.compile(r"\]\(([^)]+)\)")
ADR_STATUS = re.compile(
    r"Status: (Proposed|Accepted|Superseded by (\d{4})) · Date: \d{4}-\d\d-\d\d( · [^·]+: [^·]+)*"
)

# An extra rule: (rel, key from the file name, text outside code fences, status line, root) ->
# problems. root is None when linting a template, so checks that read other files are skipped.
Extra = Callable[[str, str, str, str, Path | None], list["Problem"]]


@dataclass(frozen=True)
class Kind:
    folder: str
    file_name: re.Pattern[str]  # group 1 is the key: an epic such as E04, or an ADR number
    title: str  # a regex, with {key} for the key
    title_form: str  # how the title should look, for the message
    headings: tuple[str, ...]
    line: str = ""  # a line that must start with this, such as "Issue:"
    status: tuple[str, ...] = ()  # the bold status text must start with one of these
    extra: Extra | None = None


def _outside_fences(text: str) -> str:
    kept: list[str] = []
    fenced = False
    for line in text.split("\n"):
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced:
            kept.append(line)
    return "\n".join(kept)


def _has_heading(lines: Sequence[str], heading: str) -> bool:
    return any(line == heading or line.startswith(heading + " ") for line in lines)


def _spec_acs(rel: str, key: str, text: str, status: str, root: Path | None) -> list[Problem]:
    ids = AC_ID.findall(text)
    valid = [ac for ac in ids if AC_FORM.fullmatch(ac)]
    if not valid:
        return [
            state.Problem(rel, "## Acceptance criteria", "no acceptance criteria (- **AC-nn**)")
        ]
    seen: set[str] = set()
    found: list[Problem] = []
    for ac in valid:
        if ac in seen:
            found.append(state.Problem(rel, ac, "used twice"))
        seen.add(ac)
    return found


def _design_spec_link(
    rel: str, key: str, text: str, status: str, root: Path | None
) -> list[Problem]:
    line = next((line for line in text.split("\n") if line.startswith("Spec:")), "")
    link = LINK.search(line)
    if not link:
        return [state.Problem(rel, "Spec", "no link to the spec")]
    if root is not None and not ((root / rel).parent / link.group(1)).is_file():
        return [state.Problem(rel, "Spec", f"{link.group(1)} does not exist")]
    return []


def _adr_status(rel: str, key: str, text: str, status: str, root: Path | None) -> list[Problem]:
    match = ADR_STATUS.fullmatch(status)
    if not match:
        form = "Status: Proposed|Accepted|Superseded by NNNN · Date: YYYY-MM-DD"
        return [state.Problem(rel, "status", f"must be '{form}'")]
    target = match.group(2)
    if root is not None and target and not list((root / "docs/adr").glob(f"{target}-*.md")):
        return [state.Problem(rel, "status", f"superseded by {target}, which does not exist")]
    return []


KINDS = {
    "spec": Kind(
        folder="docs/specs",
        file_name=re.compile(r"(E\d+)-.+\.md"),
        title=r"# {key} · .+ — Spec",
        title_form="# <EPIC> · <title> — Spec",
        headings=(
            "## Goal",
            "## Decisions in force",
            "## In scope",
            "## Out of scope",
            "## Acceptance criteria",
            "## Assumptions",
        ),
        line="Issue:",
        status=("Draft", "Approved"),
        extra=_spec_acs,
    ),
    "design": Kind(
        folder="docs/design",
        file_name=re.compile(r"(E\d+)-.+\.md"),
        title=r"# {key} · .+ design note",
        title_form="# <EPIC> · <title> design note",
        headings=(
            "## Summary",
            "## Source layout",
            "## Test seams",
            "## Vertical slices",
            "## Risks",
        ),
        line="Spec:",
        status=("Proposed", "Accepted"),
        extra=_design_spec_link,
    ),
    "adr": Kind(
        folder="docs/adr",
        file_name=re.compile(r"(\d{4})-.+\.md"),
        title=r"# {key} · .+",
        title_form="# NNNN · <title>",
        headings=("## Context", "## Decision", "## Consequences"),
        extra=_adr_status,
    ),
}
NOT_DOCUMENTS = frozenset({"README.md"})
PR_HEADINGS = ("## What changes", "## Acceptance criteria", "## Gate evidence", "## Findings")
VERDICT = re.compile(r"\*\*(PASS|FAIL)\*\*")


def lint(kind_name: str, rel: str, text: str, root: Path | None = None) -> list[Problem]:
    """Problems in one document of a kind. With root None (a template), other files aren't read."""
    kind = KINDS[kind_name]
    named = kind.file_name.fullmatch(Path(rel).name)
    if named is None:
        return [state.Problem(rel, "file name", f"must look like {kind.file_name.pattern}")]
    key = named.group(1)
    body = _outside_fences(text.replace("\r\n", "\n"))
    lines = body.split("\n")
    found: list[Problem] = []

    if not re.fullmatch(kind.title.format(key=re.escape(key)), lines[0]):
        found.append(state.Problem(rel, "title", f"must be '{kind.title_form}' with {key}"))
    if kind.line and not any(line.startswith(kind.line) for line in lines):
        found.append(state.Problem(rel, kind.line.rstrip(":"), f"no {kind.line} line"))
    status = next((line for line in lines if line.startswith("Status:")), "")
    if not status:
        found.append(state.Problem(rel, "status", "no Status: line"))
    elif kind.status:
        bold = BOLD.search(status)
        if bold is None or not bold.group(1).startswith(kind.status):
            found.append(
                state.Problem(rel, "status", f"must be **{' ...** or **'.join(kind.status)} ...**")
            )
    for heading in kind.headings:
        if not _has_heading(lines, heading):
            found.append(state.Problem(rel, heading, "missing heading"))
    if kind.extra is not None and status:
        found += kind.extra(rel, key, body, status, root)
    return found


def _section(lines: Sequence[str], heading: str) -> str:
    """The text under the first heading that matches, up to the next ## heading."""
    start = next((i for i, line in enumerate(lines) if _has_heading([line], heading)), None)
    if start is None:
        return ""
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[start + 1 : end])


def lint_pr(text: str, name: str) -> list[Problem]:
    """Problems in PR evidence (spec AC-06): four headings, and a verdict in the gate evidence."""
    lines = _outside_fences(text.replace("\r\n", "\n")).split("\n")
    found = [
        state.Problem(name, heading, "missing heading")
        for heading in PR_HEADINGS
        if not _has_heading(lines, heading)
    ]
    evidence = "## Gate evidence"
    if _has_heading(lines, evidence) and not VERDICT.search(_section(lines, evidence)):
        found.append(state.Problem(name, evidence, "no verdict: **PASS** or **FAIL**"))
    return found


PR_EPIC = re.compile(r"^(E\d+)/T\d+|Covers (E\d+)")
PR_COMMIT = re.compile(r"(?<![0-9A-Za-z])(?=[0-9a-f]*[0-9])[0-9a-f]{7,40}(?![0-9A-Za-z])")
PR_AC_LINE = re.compile(r"^- \*\*(AC-[^*]+)\*\*")
BACKTICKED = re.compile(r"`[^`\n]+`")
PLACEHOLDER = "TODO(author)"
SHORT_SHA = 12


def _raw_section(lines: Sequence[str], heading: str) -> list[str]:
    """The lines under a heading, fenced blocks included, up to the next ## heading outside one."""
    out: list[str] = []
    inside, fenced = False, False
    for line in lines:
        if line.startswith("```"):
            fenced = not fenced
        if not fenced and line.startswith("## "):
            if inside:
                break
            inside = _has_heading([line], heading)
            continue
        if inside:
            out.append(line)
    return out


def pr_commit(text: str) -> str | None:
    """The commit the gate evidence names: its first 7-40 lowercase hex word with a digit."""
    lines = text.replace("\r\n", "\n").split("\n")
    for line in _raw_section(lines, "## Gate evidence"):
        found = PR_COMMIT.search(line)
        if found:
            return found.group(0)
    return None


def _spec_ids(root: Path, epic: str) -> set[str] | None:
    folder = root / "docs" / "specs"
    specs = sorted(folder.glob(f"{epic}-*.md")) if folder.is_dir() else []
    if not specs:
        return None
    return {ac for spec in specs for ac in AC_ID.findall(spec.read_text(encoding="utf-8"))}


PR_PATCH_ID = re.compile(r"patch-id `([0-9a-f]{7,40})`")


def patch_id(root: Path, commit: str) -> str | None:
    """`git patch-id --stable` of one commit, or None: no git, no such commit, or no diff."""
    try:
        shown = subprocess.run(
            ["git", "show", "--no-color", "--no-ext-diff", commit, "--"],
            cwd=root,
            capture_output=True,
            check=False,
        )
        if shown.returncode != 0 or not shown.stdout:
            return None
        found = subprocess.run(
            ["git", "patch-id", "--stable"],
            cwd=root,
            input=shown.stdout,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    words = found.stdout.decode("ascii", errors="replace").split()
    return words[0] if found.returncode == 0 and words else None


def recorded_patch_id(text: str) -> str | None:
    """The patch-id the gate evidence records after its commit (ADR 0027)."""
    lines = text.replace("\r\n", "\n").split("\n")
    for line in _raw_section(lines, "## Gate evidence"):
        found = PR_PATCH_ID.search(line)
        if found:
            return found.group(1)
    return None


def _same(a: str, b: str) -> bool:
    return len(a) >= 7 and len(b) >= 7 and (a.startswith(b) or b.startswith(a))


def commit_problems(
    text: str, name: str, commits: Sequence[str], root: Path | None = None
) -> list[Problem]:
    """E08 AC-10: the evidence's commit must be one of the PR's (a full SHA or 7+ prefix), or
    have the same patch-id as one of them, so a clean rebase still counts (ADR 0027)."""
    evidence = "## Gate evidence"
    commit = pr_commit(text)
    if commit is None:
        return [state.Problem(name, evidence, "no commit SHA")]
    if any(_same(c, commit) for c in commits):
        return []
    if root is not None and commits:
        # The commit's own patch-id when git has it; else the one the body records.
        own = patch_id(root, commit) or recorded_patch_id(text)
        if own and any((theirs := patch_id(root, c)) and _same(theirs, own) for c in commits):
            return []
    listed = ", ".join(c[:SHORT_SHA] for c in commits) if commits else "none"
    message = f"evidence is for {commit}, which is not a commit of this PR (its commits: {listed})"
    return [state.Problem(name, evidence, message)]


def lint_pr_strict(
    text: str, name: str, root: Path, commits: Sequence[str] | None = None
) -> list[Problem]:
    """The rules `check-pr --strict` adds to lint_pr (E08 AC-09, ADR 0025)."""
    text = text.replace("\r\n", "\n")
    raw = text.split("\n")
    lines = _outside_fences(text).split("\n")
    found: list[Problem] = []

    if commits is None:
        if pr_commit(text) is None:
            found.append(state.Problem(name, "## Gate evidence", "no commit SHA"))
    else:
        found += commit_problems(text, name, commits, root)

    trace = "## Acceptance criteria"
    section = _raw_section(lines, trace)
    starts = [i for i, line in enumerate(section) if PR_AC_LINE.match(line)]
    ids: list[str] = []
    for i in starts:
        match = PR_AC_LINE.match(section[i])
        assert match is not None
        ids.append(match.group(1))
        block = [section[i]]
        for line in section[i + 1 :]:
            if not line.strip() or not line[0].isspace():
                break
            block.append(line)
        if not BACKTICKED.search("\n".join(block)):
            found.append(state.Problem(name, match.group(1), "lists no test"))

    first = next((line for line in lines if line.strip()), "")
    epic = PR_EPIC.search(first)
    if epic is not None:
        key = epic.group(1) or epic.group(2)
        known = _spec_ids(root, key)
        if known is None:
            found.append(state.Problem(name, trace, f"no spec for {key}"))
        elif not ids:
            found.append(state.Problem(name, trace, "no AC lines (- **AC-nn**)"))
        else:
            found += [
                state.Problem(name, ac, f"not in the {key} spec") for ac in ids if ac not in known
            ]

    found += [
        state.Problem(name, f"line {n}", f"placeholder left: {PLACEHOLDER}")
        for n, line in enumerate(raw, start=1)
        if PLACEHOLDER in line
    ]
    return found


@dataclass
class Checked:
    """What validate() read: its problems (iterating gives them) and how many documents."""

    problems: list[Problem] = field(default_factory=list)
    count: int = 0

    def __iter__(self) -> Iterator[Problem]:
        return iter(self.problems)

    def __len__(self) -> int:
        return len(self.problems)


def validate(root: Path) -> Checked:
    """Lint every spec, design note and ADR under docs/ (spec AC-07)."""
    checked = Checked()
    for name, kind in KINDS.items():
        folder = root / kind.folder
        for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
            if path.name in NOT_DOCUMENTS or not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            checked.problems += lint(name, rel, path.read_text(encoding="utf-8"), root)
            checked.count += 1
    return checked


def _check(root: Path, args: argparse.Namespace) -> int:
    checked = validate(root)
    for problem in checked:
        print(problem)
    if checked:
        print(f"{len(checked)} problem{'s' if len(checked) != 1 else ''}", file=sys.stderr)
        return 1
    print(f"docs OK: {checked.count} checked")
    return 0


def _check_pr(root: Path, args: argparse.Namespace) -> int:
    name = args.file or "stdin"
    try:
        text = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    except (OSError, UnicodeDecodeError) as exc:
        print(state.Problem(name, "file", f"cannot read: {exc}"))  # E08 AC-11: not a crash
        return 1
    found = lint_pr(text, name)
    if args.strict:
        found += lint_pr_strict(text, name, root, args.commits)
    elif args.commits is not None:
        found += commit_problems(text, name, args.commits, root)
    for problem in found:
        print(problem)
    return 1 if found else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="docs.py", description=__doc__.split("\n")[0])
    parser.add_argument(
        "--root", help="repository root (default: the nearest folder holding .agentic/)"
    )
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser(
        "check", help="lint the specs, design notes and ADRs under docs/"
    ).set_defaults(run=_check)
    check_pr = commands.add_parser("check-pr", help="check PR evidence (stdin without FILE)")
    check_pr.add_argument("file", nargs="?", help="a file holding the PR body")
    check_pr.add_argument(
        "--strict", action="store_true", help="also check the commit, the trace and the spec (E08)"
    )
    check_pr.add_argument(
        "--commits",
        nargs="*",
        metavar="SHA",
        help="the PR's commits; the evidence's commit must be one of them (after FILE)",
    )
    check_pr.set_defaults(run=_check_pr)
    args = parser.parse_args(argv)
    if state is None:
        print(NEEDS_STATE, file=sys.stderr)
        return 2
    root = Path(args.root).resolve() if args.root else state.find_root(Path.cwd())
    code: int = args.run(root, args)
    return code


if __name__ == "__main__":
    sys.exit(main())
