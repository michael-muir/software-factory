# 0031 · A halt kills the command's session on POSIX and its Job Object on Windows

Status: Proposed · Date: 2026-11-19 · Epic: E16

## Context

At a cap, the daemon must kill the job's whole process tree. That includes a grandchild whose parent has already exited (E16 AC-17), and it must happen within 10 seconds on Ubuntu, macOS and Windows. Agent command lines and builds start deep trees: shells, compilers, test workers, language servers.

The gate already kills a tree on timeout (`gate.py` `_execute`). On POSIX it uses `start_new_session` and `os.killpg`. On Windows it uses `CREATE_NEW_PROCESS_GROUP` and `taskkill /T /F`. `taskkill /T` walks the tree by parent process id, so it can't find a process whose parent has exited. Windows has no process groups to signal.

The Windows answer is a Job Object: every process created inside one stays inside it, and `TerminateJobObject` ends them all. The standard library reaches it through `ctypes` (`kernel32`). A process can only be put into a job after it exists, so there's a race if the command starts children before it's assigned. `subprocess` can't start a process suspended and then resume it, because it doesn't expose the thread handle. GitHub's Windows runners already run jobs inside a Job Object, and Windows 8 and later allow nested jobs.

## Decision

- **POSIX (Ubuntu, macOS):** each command starts with `start_new_session=True`. A halt sends `SIGKILL` to its process group with `os.killpg`. That reaches orphaned grandchildren too, because they keep their process group.
- **Windows:** each command runs under a small host, `run.py _host`, started with `CREATE_NEW_PROCESS_GROUP` (so the daemon's Ctrl+C doesn't reach it) and `stdin` as a pipe:
  1. The daemon creates a Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.
  2. It assigns the host to the job, then writes one line to the host's stdin.
  3. Only then does the host start the real command, with no shell and `stdin` set to `DEVNULL`. It waits for the command and exits with its exit code.

  Everything the command starts is born inside the job. A halt calls `TerminateJobObject`. Breakaway isn't allowed, so no child can leave the job.

- **Fallback:** if the Job Object can't be created or assigned, the command still runs. A halt then uses `taskkill /T /F`, and the job record gets a warning that orphaned grandchildren may survive.
- **Output** goes straight to the command's log file, as an inherited file handle, not a pipe. The daemon never has to drain output, and a killed tree can't leave it blocked.
- **The tree code is the runner's own,** inside `run.py`. The gate keeps its own `_kill_tree`, and E16 doesn't change E05's code.

## Consequences

- AC-17 holds on all three OSes, including the orphan case. The tests prove it with process ids that a fixture writes to a file.
- On Windows, if the daemon dies, its job handles close, and `KILL_ON_JOB_CLOSE` ends every command it was running. On POSIX, commands outlive a dead daemon. E22 has to handle both: on POSIX, it may find live processes behind a `running` record.
- A process on POSIX that calls `setsid` or `setpgid` itself leaves the group, and a halt can't reach it. That's a known limit, and no ordinary build or agent tool does it.
- Windows commands cost one more short-lived Python process each, for the host.
- Two tree-killing implementations exist, the gate's and the runner's. If they ever need to be one, a later ADR can move the runner's into a shared kit module.
