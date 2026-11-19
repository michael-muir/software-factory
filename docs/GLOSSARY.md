# Glossary

The shared vocabulary of this project, so that people, agents and later sessions mean the same thing by the same word. Add terms as they come up, and keep each meaning to a sentence or two.

| Term      | Meaning                                                                                                                                                                             |
| --------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Gate      | The pass-or-fail check that runs format, lint, types, build, tests, coverage and mutation: `python .factory/gates/gate.py`. The same gate runs locally, in the git hooks and in CI. |
| Profile   | The set of commands the gate runs for one stack, such as Python or TS/JS, in `.factory/gates/profiles/*.toml`. It's picked by marker files like `pyproject.toml`.                   |
| Kit       | The Software Factory files installed into `.factory/`: tracked in its manifest and refreshed by upgrades.                                                                           |
| Slice     | One small, vertical piece of an epic that is specified, tested, built and merged on its own. Each slice has a task file.                                                            |
| Handoff   | A note in `.agentic/handoffs/` that passes a task's context to the next session: what's done, what's next, and open questions.                                                      |
| Track     | How much process a change gets: `full`, `lite` or `pass-through`, for example a dependency bump.                                                                                    |
| Phase     | Where the active work is: spec, design, test, build, gate, review, docs, ship or learn.                                                                                             |
| Task file | One file per slice in `.agentic/tasks/`, holding its status, review round and findings.                                                                                             |
| ADR       | An Architecture Decision Record in `docs/adr/`: one decision, why it was made, and what follows from it.                                                                            |
