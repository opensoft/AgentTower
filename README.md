# AgentTower

AgentTower is an Opensoft local control tower for orchestrating AI agent
terminals, long-running jobs, and container shells running in tmux.

It is designed for developers who run multiple Claude Code, Codex CLI, test
runner, and Docker/devcontainer sessions at the same time and need one reliable
place to see what is running, which panes are waiting, and where notifications
should be routed.

## Status

AgentTower is in early product design. This repository currently contains the
project scaffold and product direction. The first implementation will focus on a
local Python CLI and daemon before adding a richer terminal UI.

## Problem

tmux is good at keeping terminal sessions alive, but it does not understand
agent workflows. A tmux window can show activity, and `pipe-pane` can write a
log, but something still has to decide whether that activity means:

- an agent is waiting for input
- a test run failed
- a long-running job completed
- a worker needs to notify an orchestrator
- a pane is connected to the wrong container

AgentTower adds the missing coordination layer without replacing tmux, Docker,
Claude Code, Codex CLI, or existing shell helpers.

## Core Ideas

AgentTower treats every tmux pane as a discoverable local work surface. A pane
can be labeled and assigned a role:

- `orchestrator`: a Claude or Codex session that receives routed notifications
- `worker`: an agent pane being monitored
- `test-runner`: a pane running tests, benchmarks, or validation jobs
- `container-shell`: a shell attached to a Docker/devcontainer runtime
- `unknown`: a discovered pane that has not been classified yet

Workers can route events to one or more orchestrators. The user stays in
control of which panes can receive input.

## Planned Capabilities

- Discover all accessible tmux sessions, windows, and panes, including panes
  that were not started through AgentTower.
- Register pane metadata such as labels, roles, project paths, log files, and
  routing targets.
- Support multiple orchestrators at the same time.
- Attach durable logs to panes with `tmux pipe-pane`.
- Classify important terminal events such as waiting for input, errors, test
  failures, completed jobs, and manual review prompts.
- Route compact notifications to selected orchestrator panes.
- Show Docker containers and devcontainer-like runtime contexts.
- Infer which tmux panes appear connected to containers when possible.
- Open new tmux panes or windows attached to selected containers.
- Provide safe defaults so AgentTower does not type into an interactive pane
  unless the user has explicitly allowed it.

## Architecture

```text
tmux discovery + Docker discovery
        -> pane/container registry
        -> user role and routing config
        -> watcher/classifier daemon
        -> event queue
        -> notification router
        -> orchestrator pane(s)
```

The first implementation is expected to provide:

- `agenttower`: user-facing CLI
- `agenttowerd`: background daemon and watcher
- SQLite state storage
- JSONL event history
- append-only pane logs
- optional TUI after the CLI and daemon are stable

## Storage Layout

AgentTower uses an Opensoft namespace under the current user account:

```text
~/.config/opensoft/agenttower/config.toml
~/.local/state/opensoft/agenttower/agenttower.sqlite3
~/.local/state/opensoft/agenttower/events.jsonl
~/.local/state/opensoft/agenttower/logs/
~/.cache/opensoft/agenttower/
```

## CLI Direction

The initial CLI is expected to include commands similar to:

```bash
agenttower ensure-daemon
agenttower scan
agenttower list-panes
agenttower list-containers
agenttower register-pane --pane %4 --label claude-010 --role worker
agenttower attach-log --pane %4 --log ~/.local/state/opensoft/agenttower/logs/claude-010.log
agenttower route --from %4 --to %0
agenttower set-role --pane %0 --role orchestrator
agenttower events
agenttower open-container --container ledgerlinc-ocr-pipeline --new-window
agenttower tui
```

Shell helpers such as `yodex`, `yolo`, and `cta` should eventually call
`agenttower ensure-daemon`, start their tmux pane, register it, and attach a
log.

## Safety Principles

AgentTower can route text into live terminal panes, so safety is part of the
product contract:

- Discovered panes are notify-only by default.
- Sending input to a pane requires explicit permission.
- Notifications are queued when an orchestrator is not ready.
- Event history is auditable through JSONL logs.
- The user can disable routing globally or per pane.
- AgentTower should summarize terminal activity instead of blindly forwarding
  large raw logs.

## SonarQube CI

This repo runs SonarQube analysis as a GitHub Actions workflow, NOT
via the SonarCloud / SonarQube GitHub App. The workflow at
`.github/workflows/sonarqube.yml` runs `pytest` with coverage and
then `sonar-scanner`, passing PR-decoration context through the
GitHub Actions env vars.

To enable analysis on a repo:

1. Generate a long-lived analysis token in your Sonar instance
   (Account → Security → Generate Tokens). The token needs at
   least "Execute Analysis" on the project.
2. Add it as a repository **secret** named `SONAR_TOKEN`
   (Settings → Secrets and variables → Actions → Secrets).
3. (Optional, self-hosted only.) If your Sonar server is NOT
   SonarCloud, add a repository **variable** named `SONAR_HOST_URL`
   pointing at the server, e.g. `https://sonar.example.com`. The
   workflow falls back to `https://sonarcloud.io` when this variable
   is unset.

Project-level configuration (`sonar.projectKey`, exclusions, coverage
paths, Python version targets) lives in `sonar-project.properties`.

## Roadmap

1. Build tmux and Docker discovery.
2. Add the durable pane registry and state store.
3. Attach pane logs and track log offsets.
4. Emit classified events.
5. Route notifications to selected orchestrator panes.
6. Add container attach actions.
7. Add a TUI for pane/container/event management.
8. Integrate with local shell helpers.

## License

AgentTower is licensed under the Apache License, Version 2.0, matching
Opensoft's Dartwing project.
