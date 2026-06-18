# Design: Multi-Operator App Collaboration

## Context

FEAT-011 added the `app.*` namespace over the host daemon's Unix socket: a
versioned, host-only, session-based API (cap 8 concurrent sessions via
`app.hello`) that a packaged desktop control panel uses instead of scraping CLI
output. Today nothing distinguishes one app session from another in terms of
authority — every session can call every mutation. This design adds
collaboration semantics: multiple humans connected at once, with read-only
watchers and permitted co-drivers, while staying local and listener-free.

## Goals / Non-Goals

**Goals**
- Multiple concurrent operators see one consistent live view.
- A clear, server-enforced split between `observer` (read-only) and `operator`
  (mutating) sessions.
- Cross-session auditability.

**Non-Goals**
- Remote / URL / mobile sharing — requires an authenticated transport and a
  reversal of the no-network-listener stance; explicitly deferred.
- External identity (OIDC) — the trust model stays same-host-UID + socket
  permission, as in FEAT-011.
- Session *forking* (independent continuation) — candidate for a later change.

## Decision 1 — Session roles over the existing socket

`app.hello` issues a session; this change adds a session **role** of `observer`
or `operator`. The role is assigned at session establishment under the existing
same-host-UID trust model — no new credential or listener is introduced. The
8-session cap and in-memory session registry from FEAT-011 are reused.

Rationale: collaboration is a property of *who is connected to the local
daemon*, not a new transport. Keeping it on the existing socket preserves the
constitution (`architecture.md` §23).

## Decision 2 — Consistent shared view

All sessions read the same SQLite registry and the same `events.jsonl` stream,
so any two connected clients converge on the same state. Event tailing is
per-session but sourced from the one daemon stream; no client holds private
authoritative state.

Rationale: "watch" only has meaning if every watcher sees the same thing the
driver sees.

## Decision 3 — Server-side co-drive enforcement

Mutating `app.*` methods (the FEAT-011 operator mutations: `app.agent.update`,
`app.log.*`, `app.send_input`, `app.queue.*`, `app.route.*`) are permitted only
for `operator` sessions. `observer` sessions calling a mutation receive a
closed-set rejection. Where `routing-policy-layers` is present, co-drive
deliveries also pass the policy stack.

Rationale: enforcement must be server-side; a read-only client must not be able
to mutate by crafting requests.

## Decision 4 — Cross-session audit

Each mutation records the originating app session id alongside the existing
audit fields, so "who did what" is answerable across simultaneous operators.

## Decision 5 — Explicit local-only boundary

This change is same-host socket only. Remote/URL/mobile sharing is named as a
non-goal with its gate: an authenticated network transport whose adoption is a
separate, deliberate decision (the deferred "reachable-from-anywhere" item).
This is the seam that future work would attach to.

## Risks / Trade-offs

- **Accidental co-drive** — default new sessions to `observer`; require an
  explicit step to become `operator`.
- **Conflicting operators** — two operators mutating at once is serialized by
  the daemon; multi-master arbitration (architecture §17) already covers
  conflicting deliveries.
- **Scope creep toward remote** — the local-only boundary is a hard line in this
  change.

## Migration / Phasing

1. Add session role to `app.hello` / the session registry.
2. Enforce observer/operator on mutating methods.
3. Cross-session mutation audit.

## Open Questions

- Is watch + co-drive sufficient for v1, or is session fork needed?
- Default role policy: always `observer` until explicitly promoted?
