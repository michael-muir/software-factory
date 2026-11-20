---
name: retro
description: Looks across finished jobs for failures that recur, and proposes a check or standard for each as a draft spec. Use when a milestone or a batch of jobs finishes, or the same finding shows up twice.
---

# Retro

Used by: `retro`.

## When to use

- A milestone or a batch of jobs has finished.
- The same kind of finding, failed gate or escalation has appeared in two or more jobs.

## Steps

1. Collect the findings, failed gate runs and escalations from the finished jobs' task files and handoffs in `.agentic/`.
2. Group them by kind. A pattern is the same kind of finding in two or more jobs, not a one-off.
3. For each pattern, choose the cheapest check that would have caught it: a gate check, a standards rule, a template field or a skill step.
4. Write each proposal as a **Draft** spec from `.factory/workflow/templates/spec.md`, citing the findings it comes from, and run `python .factory/workflow/docs.py check`.
5. Hand the drafts to a human for approval (skill: handoff). Don't change gates, standards or templates yourself.

## Done when

- Each proposal cites at least two findings or failures from different jobs.
- Each proposal is a Draft spec that passes `docs.py check`.
- Nothing outside the drafts changed.
