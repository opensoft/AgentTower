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

## Host Path & Command Execution

Why: absolute host paths baked into repo files (or pointer files like `.git`)
silently break when the repo moves on disk — symlink swap, bind-mount change,
new host, rsync to a new directory. The stale `git worktree` pointer breakage
between `/home/brett/projects/AgentTower*` and `/workspace/projects/AgentTower*`
is the canonical example.

**Rule 1 — Never write host-absolute paths into repo files.** When editing or
creating any committed file (source, config, script, spec, doc, fixture), do
not write `/home/<user>/...`, `/workspace/...`, `C:\Users\...`, or any other
host-specific absolute path. Use one of:

- Relative paths from the repo root or the file's own location.
- Project-defined env vars (`$REPO_ROOT`, `$AGENTTOWER_ROOT`); define one at
  the entry point if none exists rather than inlining a host path.
- Runtime resolution (`git rev-parse --show-toplevel`,
  `Path(__file__).resolve().parents[N]`, etc.).

If you find an existing host-specific path while editing nearby code, treat it
as a bug: don't propagate it, and flag it to the user. Exceptions: machine-
managed git plumbing under `.git/`, lockfiles, and files explicitly marked
host-local and gitignored.

**Rule 2 — Run codebase commands inside the devBench container.** For build,
test, lint, run, migrations, code generation, and any command that resolves
project paths, execute inside the project's dev container (devBench) rather
than the host shell. Container-internal paths are stable; host paths vary by
machine, mount layout, and WSL configuration, which is exactly the variability
Rule 1 is protecting against.

Exceptions where host execution is correct:

- `git` operations on the host checkout (status, log, worktree management,
  fetch/push).
- OS-level inspection and anything that talks to the host's Docker/devBench
  daemon itself.
- The Spec Kit `pwd` / `git rev-parse` worktree checks above.

In all such host-side cases, Rule 1 still applies to whatever gets written
back into committed files.

If the right devBench invocation isn't obvious from project tooling, stop and
ask before defaulting to the host shell.

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
