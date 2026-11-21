# 0050 · There is one job, owned by the job index: a TOML record in the git common directory, with sidecar files for other epics

Status: Proposed · Date: 2026-11-21 · Epic: E18

## Context

E18 needs a record of each piece of work that every session and every worktree can see. E13's pipeline needed one too, and its draft kept its own record under `factory/pipeline/`. The product owner decided that there is **one job, owned by E18**. E18's record, its id and its lease are the job. E13 keeps its stage, approval and PR details in a file beside the record, keyed by the same id (E18 spec, change note). Files stay the source of truth, and the SQLite index is derived from them.

Several processes create and change jobs: people at a shell, E13's driver, and later the router (E19). Only the standard library is allowed, the code must work on three OSes, and nothing may be tracked by git. ADR 0030 already has a lock-free way to reserve names and publish files under `<git-common-dir>/factory/`.

The options were:

- A record inside each branch's `.agentic`. A branch can't see the others, so one session couldn't find every job.
- Records only in SQLite. That breaks "state lives in files", and losing the database would lose the jobs.
- **One TOML file per job in the git common directory**, beside the runner's files.

## Decision

- **A job is `<git-common-dir>/factory/work/<id>.toml`:** a version, id, title, track, phase, status, task, tasks, branch, worktree, owner, times, and a `[[claims]]` audit trail. It is published with a temp file and `os.replace`.
- **Ids** match `[a-z0-9][a-z0-9-]{0,29}`, at most 30 characters, so a runner id built from a job id fits E16's 40. They are reserved with `os.mkdir(work/.ids/<id>)`. A generated id is `job-<n>`.
- **A task belongs to one live job.** That is enforced by an exclusive create in `work/.tasks/`, and released when the job is done or cancelled. Runner jobs belong to the job whose `tasks` holds their `--task`.
- **Sidecars** are the extension point: `work/<id>.<name>.toml`, where `<name>` matches `[a-z][a-z0-9]{0,19}`. The owning epic writes it, atomically, while holding the job's lease, through `jobs.write_sidecar`. `jobs.py` never reads or validates a sidecar's contents. It lists sidecars and shows their paths. E13's is `pipeline`.
- **A small Python API** (`new_job`, `read_job`, `set_job`, `claim`, `beat`, `release`, `sidecar_path`, `write_sidecar`) is the contract that E13 and E19 call. Tests pin it.

## Consequences

- E13 and E18 never disagree about what a job is: there is one id and one lease. E13 has no record of its own to keep in step.
- Any epic can add its own details about a job without changing E18's schema. The price is that the index doesn't understand them: a query on pipeline stages needs E13's own reader, or a later migration.
- A job's record is visible from every worktree, and never committed. Work that should be reviewed still lives in each branch's `.agentic`, as before.
- Two reservation folders, `.ids` and `.tasks`, sit beside the records. `rebuild` reads the records and never the reservations.
