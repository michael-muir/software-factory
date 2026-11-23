+++
name = "docs"
title = "Docs standards pack"
prefix = "DOC"
applies_to = ["*"]

[[sources]]
title = "Conventional Commits 1.0.0"
url = "https://www.conventionalcommits.org/"
licence = "CC-BY-3.0"

[[sources]]
title = "Google developer documentation style guide"
url = "https://developers.google.com/style/"
licence = "CC-BY-4.0"

[[sources]]
title = "Michael Nygard, Documenting Architecture Decisions"
url = "https://www.cognitect.com/blog/2011/11/15/documenting-architecture-decisions"
licence = "All rights reserved: cited, never quoted"

[[sources]]
title = "Software Factory docs"
url = "https://github.com/michael-muir/software-factory/blob/main/"
licence = "Apache-2.0"
+++

# Docs standards pack

Rules a reviewer judges in Markdown docs, ADRs, specs, PR bodies and commit messages. It applies to every change, because every change has a commit message. Each rule is in our own words and links the section of the source it comes from. Cite a rule by its id in a finding. Severity follows ADR 0037: `blocker` for unsafe or incorrect code, `major` for code that misleads or is hard to change, `minor` for readability.

## Left to the tools

The gate's format check (Prettier, for Markdown) and lint check (`docs.py check`, which runs in the gate) own the layout and the required parts of specs, design notes and ADRs. This pack doesn't repeat them: it covers what a reviewer has to judge.

## Rules

| Rule id | Severity | Rule                                                                                                                                     | Why/example                                                              | Source                                                                                                                                          |
| ------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| DOC-001 | blocker  | Never put secrets, tokens, passwords or personal data in docs, examples, commit messages or PR bodies.                                   | Git history keeps them after the file is fixed.                          | [Software Factory: threat-check skill](https://github.com/michael-muir/software-factory/blob/main/.factory/skills/threat-check/SKILL.md)        |
| DOC-002 | major    | A change to behaviour updates the docs that describe it, in the same PR.                                                                 | Docs that describe last month's behaviour mislead every reader.          | [Software Factory: Docs Writer role](https://github.com/michael-muir/software-factory/blob/main/.factory/agents/core/docs-writer.md)            |
| DOC-003 | major    | Commit subjects follow Conventional Commits (`type(scope): summary`). A breaking change says so with `!` or a `BREAKING CHANGE:` footer. | Release tooling and readers both depend on the type.                     | [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/)                                                                    |
| DOC-004 | major    | A commit holds one logical change, with a subject that says what changed.                                                                | Small commits are easy to review, revert and bisect.                     | [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/)                                                                    |
| DOC-005 | major    | An ADR records the context, the decision and its consequences. Once it's accepted it isn't rewritten: a new ADR supersedes it.           | The record shows why things are the way they are, including old reasons. | [Nygard: Documenting Architecture Decisions](https://www.cognitect.com/blog/2011/11/15/documenting-architecture-decisions)                      |
| DOC-006 | major    | A spec's acceptance criteria are numbered, and each names something a test can observe.                                                  | Untestable criteria can't be traced to evidence.                         | [Software Factory: spec-interview skill](https://github.com/michael-muir/software-factory/blob/main/.factory/skills/spec-interview/SKILL.md)    |
| DOC-007 | major    | Every PR body carries the evidence the template asks for: the gate report, the trace from each AC to its tests, and the findings.        | A reviewer can audit the PR without rerunning anything.                  | [Software Factory: PR evidence template](https://github.com/michael-muir/software-factory/blob/main/.factory/workflow/templates/pr-evidence.md) |
| DOC-008 | major    | Examples work as written, and placeholders are clearly marked as placeholders.                                                           | Readers copy examples, so a broken one spreads.                          | [Google style: Placeholders](https://developers.google.com/style/placeholders)                                                                  |
| DOC-009 | minor    | A doc says what's true now. History belongs in changelogs, ADRs and commit messages.                                                     | Readers want the current state, not the story of how it got there.       | [Software Factory: Docs Writer role](https://github.com/michael-muir/software-factory/blob/main/.factory/agents/core/docs-writer.md)            |
| DOC-010 | minor    | Write instructions in the second person and the present tense: "Run the gate".                                                           | Direct instructions are shorter and clearer.                             | [Google style: Second person](https://developers.google.com/style/person)                                                                       |
| DOC-011 | minor    | Use the active voice, so the sentence says who does what.                                                                                | "The gate rejects the change", not "the change is rejected".             | [Google style: Active voice](https://developers.google.com/style/voice)                                                                         |
| DOC-012 | minor    | Use sentence case in headings.                                                                                                           | One rule, applied everywhere, reads as one voice.                        | [Google style: Capitalization](https://developers.google.com/style/capitalization)                                                              |
| DOC-013 | minor    | Number steps that a reader follows in order. Use bullets otherwise.                                                                      | Numbers promise an order; bullets don't.                                 | [Google style: Lists](https://developers.google.com/style/lists)                                                                                |
| DOC-014 | minor    | Put code, commands, file names and identifiers in code font.                                                                             | The reader can tell exactly what to type.                                | [Google style: Code in text](https://developers.google.com/style/code-in-text)                                                                  |
| DOC-015 | minor    | Spell out an abbreviation on first use, unless every reader is sure to know it.                                                          | New readers aren't left guessing.                                        | [Google style: Abbreviations](https://developers.google.com/style/abbreviations)                                                                |
| DOC-016 | minor    | Link text says where the link goes. Never "click here".                                                                                  | Screen readers and skimmers read links on their own.                     | [Google style: Link text](https://developers.google.com/style/link-text)                                                                        |
