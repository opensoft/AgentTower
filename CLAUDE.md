<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan:
`specs/001-package-state-foundation/plan.md`.
<!-- SPECKIT END -->

# AgentTower Agent Context

AgentTower is a local-first Python CLI and daemon for coordinating tmux-based
AI agents inside Opensoft bench containers.

Read these project docs before creating or implementing specs:

- `docs/product-requirements.md`
- `docs/architecture.md`
- `docs/mvp-feature-sequence.md`

Spec Kit lives under `.specify/`. OpenSpec lives under `openspec/`.

## Spec Kit Workflow Rules

Follow this sequence for feature work. Use the slash-command spelling supported
by the current agent (`/speckit-specify` in Claude; `/speckit.specify` where
dot commands are installed), but keep the same order:

```text
/speckit.specify <description>   # from root checkout
cd <WORKTREE_PATH>                # or run /ct, then ct
/speckit.clarify                  # optional
/speckit.plan
/speckit.checklist <topic>        # optional, repeatable
/speckit.tasks
/speckit.analyze                  # optional

/speckit.implement
```

Before `/speckit.specify`, verify `pwd` is the root checkout and
`git rev-parse --abbrev-ref HEAD` is `main`. Do not run specify from a feature
worktree.

Before every later Spec Kit command, verify `pwd` is the intended feature
worktree and `git rev-parse --abbrev-ref HEAD` is the correct feature branch.
Use `ctp` or `.specify/extensions/git/scripts/bash/get-last-worktree.sh --json`
to confirm the recorded worktree path when available. If a command was run in
the wrong checkout, stop and repair the git/spec artifacts before continuing.

Do not go from plan to tasks without explicitly deciding whether a checklist is
needed. Run `/speckit.checklist <topic>` for any known quality gate or risk area
and repeat it for multiple topics when useful.

When tasks are deferred to a later feature, run `/speckit.taskstoissues` before
implementation and record the resulting issue links or IDs in the handoff.

MVP deployment is host-daemon first: `agenttowerd` runs on the host, bench
containers run thin `agenttower` clients over a mounted Unix socket, and there
is no network listener in MVP.
