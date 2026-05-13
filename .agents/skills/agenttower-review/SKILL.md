---
name: "agenttower-review"
description: "Run a pre-PR or PR-style code review for AgentTower changes against a chosen git base, usually origin/main. Use when the user asks to review a feature branch, review before opening a PR, compare against main, or check correctness, regressions, and missing tests."
---

# agenttower-review

Use this skill for AgentTower code review work.

This is a review workflow, not an implementation workflow.

## Review intent

Review the current branch against a git base and look for:
- correctness bugs
- regressions
- contract/spec mismatches
- missing or weak tests on changed behavior
- risky edge cases introduced by the diff

Prefer no findings over weak findings.

## Base selection

Default base:
- `origin/main`

If the user names a different base branch, use that instead.

If the user provides a specific merge-base commit, use it directly for the diff.

## Commands

Start with:

```bash
git rev-parse --abbrev-ref HEAD
git status --short --branch
git diff --stat <BASE>...HEAD
git diff --unified=0 <BASE>...HEAD
```

If the user gave a merge-base commit instead of a branch, use:

```bash
git diff --stat <MERGE_BASE>
git diff --unified=0 <MERGE_BASE>
```

Use `rg` to inspect touched code and tests after the diff identifies hotspots.

## Review focus

1. Read the changed code first.
2. Trace any changed behavior into:
   - state/schema helpers
   - CLI or socket contracts
   - lifecycle/audit surfaces
   - tests covering the changed code
3. Check whether the branch matches the relevant feature spec when the feature is part of Speckit work.
4. If practical, run focused validation on the touched areas rather than defaulting immediately to the whole suite.

## Output rules

- Respond in concise Markdown unless the user explicitly asked for another format.
- If a review UI supports inline comments, use inline comments only for discrete actionable issues.
- Lead with findings, ordered by severity.
- If there are no actionable issues, say so directly and briefly.

## AgentTower-specific checks

When reviewing this repo, pay extra attention to:
- daemon transaction boundaries
- SQLite commit vs post-commit side effects
- Unix socket permission and peer-uid behavior
- tmux/container identity assumptions
- carried-over obligations from earlier features
- CLI text/JSON contract drift
- test coverage for lifecycle and degraded paths

## Example asks

- `Use agenttower-review on this branch before I open a PR`
- `Review FEAT-008 against origin/main`
- `Review changes against 008-event-ingestion-follow`
- `Do a PR-style review on this branch`
