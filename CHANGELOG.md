# Changelog

All notable changes to Software Factory are recorded here, in the form of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The project follows [semantic versioning](https://semver.org/).

## [Unreleased]

- `pipeline.py check`: whether a full-track stage has passed, decided from a checkout's committed files (E13).
- `pipeline.py new`, `run`, `approve`, `reject`, `resume`, `cancel` and `status`: a full-track job driven through its plan stages under E18's lease, with the spec and design checkpoints (E13).
- `pipeline.py run` drives each task's slice too: the gate with Debugger retries, the six review sessions with their findings committed, the changelog entry and a second gate, the PR opened through GitHub's REST API or plain git once its body passes `check-pr --strict`, merge detection, the next slice from the fetched base, and the learn stage's summary and closing handoff (E13).
- `jobs.py resume`: a session claims a crashed job and gets what it needs to carry on: the job's record and lease, its branch and worktree, its runner jobs' last commands and cost, and its task and newest handoff. These are read from the worktree, or from the branch with the command that rebuilds the worktree if it has gone (E18).
