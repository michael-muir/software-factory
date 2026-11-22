"""E13 fixture: what the Integrator does at the ship stage, scripted.

Usage (as a fake agent's `run` action, in the slice's worktree):

    draft_pr_body.py <task> [--leave-todo]

It follows the pull-request-evidence skill: it drafts the body with the kit's `evidence.py` from
the gate report named by `$FACTORY_GATE_REPORT`, then replaces each `TODO(author)` placeholder
(unless `--leave-todo`), and writes the body to `$FACTORY_PR_BODY`. It exits with evidence.py's
code when the draft is refused.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

EVIDENCE_PY = Path(__file__).resolve().parents[3] / "kit" / ".factory" / "workflow" / "evidence.py"
TODO = "TODO(author)"


def main() -> int:
    task = sys.argv[1]
    out = Path(os.environ["FACTORY_PR_BODY"])
    report = os.environ["FACTORY_GATE_REPORT"]
    argv = [sys.executable, str(EVIDENCE_PY), "--root", ".", task, "--gate-report", report]
    done = subprocess.run([*argv, "--out", str(out)], check=False)
    if done.returncode != 0:
        return done.returncode
    if "--leave-todo" not in sys.argv[2:]:
        text = out.read_text(encoding="utf-8").replace(TODO, "Filled in")
        out.write_bytes(text.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
