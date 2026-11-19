# Fixture run: retro

Retro follows the skill once over two finished jobs in `before/`.

1. Collected the findings from `.agentic/tasks/`: E05-T1 F1 and E06-T2 F1, both major and fixed.
2. Grouped them: both are a missing changelog entry for a user-facing change. That's two jobs, so it's a pattern.
3. The cheapest check that would have caught both is a gate check on the diff.
4. Wrote a Draft spec, `docs/specs/E07-changelog-check.md`, citing both findings. `docs.py check`: no problems.
5. Handed the draft to the product owner for approval. Nothing else changed.
