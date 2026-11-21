"""E16/T3: killing a command's whole process tree, on Ubuntu, macOS and Windows.

Covers E16 AC-17. Expectations come from the E16 spec, ADR 0031 and the design note ("Process
trees"), not from the implementation. The tree tests start real processes on every OS: on
Windows that runs each command under `run.py _host` inside a Job Object, nested in the one
GitHub's runner already puts the job in, and the orphan case is the one `taskkill /T` can't
reach. The Job Object's calls are also checked against a fake kernel32, so they're tested on
every OS.
"""

from __future__ import annotations

import ctypes
import io
import os
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

import run as runner
from tests._daemon import until
from tests._halt import GONE_S, alive, all_gone, read_pids, reap, tree_argv

WINDOWS = sys.platform == "win32"

# Win32 constants, from the Windows SDK's winnt.h.
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x0800
JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK = 0x1000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100


@pytest.fixture
def started() -> Iterator[list[int]]:
    """Process ids to kill at the end, whatever the test did."""
    pids: list[int] = []
    yield pids
    reap(pids)


def start(tmp_path: Path, argv: list[str], name: str = "cmd") -> tuple[Any, Path]:
    log = tmp_path / "logs" / f"{name}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    tree = runner.start_command(argv, tmp_path, dict(os.environ), log)
    return tree, log


def start_tree(
    tmp_path: Path, started: list[int], name: str, *, orphan: bool = False
) -> tuple[Any, dict[str, int]]:
    tree, _ = start(tmp_path, tree_argv(tmp_path / name, orphan=orphan), name)
    pids = read_pids(tmp_path / name)
    started.extend(pids.values())
    return tree, pids


# --- the tree is gone within 10 seconds -------------------------------------------------------


@pytest.mark.ac("E16-AC-17")
def test_a_halt_kills_the_command_its_child_and_its_grandchild(
    tmp_path: Path, started: list[int]
) -> None:
    tree, pids = start_tree(tmp_path, started, "tree")
    assert all(alive(pid) for pid in pids.values()), pids
    assert tree.poll() is None

    began = time.monotonic()
    tree.kill()
    assert all_gone(pids.values()), {role: alive(pid) for role, pid in pids.items()}
    assert time.monotonic() - began < GONE_S
    assert tree.poll() is not None, "a killed command has an exit code"
    assert tree.warnings == [], "nothing fell back: a Job Object on Windows, a session on POSIX"


@pytest.mark.ac("E16-AC-17")
def test_a_halt_kills_an_orphaned_grandchild(tmp_path: Path, started: list[int]) -> None:
    tree, pids = start_tree(tmp_path, started, "orphan", orphan=True)
    assert until(lambda: not alive(pids["child"]), timeout=30), "the child should have exited"
    assert alive(pids["command"])
    assert alive(pids["grandchild"]), "the grandchild is left running without its parent"

    began = time.monotonic()
    tree.kill()
    assert all_gone([pids["command"], pids["grandchild"]]), {
        role: alive(pid) for role, pid in pids.items()
    }
    assert time.monotonic() - began < GONE_S
    assert tree.warnings == []


@pytest.mark.ac("E16-AC-17")
def test_a_halt_leaves_another_jobs_tree_and_the_daemon_alone(
    tmp_path: Path, started: list[int]
) -> None:
    first, first_pids = start_tree(tmp_path, started, "first", orphan=True)
    second, second_pids = start_tree(tmp_path, started, "second", orphan=True)
    assert until(lambda: not alive(first_pids["child"]), timeout=30)
    assert until(lambda: not alive(second_pids["child"]), timeout=30)

    first.kill()
    assert all_gone([first_pids["command"], first_pids["grandchild"]])
    assert alive(second_pids["command"]), "another job's command is untouched"
    assert alive(second_pids["grandchild"]), "and so is its orphaned grandchild"
    assert second.poll() is None
    assert alive(os.getpid()), "the daemon itself is untouched"

    second.kill()
    assert all_gone([second_pids["command"], second_pids["grandchild"]])


# --- a command still runs as before through the tree --------------------------------------------


@pytest.mark.ac("E16-AC-17")
def test_a_finished_command_reports_its_own_exit_code(tmp_path: Path) -> None:
    script = "import sys; print('from the command'); sys.exit(3)"
    tree, log = start(tmp_path, [sys.executable, "-c", script])
    assert until(lambda: tree.poll() is not None, timeout=60)
    assert tree.poll() == 3
    assert "from the command" in log.read_text(encoding="utf-8")


@pytest.mark.ac("E16-AC-17")
def test_a_command_that_cannot_start_exits_127_with_the_reason_in_its_log(tmp_path: Path) -> None:
    tree, log = start(tmp_path, ["no-such-program-e16-t3", "x"])
    assert until(lambda: tree.poll() is not None, timeout=60)
    assert tree.poll() == 127
    assert "no-such-program-e16-t3" in log.read_text(encoding="utf-8", errors="replace")
    tree.kill()  # killing a finished command is harmless


# --- the host (ADR 0031): the command starts only after the daemon says go ----------------------


def host(monkeypatch: pytest.MonkeyPatch, stdin: str, argv: list[str]) -> int:
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    return runner.main(["_host", "--", *argv])


@pytest.mark.ac("E16-AC-17")
def test_the_host_runs_its_command_after_the_go_line_and_exits_with_its_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "ran.txt"
    script = (
        "import sys; open(sys.argv[1], 'w').write('stdin=' + repr(sys.stdin.read())); sys.exit(4)"
    )
    code = host(monkeypatch, "go\n", [sys.executable, "-c", script, str(out)])
    assert code == 4
    assert out.read_text(encoding="utf-8") == "stdin=''", "the command's stdin is empty"


@pytest.mark.ac("E16-AC-17")
def test_the_host_never_runs_its_command_without_the_go_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "ran.txt"
    script = "import sys; open(sys.argv[1], 'w').write('ran')"
    code = host(monkeypatch, "", [sys.executable, "-c", script, str(out)])
    assert code != 0
    assert not out.exists()


@pytest.mark.ac("E16-AC-17")
def test_the_host_exits_127_when_its_command_cannot_start(
    monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    code = host(monkeypatch, "go\n", ["no-such-program-e16-t3"])
    assert code == 127
    captured = capfd.readouterr()
    assert "no-such-program-e16-t3" in captured.out + captured.err


# --- Windows: the Job Object, and the taskkill fallback ------------------------------------------


@pytest.mark.ac("E16-AC-17")
@pytest.mark.skipif(not WINDOWS, reason="the Job Object and taskkill are Windows only")
def test_without_a_job_object_a_halt_falls_back_to_taskkill_with_a_warning(
    tmp_path: Path, started: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object, **kwargs: object) -> object:
        raise OSError("AssignProcessToJobObject failed")

    monkeypatch.setattr(runner, "JobObject", refuse)
    tree, pids = start_tree(tmp_path, started, "fallback")
    [warning] = tree.warnings
    assert "taskkill" in warning
    assert "grandchild" in warning, "the warning says orphaned grandchildren may survive"

    tree.kill()
    assert all_gone(pids.values()), "taskkill /T still ends a tree whose parents are alive"


class FakeKernel32:
    """kernel32 as the Job Object code calls it: every call is recorded; one name can fail."""

    def __init__(self, fail: str = "") -> None:
        self.fail = fail
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.handles: list[int] = []

    def __getattr__(self, name: str) -> Callable[..., int]:
        if name.startswith("_"):
            raise AttributeError(name)

        def call(*args: Any) -> int:
            self.calls.append((name, args))
            if name == self.fail:
                return 0
            if name in ("CreateJobObjectW", "OpenProcess"):
                handle = 1000 + len(self.handles)
                self.handles.append(handle)
                return handle
            return 1

        return call

    def named(self, name: str) -> list[tuple[Any, ...]]:
        return [args for called, args in self.calls if called == name]

    def closed(self) -> set[int]:
        return {_int(args[0]) for args in self.named("CloseHandle")}


def _int(value: Any) -> int:
    """A handle passed as an int, a c_void_p or a wintypes.HANDLE."""
    return int(getattr(value, "value", value) or 0)


def _struct(value: Any) -> Any:
    """The structure behind ctypes.byref(s), ctypes.pointer(s) or s itself."""
    if hasattr(value, "_obj"):
        return value._obj
    if hasattr(value, "contents"):
        return value.contents
    return value


@pytest.mark.ac("E16-AC-17")
def test_the_job_object_kills_on_close_allows_no_breakaway_and_holds_the_process() -> None:
    kernel32 = FakeKernel32()
    job = runner.JobObject(4321, kernel32=kernel32)
    assert len(kernel32.named("CreateJobObjectW")) == 1
    job_handle = kernel32.handles[0]

    [(handle, info_class, info, size)] = kernel32.named("SetInformationJobObject")
    assert _int(handle) == job_handle
    assert _int(info_class) == JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS
    limits = _struct(info).BasicLimitInformation.LimitFlags
    assert limits & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    assert not limits & JOB_OBJECT_LIMIT_BREAKAWAY_OK, "no child may leave the job"
    assert not limits & JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK
    assert _int(size) == ctypes.sizeof(_struct(info))

    [(access, _inherit, pid)] = kernel32.named("OpenProcess")
    assert _int(pid) == 4321
    assert _int(access) & PROCESS_SET_QUOTA and _int(access) & PROCESS_TERMINATE
    process_handle = kernel32.handles[1]
    [(assigned_job, assigned_process)] = kernel32.named("AssignProcessToJobObject")
    assert (_int(assigned_job), _int(assigned_process)) == (job_handle, process_handle)
    assert job_handle not in kernel32.closed(), "the job stays open while its command runs"

    job.terminate()
    [(terminated, _code)] = kernel32.named("TerminateJobObject")
    assert _int(terminated) == job_handle
    job.close()
    assert job_handle in kernel32.closed()


@pytest.mark.ac("E16-AC-17")
@pytest.mark.parametrize(
    "failing",
    ["CreateJobObjectW", "SetInformationJobObject", "OpenProcess", "AssignProcessToJobObject"],
)
def test_a_job_object_call_that_fails_raises_and_leaks_no_handle(failing: str) -> None:
    kernel32 = FakeKernel32(fail=failing)
    with pytest.raises(OSError, match=failing):
        runner.JobObject(4321, kernel32=kernel32)
    assert set(kernel32.handles) <= kernel32.closed(), "every handle opened was closed again"
