---
name: "agenttower-pr-review"
description: "Codex wrapper for the AgentTower GitHub PR review workflow."
---

# agenttower-pr-review

Use `../../../.agents/skills/agenttower-pr-review/SKILL.md` as the source workflow.

Rules:
- Read the source skill before doing anything else.
- Use the PR number or URL the user provided.
- If the user did not provide a PR reference, fall back to `agenttower-review`.
- Execute the source skill exactly, including review-thread comparison behavior.
