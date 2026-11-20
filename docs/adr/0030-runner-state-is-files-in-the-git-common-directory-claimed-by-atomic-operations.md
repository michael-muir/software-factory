# 0030 · Runner state is files in the git common directory, claimed by atomic file operations

Status: Proposed · Date: 2026-11-19 · Epic: E16

## Context

The product owner chose a file queue on the machine, one TOML record per job under the git directory, and worktree claims made by atomic create (E16 spec, decisions in force). Several processes touch these files at once: `submit`, `send`, `usage` and `cancel` from any shell, and one or more daemons. They run on Ubuntu, macOS and Windows, and only the standard library is allowed. SQLite (E18) isn't here yet, and file locks (`fcntl`, `msvcrt`) behave differently on each OS and are easy to leave held after a crash.

Every process must find the same files, whether it runs in the main checkout or in a job's worktree. Nothing must ever be tracked by git.

The operations the standard library offers that are atomic on all three OSes are:

- `os.mkdir`, which fails if the folder exists;
- `os.open` with `O_CREAT | O_EXCL`, which fails if the file exists;
- `os.rename`, which on every OS fails if the source has gone, and on Windows also fails if the target exists;
- `os.replace` within one folder, which swaps a file whole.

Appending with `O_APPEND` isn't safe across processes on Windows, because the C runtime emulates it with a seek and then a write.

## Decision

- **All runner state lives under `<git-common-dir>/factory/`,** found with `git rev-parse --path-format=absolute --git-common-dir`. Git never tracks it, and every worktree of the repo resolves the same folder.
- **Each state change has one writer, or uses an atomic operation:**

| Step                                 | Operation                                                                                                                                                                           |
| ------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Reserve a job id (`submit`)          | `os.mkdir(jobs/<id>)`. If it exists, the id is taken (exit 2).                                                                                                                      |
| Queue a request                      | Write `queue/.tmp-<random>`, then `os.rename` it to `queue/<id>.toml`.                                                                                                              |
| Claim a request (daemon or `cancel`) | `os.rename(queue/<id>.toml, jobs/<id>/request.toml)`. Only one rename can succeed. The loser sees `FileNotFoundError` and moves on.                                                 |
| Claim a worktree path                | Create `claims/<key>` with `O_CREAT \| O_EXCL`, holding the job id. `<key>` is the SHA-256 of the case-folded, resolved absolute path.                                              |
| Send a command                       | Create `jobs/<id>/commands/<nnnn>.toml` with `O_EXCL`, taking the next free number.                                                                                                 |
| Close, cancel                        | Create a `closed` or `cancel` marker file in `jobs/<id>/`.                                                                                                                          |
| Report usage                         | Create a new file `jobs/<id>/usage/<time>-<random>.usd` holding one decimal amount. The total is the sum of the files.                                                              |
| Write the record                     | Only the claiming process writes `jobs/<id>/job.toml`: write a temp file in the same folder, then `os.replace`. On Windows, retry for up to a second while a reader holds the file. |
| Stop the daemons                     | Write `factory/stop` holding a time. A daemon stops when it sees a stop time later than its own start.                                                                              |

- **The record is TOML,** written by a small emitter inside `run.py`, and read with `tomllib`. Amounts are `decimal.Decimal`, so reported cents add up exactly.
- **Intake sits behind one small interface:** list the pending requests, claim one, read it. E23 can add a transport that feeds the same queue without touching the job loop.

## Consequences

- No locks: a crash can't leave a lock held. What a crash does leave (a `running` record, a claim, a worktree) is E22's to repair. Each of them is a plain file that names its job.
- A worktree path can never be claimed twice. The claim key folds case, so two paths that differ only by case can't both be claimed even on Linux. That costs nothing, because job ids are lower case.
- Usage reports never lose an update, and each report stays on disk for audit (E21).
- Many small files per job. Listing a job's state means reading a folder, which is cheap at the scale of one machine. E18's index can be built from these files.
- Every `run.py` command needs `git` on the PATH and a repo with at least one commit.
