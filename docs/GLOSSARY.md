# Glossary

The shared vocabulary of this project, so that people, agents and later sessions mean the same thing by the same word. Add terms as they come up, and keep each meaning to a sentence or two.

| Term       | Meaning                                                                                                                                                                                                             |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Gate       | The pass-or-fail check that runs format, lint, types, build, tests, coverage and mutation: `python .factory/gates/gate.py`. The same gate runs locally, in the git hooks and in CI.                                 |
| Profile    | The set of commands the gate runs for one stack, such as Python or TS/JS, in `.factory/gates/profiles/*.toml`. It's picked by marker files like `pyproject.toml`.                                                   |
| Kit        | The Software Factory files installed into `.factory/`: tracked in its manifest and refreshed by upgrades.                                                                                                           |
| Slice      | One small, vertical piece of an epic that is specified, tested, built and merged on its own. Each slice has a task file.                                                                                            |
| Handoff    | A note in `.agentic/handoffs/` that passes a task's context to the next session: what's done, what's next, and open questions.                                                                                      |
| Track      | How much process a change gets: `full`, `lite` or `pass-through`, for example a dependency bump.                                                                                                                    |
| Phase      | Where the active work is: spec, design, test, build, gate, review, docs, ship or learn.                                                                                                                             |
| Task file  | One file per slice in `.agentic/tasks/`, holding its status, review round and findings.                                                                                                                             |
| ADR        | An Architecture Decision Record in `docs/adr/`: one decision, why it was made, and what follows from it.                                                                                                            |
| Job        | One piece of work, such as a request on the full track, with its own record in `<git-common-dir>/factory/work/`. It's made and claimed with `.factory/control/jobs.py`, and its runner jobs and tasks belong to it. |
| Runner job | An E16 job: a worktree and the commands run in it by `.factory/runner/run.py`. It belongs to the job whose tasks hold its `--task`.                                                                                 |
| Lease      | A session's claim on a job, for `jobs.lease_minutes`, kept alive by heartbeats. Only the holder may change the job, and a lease that runs out means the job crashed and anyone may resume it.                       |
