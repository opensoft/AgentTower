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

## Single-Bench Feature Ownership

Every AgentTower feature must be owned by exactly one execution bench. Do not
plan or implement a feature that requires agents to work across both
`py-bench` and `flutter-bench` in the same feature scope.

- `py-bench` features may change Python daemon, CLI, local app contracts,
  backend tests, OpenSpec/Spec Kit artifacts, and backend documentation.
- `flutter-bench` features may change the Flutter desktop app, Flutter client
  contract consumption, UI tests, desktop build/run checks, and UI
  documentation.
- If a product change needs both backend and Flutter work, split it into
  separate features with separate branches/worktrees: one `py-bench` feature
  for the backend/contract side and one `flutter-bench` feature for the app
  consumer side.
- Each feature spec/plan must name its owning bench and keep implementation
  tasks inside that bench. Cross-bench follow-up work belongs in a later
  feature, not as hidden scope inside the current one.

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

## Shared File Path Coordination

When a human or another agent names a specific file path for shared
coordination, use that exact path as the coordination surface. This matters
most for files edited by both host-side Codex and container-side Claude, such
as Spec Kit clarification files, plans, task lists, and review notes.

- Do shared-file work through the devBench container, not the host shell. For
  this repo, `/workspace/projects/...` inside `py-bench` is the canonical
  shared project mount used by Claude and other container-side agents.
- If the path is under `/workspace/...`, treat `/workspace/...` as canonical
  for that task. Use the container's `/workspace/...` path for reads, edits,
  git checks, and verification. Do not use the host's `/workspace/...` path;
  it may be a different stale/root-owned directory.
- Before editing, verify the exact named file exists and is writable from
  inside the container that owns the shared workspace.
- If the exact path is missing, stale, or not writable, stop and report the
  mismatch. Do not create or edit a mirror copy unless the user explicitly
  approves that fallback.
- When answering clarification questions from a file, put the answers inline
  in that same file, not only in chat and not in a separate answers file,
  unless the user explicitly requests a separate file.

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

## Cross-Feature Spec Dir Editing

A feature PR ordinarily edits only its own `specs/<NNN>-<slug>/` directory.
The one allowed exception is **additive cross-reference breadcrumbs**: a
contract-evolution feature MAY add a small subsection to a prior feature's
`specs/<MMM>-<slug>/contracts/*.md` for the sole purpose of pointing readers
at the new evolution. Rules:

- The added subsection MUST be purely additive (a new `## App Contract
  Evolution — vX.Y (FEAT-NNN)` heading or similar). It MUST NOT rewrite,
  reflow, or delete any prior text in the file.
- The subsection MUST be a pointer to the evolving feature's own
  `contracts/` directory, not a re-statement of the new contract content.
- If a feature would need to *modify* (not just append to) a prior feature's
  spec dir, it MUST be split into two PRs: the current feature's PR
  (self-contained), and a follow-up PR owned by the prior feature's lineage
  that does the modification.

The canonical contract docs always live in the feature that introduced the
contract version. Prior-feature spec dirs get pointers, not duplicates.

## Detecting "Already In devBench" (Rule 2 satisfied)

When a Claude or Codex session starts INSIDE the project's devBench container
(as opposed to the host shell), the host-path rule's prescription to "run
codebase commands inside the devBench container" is already satisfied — no
separate routing step (no `docker exec`, no `devbench` wrapper) is required.
Detect "in devBench" deterministically by requiring BOTH structural signals,
treating the env var as confirming-but-optional:

1. `/.dockerenv` exists — any Docker container. (required)
2. The project workspace is mounted at `/workspace/…` — the devBench layout. (required)
3. `REMOTE_CONTAINERS=true` is set — confirms a VS Code devcontainer launch, but
   may be absent for `docker exec`, `tmux`/SSH attach, or `cta`-launched shells
   that are nonetheless inside the container. (optional, confirming-only)

When both required structural signals hold, run codebase commands directly: `python3`,
`pytest`, `pip`, the project's CLI, etc. From inside the container, the
in-container shell IS the runner; the host-path concerns Rule 1 protects
against don't apply, because the container's filesystem layout is stable
across host machines, WSL configurations, and mount-point reshuffles.

When either required structural signal is missing, treat the current shell as a host
shell: either route the codebase command through the appropriate devBench
invocation (typical from the host: `docker exec <bench-name> …`) or stop and
ask the user how to route before defaulting to the host.

In this repo's devBench the bench is named `py-bench`. That name is not
visible from inside the container, so do NOT try to verify it programmatically
— verify "in devBench" via the two required structural signals above.
