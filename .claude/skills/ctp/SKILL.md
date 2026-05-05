---
name: ctp
description: Show the latest Speckit worktree path and metadata
compatibility: Requires spec-kit project structure with .specify/ directory
metadata:
  author: github-spec-kit
  source: local:commands/ctp
user-invocable: true
disable-model-invocation: true
---

# Show Latest Speckit Worktree

Use this command when you want the latest Speckit worktree details without the "jump there" framing.

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

## Output

Parse the JSON result and report:

- `WORKTREE_PATH`
- `BRANCH_NAME`
- `BASE_BRANCH`
- `SOURCE`

If the current working directory already equals `WORKTREE_PATH`, say the user is already in the correct worktree.

Otherwise, state:

- the resolved worktree path
- the branch name
- the base branch
- whether the result came from the recorded handoff state or the worktree-root fallback
- that `/ct` is the shorter jump helper

## Graceful Degradation

If no recent Speckit worktree can be resolved:
- Return the helper error message
- Do not invent a fallback path
