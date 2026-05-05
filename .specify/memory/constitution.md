# AgentTower Constitution

## Core Principles

### I. Local-First Host Control

AgentTower is a local developer control plane. The MVP Tower runs as a host
daemon, stores durable state under the host user's Opensoft namespace, and does
not expose a network listener. Bench containers use thin clients over the
mounted Unix socket; they do not own durable state.

### II. Container-First MVP

MVP work targets running bench containers and tmux panes inside those
containers. Host-only tmux discovery, Antigravity support, Python-thread
backends, mailbox adapters, and in-container relays are later work unless a
feature explicitly changes scope.

### III. Safe Terminal Input

AgentTower can type into live terminals, so safety is a product requirement.
Unknown panes must not receive input, master permissions must be human-granted,
prompt delivery must be queued and auditable, and shell command construction
must never interpolate raw prompt text.

### IV. Observable and Scriptable

Every feature must be usable from the CLI and inspectable through durable state.
SQLite stores current state, JSONL stores audit history, and pane logs are
append-only where practical. Failures should produce actionable CLI output
rather than silent degradation.

### V. Conservative Automation

AgentTower is a registry, router, event stream, and safe input layer. It does
not decide project workflows, choose the best model agent for a task, or answer
agent questions automatically. Masters own workflow logic; AgentTower transports
prompts and events.

## Technical Constraints

- Primary implementation language is Python.
- Console entrypoints are `agenttower` and `agenttowerd`.
- Durable files live under `~/.config/opensoft/agenttower/`,
  `~/.local/state/opensoft/agenttower/`, and
  `~/.cache/opensoft/agenttower/`.
- MVP container discovery uses Docker from the host and defaults to container
  names containing `bench`.
- MVP tmux discovery uses `docker exec -u "$USER"` into bench containers.
- CLI output should support human-readable defaults and structured output where
  it materially helps automation.

## Development Workflow

- Build features in the order defined by `docs/mvp-feature-sequence.md`.
- Run `/speckit.specify <description>` only from the root checkout on `main`.
  Run all later Spec Kit steps only from the intended feature worktree after
  verifying the branch and worktree path. The normal order is specify, switch
  to worktree, clarify, plan, checklist, tasks, analyze, implement.
- Decide explicitly whether `/speckit.checklist <topic>` is needed before
  generating tasks; run it for known quality gates and repeat by topic when
  useful. Use your own judgment after each checklist to decide whether a second
  topic-specific checklist is warranted before tasks are generated.
- If tasks are deferred to a later feature, run `/speckit.taskstoissues` before
  implementation and capture the issue links or IDs.
- Keep each feature independently testable from the CLI.
- Add tests proportional to risk, with broader tests for daemon state, socket
  protocol, Docker/tmux adapters, permissions, and input delivery.
- Preserve existing docs and NotebookLM sync mappings when adding Markdown.
- Do not introduce a TUI, web UI, or relay before the core daemon, discovery,
  registration, logging, events, and routing slices work.

## Governance

This constitution guides Spec Kit planning and task generation for AgentTower.
Changes to these principles should be explicit, documented in the relevant
feature spec, and reflected in the PRD or architecture docs when they affect
product scope.

**Version**: 0.1.0 | **Ratified**: 2026-05-05 | **Last Amended**: 2026-05-05
