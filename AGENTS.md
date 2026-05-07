<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
<!-- SPECKIT END -->

# AgentTower Agent Context

AgentTower is a local-first Python CLI and daemon for coordinating tmux-based
AI agents inside Opensoft bench containers.

Read these project docs before creating or implementing specs:

- `docs/product-requirements.md`
- `docs/architecture.md`
- `docs/mvp-feature-sequence.md`

Spec Kit lives under `.specify/`. OpenSpec lives under `openspec/`.

## Claude Launch Rule

When starting a new Claude session for AgentTower bench work, always start it
with the `yolo` shell function from the bench user's `~/.zshrc`. Do not launch
raw `claude` directly. `yolo` is required because it starts Claude with the
expected bypass-permissions and teammate-mode flags for these tmux-driven
workflows.

If a Claude session was started without `yolo`, stop it and restart correctly
before continuing.

## Tmux Prompt Rule

When prompting Claude in a tmux pane, always submit the prompt with a carriage
return immediately after sending the text. Do not leave a prompt sitting in the
input buffer unsubmitted. If you use `tmux send-keys` to send prompt text, send
`C-m` in the same action or immediately after it, then verify the prompt was
actually submitted before waiting for output.

## Spec Kit Workflow Rules

Follow this sequence for feature work. Use the slash-command spelling supported
by the current agent (`/speckit-specify` in Claude; `/speckit.specify` where
dot commands are installed), but keep the same order:

```text
/speckit.specify <description>   # from root checkout
cd <WORKTREE_PATH>                # or run /ct, then ct
/speckit.clarify
/speckit.plan
/speckit.checklist <topic>        # decision required before tasks; repeatable when needed
/speckit.tasks
/speckit.analyze

/speckit.implement
```

Treat the full sequence above as mandatory by default. Do not skip `clarify`,
`plan`, `tasks`, `analyze`, or `implement` just because the feature appears
straightforward. Do not skip the checklist decision step at all. Only skip a
phase when the user explicitly approves the skip, a repository-specific rule
explicitly says to skip it, or that phase is already complete and still current
for the active feature in the correct worktree.

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
and repeat it for multiple topics when useful. Use your own judgment after each
checklist to decide whether a second topic-specific checklist is warranted
before tasks are generated.

When tasks are deferred to a later feature, run `/speckit.taskstoissues` before
implementation and record the resulting issue links or IDs in the handoff.

MVP deployment is host-daemon first: `agenttowerd` runs on the host, bench
containers run thin `agenttower` clients over a mounted Unix socket, and there
is no network listener in MVP.
