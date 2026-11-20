---
name: lock-tests
description: Locks a slice's failing tests with agents.py so they can't change after the implementation starts, and handles the rare relock. Use when tests are written and failing, before any implementation commit, or when a locked test needs a change.
---

# Lock tests

Used by: `test-designer`.

## When to use

- A slice's tests are written and fail for the right reason, and nothing has been implemented yet.
- A locked test has a real mistake. That needs a relock, and a relock needs a human.

## Steps

1. Format and lint the test files first. A lock records exact contents, so a later reformat would break it.
2. Lock them: `python .factory/agents/agents.py lock <task> <file>...`. The task must have a task file in `.agentic/tasks/`.
3. Check the record in `.agentic/locks/<task>.toml`, and run `python .factory/agents/agents.py check`.
4. Commit the tests and the lock record in the same `test(...)` commit, before any implementation.
5. If a locked test must change, stop and ask a human. Only with their approval, fix it in its own `test(...)` commit, saying "expectations unchanged" (or what changed and why), and relock with `python .factory/agents/agents.py lock --replace <task> <file>...`. Flag the relock in the PR.

## Done when

- `.agentic/locks/<task>.toml` lists every test file of the slice, and `agents.py check` passes.
- The gate reports `Locks: N locked files, none changed`.
- Any relock was approved by a human and is called out in the PR.
