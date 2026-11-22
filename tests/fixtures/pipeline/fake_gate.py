"""E13 fixture: a stand-in for the full gate, run by the pipeline's driver.

Usage (as `gates.python_command`, so the driver's gate command lands here):

    fake_gate.py .factory/gates/gate.py --json-out PATH

It writes a report in the shape `gate.py --json-out` writes (E08 AC-01) for the current
directory's HEAD: `verdict` is "fail" when HEAD's tree holds a file named `GATE-RED`, and "pass"
otherwise; `dirty` says whether `git status --porcelain` shows anything. It exits 1 on a fail, as
the gate does. Each call is appended to `$FAKE_GATE_LOG` as a JSON line, when that is set.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

RED = "GATE-RED"


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8", check=False
    )


def _check(name: str, status: str) -> dict[str, object]:
    """One check, as gate.py's Result is written (E05, E08)."""
    return {
        "profile": "python",
        "check": name,
        "status": status,
        "reason": "",
        "exit_code": 0 if status == "pass" else 1,
        "duration_s": 0.1,
        "command": ["python", "-m", name],
        "output_tail": "",
    }


def main() -> int:
    argv = sys.argv[1:]
    out = Path(argv[argv.index("--json-out") + 1])
    commit = _git("rev-parse", "HEAD").stdout.strip()
    red = _git("cat-file", "-e", f"HEAD:{RED}").returncode == 0
    dirty = bool(_git("status", "--porcelain").stdout.strip())
    verdict = "fail" if red else "pass"
    checks = [_check("format", "pass"), _check("tests", verdict)]
    report = {
        "verdict": verdict,
        "root": ".",
        "base_ref": "main",
        "commit": commit,
        "dirty": dirty,
        "profiles": ["python"],
        "changed_files": [],
        "locks": {"locked": 1, "broken": []},
        "docs": {"checked": 2, "problems": []},
        "adapters": {"files": None, "problems": []},
        "checks": checks,
    }
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log = os.environ.get("FAKE_GATE_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"argv": argv, "cwd": os.getcwd(), "commit": commit}) + "\n")
    return 1 if red else 0


if __name__ == "__main__":
    sys.exit(main())
