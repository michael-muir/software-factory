# Changelog

All notable changes to Software Factory are recorded here, in the form of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The project follows [semantic versioning](https://semver.org/).

## [Unreleased]

- `pipeline.py approve <job> relock --task <id> --by <name> [--files f...]`: a relock the product owner approves while a job needs a human. The next `run` relocks every locked file plus the approved ones with `agents.py lock --replace ... --approved-by <name>`, after checking that only the approved files' hashes changed, commits `test(<task>): relock approved by <name>`, and reruns the stopped stage (E13).
- A Debugger that records an open blocker finding stops the job for a human at once, instead of spending the remaining gate retries (E13).
- `agents.py lock --approved-by NAME` records who approved a relock as `approved_by` in the lock record, and `agents.py check` accepts it (E03).
- Fixed: the default `pipeline.agent_command` puts `--` before `{prompt}`, so Claude Code's `--allowedTools` can't read the prompt as a tool name. A repo installed before this fix keeps its own `agent_command`: add `"--"` before `"{prompt}"` in `.agentic/config.toml` (E13).
- `pipeline.py check`: whether a full-track stage has passed, decided from a checkout's committed files (E13).
- `pipeline.py new`, `run`, `approve`, `reject`, `resume`, `cancel` and `status`: a full-track job driven through its plan stages under E18's lease, with the spec and design checkpoints (E13).
- `pipeline.py run` drives each task's slice too: the gate with Debugger retries, the six review sessions with their findings committed, the changelog entry and a second gate, the PR opened through GitHub's REST API or plain git once its body passes `check-pr --strict`, merge detection, the next slice from the fetched base, and the learn stage's summary and closing handoff (E13).
- `jobs.py resume`: a session claims a crashed job and gets what it needs to carry on: the job's record and lease, its branch and worktree, its runner jobs' last commands and cost, and its task and newest handoff. These are read from the worktree, or from the branch with the command that rebuilds the worktree if it has gone (E18).
