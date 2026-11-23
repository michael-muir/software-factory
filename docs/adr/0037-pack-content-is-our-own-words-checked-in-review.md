# 0037 · Pack content is in our own words and leaves tool-enforced rules to the gate; review checks this, tests check the shape

Status: Accepted · Date: 2026-11-21 · Epic: E11

## Context

The packs draw on guides under different terms. PEP 8 is public domain. The Google guides are CC-BY. Uber Go is Apache-2.0 _(corrected 21 Nov 2026, T2: this said CC-BY 4.0; the guide's LICENSE file is Apache-2.0)_. StyleCop is MIT. Epic's Unreal standard has no open licence. The PO chose rules in our own words, each linking to its source section, with each source and its licence named in the front matter. The PO also chose 15–30 rules per pack that a reviewer must judge, with nothing the formatter or linter already enforces. Neither "our own words" nor "not tool-enforced" can be tested without the source texts and every possible linter configuration.

## Decision

- **Tests check the shape** (E11 AC-01 to AC-06). They check:
  - the front matter and the table
  - 15–30 rules in force
  - every severity used
  - every Source link starting with the URL of a source named in the front matter
- **Review checks the content.** The PR that adds or changes a pack says how it checked both rules:
  - **Own words:** a rule is one or two sentences we wrote, and the Why/example cell is our own example.
  - **Not tool-enforced:** no rule duplicates the stack's formatter or default linter rules. The `## Left to the tools` section names those tools, and the gate's format and lint checks enforce them.
- **Severity follows one scale in every pack:**
  - `blocker`: unsafe or incorrect, such as swallowed errors or undefined behaviour
  - `major`: makes the code hard to change or misleading, such as names that lie or hidden global state
  - `minor`: hurts readability, such as missing docstrings or unclear test names
- **A guide with no open licence is cited, never quoted.** The Unreal pack links Epic's pages and states their terms in its front matter.

## Consequences

- The kit can ship under Apache-2.0 with clear attribution, and each rule leads back to its source.
- Severities mean the same in every language. A finding normally takes its rule's severity, and the skill tells the reviewer to explain any other choice in the summary.
- Content quality relies on review, the same as code. E28's retro loop can later propose new or retired rules from recurring findings.
