"""E13 fixture: a scripted agent that plays any role in the pipeline's tests.

Usage (as `pipeline.agent_command`):

    fake_agent.py --role {role} --allowed {allowed_tools} {prompt}

It reads the script named by `$FAKE_AGENT_SCRIPT`, a JSON object mapping `<role>` or
`<role>@<task>` to a list of turns. Its n-th call for that key plays the n-th turn (the last one
again once they run out). A turn is a list of actions, done in order in the current directory:

    {"write": {"<path>": "<text>"}}     write files (LF endings)
    {"commit": "<message>"}             git add -A and commit
    {"run": ["argv", ...]}              run a command; a non-zero exit stops the turn with it
    {"exit": <code>}                    stop the turn with this exit code
    {"cost": <usd or null>}             the cost to report (default 0.01; null reports none)
    {"print": "<text>"}                 print this instead of the JSON result

Every call is appended to `$FAKE_AGENT_LOG` as a JSON line: role, allowed tools, prompt, the
environment's FACTORY_ROLE and the working directory.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def _turn(script: dict[str, Any], role: str, task: str, counter: Path) -> list[dict[str, Any]]:
    key = f"{role}@{task}" if f"{role}@{task}" in script else role
    turns = script.get(key, [[]])
    calls = json.loads(counter.read_text(encoding="utf-8")) if counter.is_file() else {}
    n = calls.get(key, 0)
    calls[key] = n + 1
    counter.write_text(json.dumps(calls), encoding="utf-8")
    return list(turns[min(n, len(turns) - 1)])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", required=True)
    parser.add_argument("--allowed", default="")
    parser.add_argument("prompt")
    args = parser.parse_args()
    script_path = Path(os.environ["FAKE_AGENT_SCRIPT"])
    script = json.loads(script_path.read_text(encoding="utf-8"))
    task = next(
        (
            line.split("Task: ", 1)[1].rstrip(".")
            for line in args.prompt.splitlines()
            if "Task: " in line
        ),
        "",
    )
    log = os.environ.get("FAKE_AGENT_LOG")
    if log:
        entry = {
            "role": args.role,
            "allowed": args.allowed,
            "prompt": args.prompt,
            "factory_role": os.environ.get("FACTORY_ROLE", ""),
            "cwd": os.getcwd(),
        }
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    cost: float | None = 0.01
    printed: str | None = None
    code = 0
    counter = script_path.with_name(script_path.name + ".calls")
    for action in _turn(script, args.role, task, counter):
        if "write" in action:
            for rel, text in action["write"].items():
                path = Path(rel)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(text.encode("utf-8"))
        elif "commit" in action:
            subprocess.run(["git", "add", "-A"], check=True)
            subprocess.run(["git", "commit", "-q", "-m", action["commit"]], check=True)
        elif "run" in action:
            code = subprocess.run(action["run"], check=False).returncode
            if code:
                break
        elif "exit" in action:
            code = int(action["exit"])
            break
        elif "cost" in action:
            cost = action["cost"]
        elif "print" in action:
            printed = action["print"]
    result = "done\nVERDICT: pass" if args.role == "verifier" else "done"  # E13-T6
    if printed is not None:
        print(printed)
    elif cost is None:
        print(json.dumps({"result": result}))
    else:
        print(json.dumps({"result": result, "total_cost_usd": cost}))
    return code


if __name__ == "__main__":
    sys.exit(main())
