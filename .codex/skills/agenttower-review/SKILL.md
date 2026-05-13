---
name: "agenttower-review"
description: "Codex wrapper for the AgentTower pre-PR review workflow."
---

# agenttower-review

Use `../../../.agents/skills/agenttower-review/SKILL.md` as the source workflow.

Rules:
- Read the source skill before doing anything else.
- If the user names a base branch or merge-base commit, use it.
- Otherwise default to `origin/main`.
- Execute the source skill exactly, including the review-first posture.
