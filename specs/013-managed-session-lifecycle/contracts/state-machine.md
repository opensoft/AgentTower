# Contract: Managed Pane / Managed Layout State Machine

**Feature**: 013-managed-session-lifecycle
**Authority**: spec.md §FR-007 / §Clarifications Q1, Q2, Q8, Q9, Q13; research.md §R13.

This is the authoritative state graph for managed_pane and managed_layout. All other documents reference this file.

---

## Pane states

| State | Meaning |
|---|---|
| `creating` | Row inserted; pane is being spawned, agent is being registered, logs are being attached. Pending-managed marker is set. |
| `ready` | Pane exists in tmux, agent is registered with FEAT-006, log attach attempted (success or recoverable failure). Marker cleared. |
| `degraded` | Pane exists but is partly unhealthy: launch command exited immediately, or log attach failed, or agent went unhealthy after `ready`. Recovery is via **recreate**. |
| `failed` | Pane is unusable until recreated. `failed_stage` is populated. The row is retained for audit; a fresh recreated row may take its label (terminal-state rows are excluded from the per-container label uniqueness index). |
| `removed` | Operator-initiated removal; tmux pane was killed (or attempt was made), routes/log attachments cleaned. Terminal. Audit retained indefinitely (FR-021). |

---

## Pane transitions

| From | To | Trigger | Validator |
|---|---|---|---|
| _(none)_ | `creating` | `create_layout` or `recreate_pane` service entry | Idempotency dedupe (R10), per-container lock held |
| `creating` | `ready` | Pane spawned + FEAT-006 registration succeeded + log attach attempted | All three steps observed; pending-managed marker cleared synchronously |
| `creating` | `degraded` | Launch command exited within 1s OR log attach failed | `failed_stage` set to `launch_command` or `log_attach` |
| `creating` | `failed` | `tmux new-session/split-window` failed OR FEAT-006 registration errored | `failed_stage` set to `pane_create` or `registration` |
| `creating` | `failed` | Pending-managed marker TTL exceeded (5 minutes per FR-022, research §R5) and pane never observed | Daemon-initiated sweep task; `failed_stage = 'pane_create'` if no tmux pane backs the row, else `'registration'` |
| `ready` | `degraded` | Subsequent transient failure (log path lost, agent process exited) | Observed by FEAT-007 / FEAT-006 health probes |
| `ready` | `removed` | Operator `remove` | Per-container lock held; tmux `kill-pane` attempted |
| `degraded` | `removed` | Operator `remove` | Same as `ready → removed` |
| `degraded` | `failed` | Subsequent non-recoverable failure (registration lost, tmux pane disappeared) | `failed_stage` updated |
| `failed` | `removed` | Operator `remove` | `kill-pane` skipped if pane is already gone |
| `removed` | _(terminal)_ | — | — |

**Disallowed transitions** (rejected with `managed_pane_illegal_transition`):

- `ready → creating`
- `degraded → ready` (recovery is via recreate; keeps the graph acyclic)
- `failed → ready` (same)
- `removed → *`
- `* → promoted_from_adopted` (reserved; returns `not_implemented`)

---

## Layout states (derived)

The layout's state is **derived** from the aggregate of its managed_pane rows, computed and persisted on each pane state transition:

| Pane state distribution | Layout state |
|---|---|
| Any pane `creating` | `creating` |
| All panes `ready` (no `degraded`/`failed`) | `ready` |
| At least one `degraded`, no `creating`/`failed` | `degraded` |
| At least one `failed` | `failed` |
| All panes `removed` | `removed` |

A layout cannot be removed independently of its panes — removing the layout cascades a `remove` to every non-terminal pane.

---

## Recreate semantics (Q2 / R3)

When the operator invokes `recreate_pane` against a pane in `removed` or `failed`:

1. Service validates `predecessor.chain_depth < 16` else `managed_pane_recreate_chain_too_deep` (FR-023, R4).
2. A new `managed_pane` row is inserted with:
   - Fresh `id` (uuid4).
   - Same `layout_id`, `role`, `capability` as predecessor.
   - Fresh `label` resolved from the layout's template `label_pattern` with the next ordinal not currently used by a non-terminal pane in this layout.
   - `predecessor_id = predecessor.id`.
   - `chain_depth = predecessor.chain_depth + 1`.
   - Initial `state = 'creating'`.
   - Pending-marker token equals the recreate request's optional `idempotency_key` else `uuid4()`.
3. The pipeline (`creating → ready`/`degraded`/`failed`) runs the same way as a fresh create.

Recreating from a `ready` or `degraded` pane is **not** allowed (the operator must `remove` first); the service refuses with `managed_pane_illegal_recreate_source`.

**Idempotency + in-flight successor (FR-011 / FR-027):** a recreate retried with the same `idempotency_key` as the in-flight successor replays that successor (`replay: true`) instead of returning `managed_pane_concurrent_recreate`. A predecessor that already has a **non-terminal** successor (`creating` / `ready` / `degraded`) MUST NOT be recreated again until that successor reaches a terminal state — the slot's `(tmux_session_name, tmux_pane_index)` and label are still occupied. The service surfaces this as `managed_pane_concurrent_recreate`; the insert path also translates any residual partial-unique-index collision into the closed-set `managed_session_name_conflict` / `managed_pane_label_conflict` rather than a raw DB error.

---

## Recovery (FR-020 / SC-008)

Boot-time reconcile (see `recovery.py`):

1. Load every `managed_layout` and `managed_pane` row where `state IN ('creating','ready','degraded')`.
2. For each unique `container_id`, invoke `tmux list-panes -t <container>` via the FEAT-004 channel. **Per-container isolation (FR-020):** a list-panes failure for one container is logged and that container is skipped (its rows left untouched for the next reconcile) — it MUST NOT abort recovery for the other containers, and the per-container pane-state writes + the layout-aggregate recompute MUST be committed together so an aborted container never leaves a layout's aggregate stale.
3. Match by `(tmux_session_name, tmux_pane_index)`:
   - **Match** — pane is alive; transition rule:
     - `creating` + marker still set + age < TTL → left in `creating`. **Not re-driven at boot** (FR-020): the original spawn thread died with the prior daemon process, and re-running the spawn pipeline would re-issue `new-session`/`split-window` against the already-existing pane. The row stays `creating` until the FR-022 TTL sweep transitions it to `failed` if it never settles. (A register/log-attach-only continuation is deferred.)
     - `creating` + marker still set + age ≥ TTL → move to `failed` with `failed_stage = 'recovery_reattach'`.
     - `ready` / `degraded` — re-emit the audit event `managed_layout_recovery_reattached` and keep state.
   - **No match** (pane gone) — move to `failed` with `failed_stage = 'recovery_reattach'`; emit `managed_layout_recovery_failed`.
4. Drop any `pending_marker_token` whose row is now in a non-`creating` state.
5. Release per-container locks; socket starts accepting requests.

**Clean-shutdown ordering (implementation invariant):** on `agenttowerd` shutdown, the daemon cancels the FR-022 sweep timer and closes the shared worker connection **under the worker transaction lock**, so any in-flight managed write (a background spawn thread or a sweep tick) completes before the connection closes — the close cannot race a tx-guarded statement. This is a daemon implementation invariant, not an operator-facing requirement; on the rare interleaving the next boot's reconcile + sweep repairs the row regardless.

**Operator visibility of recovery outcomes (FR-020 / SC-009)**: After step 5, every recovered managed-layout and managed-pane row is readable via the standard `app.managed_layout_detail` (M3) and `app.managed_pane_detail` (M5) surfaces. A pane that failed to reattach surfaces as `state = "failed"` with `failed_stage = "recovery_reattach"`; a successful reattach keeps the prior state (`ready` / `degraded`). No log inspection is required, and SC-009 mandates this be observable within 5 seconds of socket-ready.

---

## Promotion stub (Q13 / FR-018)

`promote_adopted_to_managed` is reserved in the state graph for a later feature. In MVP:

- The state-machine module exposes a `PROMOTE_FROM_ADOPTED` constant for tests but the service entry point returns `not_implemented` (FEAT-011 closed-set code).
- The data model does not require any new column to support promotion later — when implemented, promotion would insert a new managed_pane row with `predecessor_id = NULL`, `chain_depth = 0`, and `agent_id` set to the adopted pane's existing agent_id, then update the adopted-agent's metadata in place.
