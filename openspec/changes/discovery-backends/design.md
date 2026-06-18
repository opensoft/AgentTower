# Design: Pluggable Discovery / Substrate Backends

## Context

AgentTower discovers work in exactly one way today: the host daemon runs
`docker ps` to find bench containers, then `docker exec -u "$USER" … tmux
list-panes` to find panes inside them (FEAT-003 / FEAT-004). Pane identity is
`(container, tmux socket, session, window, pane index, pane id)`. The registry,
log attachment, event pipeline, and routing all assume this single substrate.
This design extracts a backend interface so additional substrates become
additive, not invasive.

## Goals / Non-Goals

**Goals**
- One interface that any substrate implements to feed the existing registry.
- Bench-container discovery becomes the first backend with zero behavior change.
- A second (host-only tmux) backend proves the abstraction.
- Backend failures are isolated; identities never collide across backends.

**Non-Goals**
- Cloud/remote bench backend implementation (interface + host-only reference
  only).
- Omnigent sessions as a backend — that is the Tier 2 hand-off in
  `agent-connection-tiers`, not a discovery substrate here.
- Changing the registry/event/routing data model beyond identity namespacing.

## Decision 1 — The `DiscoveryBackend` interface

A backend exposes:
- `enumerate_targets()` — the hosts/containers it manages.
- `enumerate_panes(target)` — tmux panes within a target.
- `attach_log_capability(pane)` — whether/how host-visible logging is possible
  for that pane (so the FEAT-007 invariant is a backend property, not a global
  assumption).
- `identity_key(pane)` — a stable, backend-namespaced key.

Rationale: this is the minimal surface the current daemon already needs; it just
names it so it can be implemented more than once.

## Decision 2 — Identity namespacing

Every backend prefixes its identities with a backend id (e.g. `bench:` vs
`host:`). tmux pane ids (`%4`) are only unique within a tmux server, so the
registry key becomes `(backend_id, target_id, tmux_socket, pane_id, …)`.

Rationale: prevents a host-tmux `%4` from colliding with a container-tmux `%4`,
and lets the same physical machine be seen by two backends without aliasing.

### Migration of existing bench-only deployments (concrete plan)

Existing deployments have rows written before namespacing existed; they carry no
backend prefix. The migration is deterministic and tied to the schema-version
bump that introduces the `backend_id` column:

1. **At upgrade (one-time, in the schema migration that adds `backend_id`):**
   every existing `agents` / `panes` / `log_offsets` row is stamped
   `backend_id = 'bench'` in a single transaction, because pre-namespacing
   discovery could only have come from the bench-container substrate. The
   migration is **idempotent** (guarded by the schema version) and **history-
   preserving** (it rewrites the key column in place; it does not delete or
   re-create rows, so events, offsets, and queue references stay attached).
2. **Read-time shim during the transition:** any lookup that receives a legacy
   key with no prefix is treated as `bench:<key>`, so an in-flight client or a
   not-yet-migrated reference resolves correctly until step 1 completes.
3. **No dual-write:** after the migration runs, all writers emit prefixed keys
   only; the shim exists solely to tolerate legacy reads and can be removed a
   release later.

This makes the bench backend's identities `bench:`-namespaced with zero history
loss and no operator action, and gives downstream schema work a fixed contract
to build on.

## Decision 3 — Per-backend degraded isolation

Each backend scan runs and degrades independently. A backend that throws (Docker
socket down, tmux missing) is marked degraded with an actionable status; other
backends keep scanning. This generalizes FEAT-003/004's existing
graceful-degradation requirement from "Docker" to "any backend".

## Decision 4 — Bench backend first, host-only backend second

- **Backend #1 (bench-container):** a refactor of FEAT-003/004 behind the
  interface. Acceptance is "no observable behavior change".
- **Backend #2 (host-only tmux):** enumerate the host user's tmux sockets
  directly (no `docker exec`). Proves the interface and delivers the
  long-deferred host-only discovery item.

## Risks / Trade-offs

- **Refactor risk** — bench backend must be behavior-preserving; cover with the
  existing FEAT-003/004 integration tests before extraction.
- **Identity migration** — addressed concretely in Decision 2: a one-time,
  idempotent, history-preserving stamp of existing rows to `backend_id='bench'`
  plus a transition read-time shim for legacy unprefixed keys.
- **Config surface growth** — keep per-backend config minimal for MVP.

## Migration / Phasing

1. Extract the interface; wrap current Docker logic as the bench backend.
2. Add the backend registry + config + identity namespacing (back-compat for
   existing rows).
3. Add the host-only tmux backend.

## Open Questions

- Should backend selection be global config or per-bench/per-host overrides?
- How long should the legacy-key read-time shim (Decision 2, step 2) be retained
  before removal — one release, or longer for slow upgraders?
