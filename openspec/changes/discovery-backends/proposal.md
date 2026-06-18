# Add Pluggable Discovery / Substrate Backends

## Why

AgentTower's discovery is hardwired to one substrate: bench containers found via
`docker ps`, with tmux panes enumerated through `docker exec` (FEAT-003 /
FEAT-004). Every later layer — registry, logs, events, routing — assumes that
single source. Databricks' Omnigent treats execution substrates as
interchangeable; AgentTower should similarly abstract *where panes/agents come
from* so host-only tmux and future remote/cloud benches can be peer backends
behind one interface — without rewriting the registry/event/routing stack each
time. (Omnigent sessions are explicitly **not** a discovery backend; they are the
Tier-2 hand-off in `agent-connection-tiers`. See Non-goals.)

This change defines a `DiscoveryBackend` interface, refactors bench-container
discovery to be its first implementation (no behavior change), and adds a
host-only tmux backend as a second reference implementation to prove the seam.

## What Changes

- **Define a `DiscoveryBackend` interface contract:** enumerate hosts/
  containers, enumerate panes, probe attach-log capability, and produce stable
  identity keys.
- **Refactor bench-container discovery as backend #1** — a pure refactor with no
  behavior change.
- **Add a backend registry + config:** enable/disable per backend, per-backend
  configuration, and identity namespacing so two backends cannot collide on tmux
  pane ids.
- **Isolate degraded state per backend:** one backend failing (e.g. Docker
  down) must not crash or degrade others.
- **Add a host-only tmux backend as reference #2** to validate the abstraction
  and land a long-standing "later" item.

## Impact

- **New capability spec:** `discovery-backends`.
- **Builds on / refactors:** FEAT-003 (container discovery), FEAT-004 (container
  tmux discovery). Registry/event/routing layers consume backends through the
  interface rather than calling Docker directly.
- **Independent of** `routing-policy-layers` and `app-collaboration`.
- **No code ships in this change** — spec/design proposal only.
- **Non-goals:** implementing a cloud/remote bench backend (interface +
  host-only reference only); Omnigent-as-a-backend (that is Tier 2 in
  `agent-connection-tiers`, handled separately).
- **Open question:** the cross-backend identity-keying scheme.
