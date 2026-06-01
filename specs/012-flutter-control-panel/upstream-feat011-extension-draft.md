> **Status: PARTIALLY SUPERSEDED (updated 2026-06-01).** §(a) — the `app.dashboard`
> field extensions — has since been promoted into **FEAT-014
> (`014-app-dashboard-extensions`)**, fully implemented (27/27) but not yet merged
> to `main`; it unblocks T160b (#34). §(b) `app.handoff.draft` and §(c)
> `app.events.subscribe` streaming are **still unfiled** — promote them as a new
> feature (proposed **FEAT-015**) via `/speckit.specify` from the root checkout on
> `main` (per `.specify/memory/constitution.md` and the project CLAUDE.md); they
> unblock T166 (#35) + T167 (#36). **Do not run `/speckit.specify` from this
> worktree.** This file remains a planning sketch for the FEAT-015 portion.

# Upstream FEAT-011 Extension for FEAT-012 Unblocking

**Why this exists**: Three open tasks in FEAT-012 (T160b, T166, T167) are
blocked on backend work that does not exist in FEAT-011 v1.0. As of 2026-06-01,
§(a) is filed (**FEAT-014**, done 27/27, pending merge — unblocks T160b); §(b)
and §(c) remain unfiled and need a new feature (**FEAT-015**) — unblocking T166
+ T167. Until each lands, the corresponding FRs (FR-012 dashboard tile parity,
FR-072(a) drafted-row recovery, FR-064 live-update budget) remain in a
documented-degraded state.

**Suggested feature id**: next sequential after 012 — likely `014` if FEAT-013
(Managed Session Creation) is already claimed.

**Suggested feature branch name**: `0NN-feat011-extension-for-feat012`.

## Hand-off to the operator

1. From the root checkout, on `main`:
   ```bash
   git checkout main
   git pull
   /speckit.specify "Extend FEAT-011 app.* contract with the dashboard fields,
                     handoff-draft persistence, and streaming subscription
                     method required to unblock FEAT-012 T160b / T166 / T167.
                     Bump app_contract_version to 1.1."
   ```
2. Move the body of this draft into the new feature's `spec.md` Summary +
   Requirements sections; delete this file from `specs/012-flutter-control-
   panel/`.
3. After `/speckit.tasks` completes on the new feature, edit FEAT-012's
   T160b / T166 / T167 bodies to cite the new task IDs as the blocking
   upstream work (instead of the abstract "FEAT-011 v1.x extension" phrase
   they use today).

## Summary

FEAT-011 v1.0 shipped the `app.*` namespace with 32 methods and contract
version 1.0. FEAT-012 consumes that surface as a thin Flutter client, but
during implementation three specific gaps emerged that FEAT-012 cannot fix on
its own without violating FR-005 ("the app MUST NOT invent or mutate domain
state locally") or FR-001 ("local-only via `app.*` namespace").

This feature bumps the contract to 1.1 and adds the minimum surface to close
those three gaps. No FEAT-012 source change beyond what T160b/T166/T167
already specify is required once 1.1 lands.

## Scope

### Three additions to FEAT-011 v1.1

#### (a) `app.dashboard` field extensions (unblocks T160b)

Extend the existing `app.dashboard` result row with four new fields:

| Field | Type | Purpose |
|---|---|---|
| `counts.panes.by_state` | `map<PaneState, int>` | Per-state pane counts for the FR-012 tile that today shows only a total |
| `counts.agents.by_state` | `map<AgentState, int>` | Per-state agent counts for the FR-012 tile |
| `counts.routes.recently_skipped_count` | `int` | 24-hour rolling count of routes that matched but were skipped — surfaces the FR-021 "recent skip explanation" signal at dashboard scale |
| `recommended_next_action` | `string` (one of an enumerated token set) | Daemon-computed recommendation for the operator's current state; the existing client logic in `dashboard_view.dart` already has a placeholder for this |

All four fields MUST be optional in the response shape (clients on contract
version 1.0 ignore them; clients on 1.1 read them).

Closes FEAT-012 T160b + analyze finding C1 + C4.

#### (b) `app.handoff.draft` write-through method (unblocks T166)

Add a new method `app.handoff.draft(params: { draft_id, draft_payload })`
that accepts a pre-submission Handoff draft and persists it daemon-side.
The daemon assigns a stable draft id (or echoes the client's transient draft
id) and returns the persisted shape. On a subsequent `app.handoff.submit`
that fails, the daemon updates the persisted draft with the failure context
so the operator can navigate away from the handoff modal and return to find
the draft + error intact (FR-072(a)).

Method signature:

```text
app.handoff.draft
  params:
    draft_id?: string         # transient client-side draft id (uuid v4)
    draft_payload: HandoffDraft  # same shape as app.handoff.submit's input
  result:
    row: HandoffDraftRecord
      handoff_id: string      # daemon-issued, stable across submission failure/retry
      draft_payload: HandoffDraft
      failure_context?: { code, message, details, occurred_at }
      created_at, updated_at
```

Closes FEAT-012 T166 + swarm-review H-B10.

#### (c) Streaming subscription method (unblocks T167)

Add a new method `app.events.subscribe(params: { since_cursor?, classes? })`
that returns a streaming response (SSE-style framing inside the existing
`\n`-terminated JSON-line transport, OR a separate Unix-socket connection
per session; preference depends on framing complexity tradeoffs the FEAT-011
implementor knows best).

Frames pushed to the subscriber MUST include enough envelope to demultiplex:

```text
{ ok, app_contract_version, stream: { class, payload } }
```

Where `class` is one of: `event`, `queue_row`, `route_match`, `route_skip`,
`drift_finding`, `validation_run`, `attention_item`, `notification`,
`master_summary`, `project_card_signal`.

Cancellation semantics: client closes its read side, daemon stops emitting
frames for that subscription. No explicit unsubscribe method required.

Closes FEAT-012 T167 + swarm-review M-11 + analyze finding C3.

### Contract version bump

`app_contract_version` MUST move from `1.0` to `1.1`. All three additions are
backward-compatible (optional fields + new methods); FEAT-012 clients on 1.0
continue to work unchanged.

## Out of Scope (explicitly)

- Mobile / remote-multi-host extensions to the streaming method.
- Push-based delivery to OS-native notifications (FEAT-012 client owns that;
  see FR-058).
- Server-Sent Events over HTTPS or any non-Unix-socket transport (per
  constitution Principle I).
- Changes to any FEAT-001..010 surface — this extension is FEAT-011-only.

## Dependencies & invariants

- Constitution Principle I (Local-First Host Control): preserved — additions
  are all Unix-socket-bound.
- FEAT-011 v1.0 wire framing (FR-003a/b: UTF-8, `\n`-terminated, 1 MiB
  request / 8 MiB response caps): the streaming method MUST preserve these
  caps per-frame.
- FEAT-012 FR-072(a) and FR-064: this feature is the ONLY way to close them.

## Hand-off to FEAT-012 after this lands

When this feature is archived / merged, FEAT-012 will:

1. Bump `ContractRegistry.declare('agent_ops/dashboard', ...)` from 1.0 → 1.1.
2. Un-comment + wire the 4 TODO-marked tiles in
   `dashboard_view.dart` (T160b).
3. Implement the client side of `app.handoff.draft` (T166).
4. Replace `ref.invalidate(...)` with the streaming subscription (T167).
5. Update T154(c) from "manual-refresh round-trip" to "push propagation"
   measurement.
6. Close analyze findings C1 + C3 + C4 + swarm-review H-B10 + M-11.

## Estimated scope for the new feature

| Phase | Estimated tasks |
|---|---|
| Setup | ~3 (mostly Python — extending existing FEAT-011 module structure) |
| Foundational | ~5 (extend envelope handling for streaming frames, schema migration if FEAT-011 persists handoff drafts) |
| US1 (single user story: client unblocking) | ~10 |
| Polish | ~3 |
| **Total** | **~21 tasks** |

The FEAT-011 implementor should re-derive these counts via `/speckit.plan` +
`/speckit.tasks`; this is a sketch, not a commitment.
