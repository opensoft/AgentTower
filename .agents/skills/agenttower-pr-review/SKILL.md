---
name: "agenttower-pr-review"
description: "Review an AgentTower GitHub pull request end-to-end. Use when the user asks to review a PR by number or URL, compare code against the PR base branch, inspect Copilot or other review threads, or check whether a PR is ready to merge."
---

# agenttower-pr-review

Use this skill for AgentTower pull request review work.

This is a review workflow, not an implementation workflow.

## Review intent

Review a GitHub PR as a code reviewer would:
- inspect the PR diff against its actual base branch
- inspect existing review threads, including Copilot comments when present
- compare review comments against the current branch state
- identify correctness, regression, contract, and test-coverage issues
- determine whether the PR is ready to merge

Prefer no findings over weak findings.

## Required inputs

Prefer one of:
- PR number, for example `PR #10`
- PR URL

If the user does not provide a PR number or URL, fall back to branch review with `agenttower-review`.

## Commands

Start with PR metadata:

```bash
gh pr view <PR> --json url,baseRefName,headRefName,reviewDecision,latestReviews
```

Then inspect the code diff against the PR base:

```bash
git diff --stat origin/<BASE>...origin/<HEAD>
git diff --unified=0 origin/<BASE>...origin/<HEAD>
```

If the branch is already checked out locally, you may review from the local worktree instead:

```bash
git diff --stat origin/<BASE>...HEAD
git diff --unified=0 origin/<BASE>...HEAD
```

Inspect review threads when needed:

```bash
gh api graphql -f query='query { repository(owner:"opensoft", name:"AgentTower") { pullRequest(number:<PR>) { reviewThreads(first:100) { nodes { isResolved isOutdated path line comments(first:20) { nodes { author { login } body } } } } } } }'
```

Use `rg` to inspect touched code and tests after the diff identifies hotspots.

## Review focus

1. Read the changed code first.
2. Compare the current code against active review feedback:
   - unresolved GitHub review threads
   - Copilot comments
   - Sonar or CI signals if relevant to correctness
3. Distinguish:
   - already-fixed review comments
   - still-valid comments
   - new issues not mentioned in GitHub review
4. Check whether the PR matches the relevant feature spec when the work is part of Speckit feature delivery.
5. If practical, run focused validation on the touched areas rather than defaulting immediately to the whole suite.

## Output rules

- Respond in concise Markdown unless the user explicitly asked for another format.
- If a review UI supports inline comments, use inline comments only for discrete actionable issues.
- Lead with findings, ordered by severity.
- Then state merge readiness briefly.
- If there are no actionable issues, say that directly and briefly.

## AgentTower-specific checks

When reviewing this repo, pay extra attention to:
- daemon transaction boundaries
- SQLite commit vs post-commit side effects
- Unix socket permission and peer-uid behavior
- tmux/container identity assumptions
- lifecycle vs JSONL event-surface separation
- CLI text/JSON contract drift
- carried-over obligations from earlier features
- test coverage for degraded and reconciliation paths

## Example asks

- `Use agenttower-pr-review on PR #10`
- `Use $agenttower-pr-review to review PR #12 and compare against Copilot comments`
- `Is PR #8 ready to merge? Use agenttower-pr-review`
