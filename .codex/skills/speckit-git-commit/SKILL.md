---
name: "speckit-git-commit"
description: "Codex wrapper for the Speckit git commit workflow."
---

# speckit-git-commit

Slash label: `/speckit.git.commit`.

Use `../../../.agents/skills/speckit-git-commit/SKILL.md` as the source workflow.

Rules:
- Read the source skill before doing anything else.
- Pass any text after `/speckit.git.commit` through as the original command input for the source skill.
- Execute the source skill exactly, including auto-commit behavior.
