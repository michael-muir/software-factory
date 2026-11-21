# 0042 · A role session is a templated command, held by an allow-list from its card and by the E03 hook

Status: Accepted · Date: 2026-11-21 · Epic: E13

## Context

Each stage's role runs headless, with no person there to answer permission prompts. Claude Code comes first (spec decision), but the runtime must stay swappable. The product owner ruled out `bypassPermissions` for security (21 Nov 2026): a role has to be held by two layers. Claude Code's own permissions (code.claude.com/docs/en/permissions and /headless) work like this:

- `--allowedTools` takes rules such as `Read` or `Bash(git diff *)`. A space before the trailing `*` gives prefix matching, and `:*` is an older equivalent.
- A compound command must match a rule in each part.
- `--permission-mode acceptEdits` approves file edits inside the working directory.
- `--permission-prompts none` denies anything else that would prompt, and tells Claude not to retry.

## Decision

- **The command is `pipeline.agent_command`,** a list with three placeholders, each a whole element: `{role}`, `{allowed_tools}` and `{prompt}`. The default is:

  ```text
  claude -p --agent {role} --output-format json --permission-mode acceptEdits --permission-prompts none --allowedTools {allowed_tools} {prompt}
  ```

  A prompt is always one argument, whatever it holds.

- **The allow-list is generated from the role's card,** through E12's Claude Code tool names (`agents.CLAUDE_CODE_AGENT_TOOLS`).
  - A role with `run` and no `[scope].run` gets `Bash` and `PowerShell`.
  - A role with run scopes gets `Bash(<prefix> *)` and `PowerShell(<prefix> *)` for each prefix, and never a bare shell rule.
- **Each session runs with `FACTORY_ROLE=<role>`,** so E03's `PreToolUse` hook (E12's generated settings) checks every call against the card and the locks.
- **These layers apply, outermost first:**
  1. E16's caps.
  2. Claude Code's permissions: the agent file's `tools`, `acceptEdits`, the allow-list, and denying everything else.
  3. The E03 hook.
- **Cost comes from the JSON output's `total_cost_usd`** and goes to `run.py usage`. Output without it is a warning, not a failure, so a template for another tool still works.

## Consequences

- A reviewer can't edit files or run anything but the gate, `state.py` and read-only git, even if the hook were missing.
- The allow-list and the hook come from the same card, so they can't disagree about which tools a role has. A test pins the lists.
- Another runtime needs only a new template, and ideally a way to read its cost. Copilot's and Cursor's command lines aren't built in yet.
- The default depends on Claude Code v2.1.259 or later (`--permission-prompts`). A repo on an older version changes the template in its config.
