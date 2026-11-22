"""E18/T2: many writers at once.

Covers E18 AC-07: 20 processes, started together, each claim their own job, send heartbeats and
report usage. None fails with a locked database, and the index then holds every lease and report.
"""

from __future__ import annotations

import decimal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests._jobs import JOBS_PY, call, jobs_repo, new
from tests._jobs_index import by_id, listing, submit
from tests._runner import RUN_PY

WORKERS = 20

WORKER = """
import runpy, subprocess, sys, time
from pathlib import Path
jobs_py, run_py, barrier, job, runner_job, session = sys.argv[1:7]
while not Path(barrier).exists():
    time.sleep(0.01)
sys.argv = ["jobs.py"]
jobs = runpy.run_path(jobs_py)
codes = [jobs["main"](["claim", job, "--session", session])]
for _ in range(5):
    codes.append(jobs["main"](["beat", job, "--session", session]))
usage = subprocess.run([sys.executable, run_py, "usage", runner_job, "--usd", "0.25"])
codes.append(usage.returncode)
codes.append(jobs["main"](["list", "--json"]))
sys.exit(max(codes))
"""


@pytest.mark.ac("E18-AC-07")
@pytest.mark.slow
def test_20_writers_at_once_lose_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    pairs = []
    for n in range(WORKERS):
        job = new(repo, monkeypatch, capsys, f"Job {n}", "--task", f"T-{n}")
        runner_job = submit(repo, monkeypatch, capsys, "--task", f"T-{n}", "--open")
        pairs.append((job, runner_job))
    assert call(repo, monkeypatch, capsys, "list")[0] == 0  # the index exists before the rush
    barrier = tmp_path / "go"
    script = tmp_path / "worker.py"
    script.write_text(WORKER, encoding="utf-8")
    procs = [
        subprocess.Popen(
            [
                sys.executable,
                str(script),
                str(JOBS_PY),
                str(RUN_PY),
                str(barrier),
                job,
                rj,
                f"s-{n}",
            ],
            cwd=repo,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        for n, (job, rj) in enumerate(pairs)
    ]
    time.sleep(1.0)
    barrier.write_text("go", encoding="utf-8")
    for proc in procs:
        _, err = proc.communicate(timeout=300)
        assert proc.returncode == 0, err
        assert "locked" not in err, err
    data = listing(repo, monkeypatch, capsys)
    found = by_id(data["jobs"])
    for n, (job, _) in enumerate(pairs):
        assert found[job]["state"] == "claimed", job
        assert found[job]["lease"]["session"] == f"s-{n}"
    reports = [u for u in data["usage"] if u["runner_job"] in {rj for _, rj in pairs}]
    assert len(reports) == WORKERS
    assert sum(decimal.Decimal(u["usd"]) for u in reports) == decimal.Decimal("5.00")
