"""Software Factory git hook launcher (E07, ADR 0012). Standard library only.

The sh hooks in this folder find a Python 3.11+ and run:  run_hook.py <pre-commit|pre-push>

It reads the gate's own settings from .agentic/config.toml, then runs the gate inside the
project's environment (gates.python_command), from the repo root:

    pre-commit:  <python_command> .factory/gates/gate.py --checks <gates.commit_checks>
    pre-push:    <python_command> .factory/gates/gate.py

Any non-zero gate exit blocks the commit or push. Bypass once with --no-verify.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gate  # the installed gate, one folder up

GATE_RELPATH = ".factory/gates/gate.py"
HOOKS = ("pre-commit", "pre-push")


def gate_args(hook: str, settings: gate.Settings) -> list[str]:
    """The gate arguments each hook runs (E07 AC-05, AC-06)."""
    if hook == "pre-commit":
        return [GATE_RELPATH, "--checks", ",".join(settings.commit_checks)]
    return [GATE_RELPATH]


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or args[0] not in HOOKS:
        print(f"usage: run_hook.py {{{'|'.join(HOOKS)}}}", file=sys.stderr)
        return 2
    hook = args[0]
    try:
        root = gate.find_root(Path.cwd())
        settings = gate.Settings.load(root)
    except gate.GateError as exc:
        print(f"factory hook: gate: {exc}", file=sys.stderr)
        return 1
    command = list(settings.python_command)
    found = shutil.which(command[0])
    if found is None:
        print(
            f"factory hook: {command[0]} not found on PATH (gates.python_command)",
            file=sys.stderr,
        )
        return 1
    if hook == "pre-commit":
        print("factory hook: checking the working tree, unstaged changes included", flush=True)
    completed = subprocess.run([found, *command[1:], *gate_args(hook, settings)], cwd=root)
    return 0 if completed.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
