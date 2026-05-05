---
name: ct
description: Resolve the latest Speckit worktree jump target
compatibility: Requires spec-kit project structure with .specify/ directory
metadata:
  author: github-spec-kit
  source: local:commands/ct
user-invocable: true
disable-model-invocation: true
---

# Resolve Latest Speckit Worktree

Use this command as the terse "take me to the current Speckit worktree" helper after `/speckit.specify`.

## Prerequisites

- Verify Git is available by running `git rev-parse --is-inside-work-tree 2>/dev/null`
- If Git is not available, output a warning and stop:
  ```
  [specify] Warning: Git repository not detected; cannot determine the latest Speckit worktree
  ```

## Execution

Run:

```bash
bash .specify/extensions/git/scripts/bash/get-last-worktree.sh --json
```

The helper resolves the latest worktree from the recorded handoff state when available. If no recorded handoff exists yet, it falls back to the configured Speckit worktree root and returns the newest worktree directory.

## Output

Parse the JSON result and focus on:

- `WORKTREE_PATH`
- `BRANCH_NAME`

If the current working directory already equals `WORKTREE_PATH`, say the user is already in the correct worktree.

Otherwise, state:

- the resolved worktree path
- that Claude slash commands cannot change the user’s current shell directory automatically
- the exact `cd <WORKTREE_PATH>` command
- that `/ctp` is the full detail command when they want path, branch, base branch, and source details

## Graceful Degradation

If no recent Speckit worktree can be resolved:
- Return the helper error message
- Do not invent a fallback path
