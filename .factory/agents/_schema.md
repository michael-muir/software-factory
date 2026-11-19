# Agent file format

Each role is one Markdown file, `.factory/agents/<folder>/<name>.md`: core roles in `core/` (E09) and domain experts in `domains/` (E29). The file starts with TOML front matter between `+++` lines, the same as the state files (ADR 0014). Files whose names start with `_`, like this one, aren't roles. Check every role with `python .factory/agents/agents.py check`. The gate and `install.py check` run the same validation.

Copy `_template.md` to start a new role.

## Keys

| Key              | Type            | Rule                                                                                               |
| ---------------- | --------------- | -------------------------------------------------------------------------------------------------- |
| `name`           | string          | Lowercase letters, digits and hyphens. It must match the file name, and no two roles may share it. |
| `title`          | string          | The role's display name. Must not be empty.                                                        |
| `summary`        | string          | One line on what the role does. Must not be empty.                                                 |
| `model_hint`     | string          | One of the model hints below.                                                                      |
| `different_from` | string          | Another role's `name` when `model_hint` is `different-from`, and `""` otherwise.                   |
| `tools`          | list of strings | At least one tool from the vocabulary below, each listed once.                                     |
| `scope`          | table           | Optional. Narrows tools, using the scope keys below.                                               |

## Tools

A role can use only the tools it lists. The hook (E03/T3) blocks every other call.

| Tool     | Means                    |
| -------- | ------------------------ |
| `read`   | read a file              |
| `search` | find files or text       |
| `edit`   | change an existing file  |
| `write`  | create or replace a file |
| `run`    | run a shell command      |
| `web`    | fetch or search the web  |

## Scope keys

| Key     | Narrows            | Rule                                                                                                                                                                                                                                                      |
| ------- | ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `write` | `edit` and `write` | A non-empty list of repo-relative globs using `/`. `*` matches within one path segment, and `**` matches any depth. No absolute paths, `\` or `..`. The role must list `edit` or `write`. When `write` is unset, the role can write anywhere in the repo. |
| `run`   | `run`              | A non-empty list of command prefixes, matched on whole words. When it's set, commands that contain shell control characters (`;`, `&`, `\|`, `` ` ``, `$(`, `>`, `<`, a newline) are blocked. The role must list `run`.                                   |

Locked test files (`.agentic/locks/`) can't be edited or written by any role, whatever its scope.

## Model hints

The model router (E20) maps these hints to real models.

| Hint             | Means                                                                                                                                   |
| ---------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `strong`         | The most capable model available, for work where quality matters most.                                                                  |
| `any`            | Any model that can follow the role. The router may choose a cheaper one.                                                                |
| `different-from` | A model from a different vendor than the one the `different_from` role used. Reviewers use it, so the author never grades its own work. |

## Body

The body must have these headings, in any order: `## Scope`, `## Inputs` and `## Outputs`.
