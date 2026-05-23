# Contract: FEAT-011 `app.*` Methods Consumed by FEAT-012

**Purpose**: Map each FEAT-012 functional requirement to the FEAT-011 `app.*` method(s) it calls. Establishes which subset of FEAT-011's 32-method surface the desktop app exercises, so the FEAT-012 implementation has a clean "where does this data come from?" reference and FEAT-011 maintainers can see which methods are load-bearing for the GUI.

**Source contract**: `specs/011-app-backend-contract/contracts/app-methods.md` (32 methods at v1.0 of `app_contract_version`).
**Wire framing**: per FEAT-011 FR-003a/b — newline-delimited JSON, 1 MiB request / 8 MiB response, UTF-8, `\n`-terminated.
**Envelope**: per FEAT-011 FR-033 — `{ok, app_contract_version, result}` or `{ok, app_contract_version, error: {code, message, details}}`.

## 1. Bootstrap & session lifecycle

| FEAT-011 method | FEAT-012 use | FR ref |
|---|---|---|
| `app.preflight` | Doctor / preflight surface in Settings; also the FR-009 doctor's first check ("Daemon socket reachable at the configured path") | FR-002, FR-009 |
| `app.hello` | App startup; held in-memory only per FR-003; re-bootstrapped on socket reconnect | FR-002, FR-003 |

**Session policy**: the app holds exactly one session at a time. Per FEAT-011's 8-concurrent-session cap, the app will not stack sessions on reconnect (FR-003 says "re-bootstrap on socket reconnect" — the prior session is implicitly invalidated by daemon-side disconnect detection).

## 2. Readiness & Dashboard

| FEAT-011 method | FEAT-012 use | FR ref |
|---|---|---|
| `app.readiness` | Subsystem panel on the Health view; doctor check #3 (`app_contract_version` satisfies minimum) reads `result.contract_compat` | FR-022, FR-009 |
| `app.dashboard` | Top of the Agent Operations Dashboard (FR-012: counts + recents + recommended next action) | FR-012 |

## 3. Read surfaces (`app.<entity>.list` / `app.<entity>.detail`)

The app consumes FEAT-011 read surfaces for these entities. All calls use the FEAT-011 default page size (50) with cursor pagination per FEAT-011 FR-020a; the app never asks for `limit > 50` at MVP.

| Entity | `list` callsite | `detail` callsite | FEAT-012 FR(s) |
|---|---|---|---|
| `container` | Agent Operations → Containers view | per-container drill-down | FR-011, FR-013 |
| `pane` | Agent Operations → Panes view | per-pane drill-down (state transitions, attached log, adopted agent ref) | FR-014, FR-017 |
| `agent` | Agent Operations → Agents view; Master Summary projection per FR-071 | per-agent drill-down (current goal/task, sub-agent tree, log attachment) | FR-015, FR-016, FR-030, FR-071 |
| `log_attachment` | per-pane affordance + Agents view | not directly surfaced in MVP (covered by Pane detail) | FR-017 |
| `event` | Agent Operations → Events view (virtualized infinite scroll per FR-080) | per-event drill-down (linked queue row) | FR-019, FR-080 |
| `queue` | Agent Operations → Queue view (5-state vocabulary) | per-row drill-down for approve/delay/cancel | FR-020, FR-080 |
| `route` | Agent Operations → Routes view; explainability surface (FR-021, FR-059) | per-route drill-down (recent match/skip) | FR-021, FR-059 |

**Anticipated additions in a FEAT-011 v1.x minor bump** (not present in v1.0, but required by FEAT-012 surfaces — see R-19 caveat):

| Entity | `list` / `detail` use | FEAT-012 FR(s) |
|---|---|---|
| `project` | Project and Specs → Projects view (cards) + project switcher | FR-024, FR-025, FR-026 |
| `feature_change` | Project and Specs → Current Work, Specs, Changes | FR-027, FR-028, FR-031, FR-032 |
| `handoff` | Project and Specs → Handoff flow + handoff list + per-handoff detail | FR-036–FR-045, FR-072, FR-081 |
| `helper_policy` | Handoff flow's auto-fill + override; doctor check (FR-038a) | FR-038, FR-038a |
| `drift` | Project and Specs → Drift view + per-finding detail | FR-033, FR-034 |
| `validation_entrypoint` | Testing and Demo → Available Validation view | FR-046, FR-047 |
| `validation_run` | Testing and Demo → Runs view | FR-048 |
| `demo_readiness` | Testing and Demo → Demo Readiness view (one per branch) | FR-050 |
| `attention` | Agent Operations → operator attention queue | FR-052 |
| `notification` | Shared → notifications panel + history | FR-008, FR-056 |
| `operator_history` | Shared → operator history surface (FR-055) | FR-055 |

If any of these methods are not yet on FEAT-011's v1.0 surface, the consuming surface degrades per FR-002 / FR-004 (`contract-version-incompatible`); the spec already handles this.

## 4. Adopt mutation

| FEAT-011 method | FEAT-012 use | FR ref |
|---|---|---|
| `app.agent.register_from_pane` | Adopt-existing-pane flow (label, role, capability, project_path, attach_log boolean) | FR-016, FR-065 |

## 5. Operator mutations

| FEAT-011 method | FEAT-012 use | FR ref |
|---|---|---|
| `app.agent.update` | Update label/role/capability/project_path on an adopted agent (Agents view) | FR-015 |
| `app.log.attach` / `app.log.detach` | Per-agent or per-pane log attach/detach affordance | FR-017 |
| `app.send_input` | Direct Send affordance; uses optional `idempotency_key` per FEAT-011 FR-031a; the FEAT-009 safe prompt queue is the delivery path | FR-018, FR-043 (handoff delivery uses the same queue) |
| `app.queue.approve` / `app.queue.delay` / `app.queue.cancel` | Queue view per-row actions on `blocked` and `queued` rows | FR-020 |
| `app.route.add` / `app.route.remove` / `app.route.update` | Routes view: add route, edit enabled state, remove route | FR-021 |

**Anticipated mutation additions in a FEAT-011 v1.x bump** (used by FEAT-012 but not necessarily on v1.0 — see R-19 caveat):

| FEAT-011 method | FEAT-012 use | FR ref |
|---|---|---|
| `app.handoff.draft` (create draft) | Handoff flow entry; returns transient draft id (per data-model §1.6) | FR-036–FR-038 |
| `app.handoff.preview` (regenerate prompt body for mode change) | Preview step; preserves operator notes per FR-040 | FR-040 |
| `app.handoff.submit` (persist + dispatch via safe prompt queue) | Submission; on success returns daemon-issued `handoff_id` | FR-042, FR-043 |
| `app.handoff.cancel` | Handoff list / detail surface | FR-044 |
| `app.handoff.supersede` (mark prior superseded, set `superseded_by_handoff_id` on new) | Double-driving conflict resolution per FR-081 | FR-081 |
| `app.drift.transition` (lifecycle state change) | Drift detail surface: new → review_needed → … → resolved; accepted_as_built; dismissed | FR-034 |
| `app.validation.run.trigger` | Available Validation card → trigger | FR-049 |
| `app.validation.run.cancel` | Runs view → cancel a `running` or `queued` run | FR-049 |
| `app.notification.acknowledge` | Notifications panel → process notification → move to history | FR-056 |
| `app.project.add` | Projects view → Add Project (explicit operator action) | Assumption: project registration model |
| `app.project.remove` | Projects view → Remove Project (FR-077 — clears UI persistence; daemon-side data untouched) | FR-077 |
| `app.helper_policies.list` / `app.helper_policies.resolve` | Handoff flow's auto-fill + override (FR-038a) | FR-038a |

## 6. Scans

| FEAT-011 method | FEAT-012 use | FR ref |
|---|---|---|
| `app.scan.containers` / `app.scan.panes` | "Re-probe" affordance on Panes view (FR-014's "re-probe" next action); also operator-triggered scan from Containers view | FR-014 |
| `app.scan.status` | Status polling for in-flight scans; spec already caps wait at 30 s per FEAT-011 FR-030b | FR-014 |

## 7. Live updates / event streaming

FEAT-011 v1.0 is request/response; live-update delivery is not yet specified at the contract level. FEAT-012's FR-064 ("within 2 seconds of the event being observable on the daemon side") implies either:

(a) **Server-pushed**: FEAT-011 adds a `app.subscribe` / `app.event_stream` surface in a v1.x minor that pushes new events over the same socket. Preferred.

(b) **Client-polled**: The app polls `app.event.list` and `app.queue.list` with cursor-since semantics at ≤ 1 s intervals while a surface is visible.

**Decision**: the FEAT-012 implementation will target (a) when it lands and fall back to (b) until then. The fallback's polling cadence is selected per surface to stay under FR-064's 2 s budget without exceeding FEAT-011's 8-session cap (a single session multiplexes all subscriptions).

## 8. Error vocabulary

The app handles the **27-entry FEAT-011 closed-set error vocabulary** (FEAT-011 FR-034). Each variant maps to user-facing copy via the i18n layer (FR-067) and is rendered with the inline-error pattern from FR-018 / FR-020 / FR-072. The full mapping lives in `apps/control_panel/lib/core/daemon/errors.dart` (one Dart enum variant per FEAT-011 code).

Two FEAT-011 codes warrant per-surface treatment in FEAT-012:

- `app_contract_major_unsupported` → triggers FR-002 global banner + per-surface contract-version-incompatible state + disabled mutations.
- `host_only` → never reached in MVP (the desktop app is host-only by construction per FR-061); if observed, the app logs the anomaly and surfaces a runtime-degraded indicator.

## 9. Methods NOT used by FEAT-012

For completeness, FEAT-011 methods that are exposed but NOT consumed by the FEAT-012 GUI at MVP:

- None known. The 32-method FEAT-011 surface is fully relevant; only the helper-policy and project/handoff/drift/validation expansions in §3 may post-date FEAT-011 v1.0.

## 10. Wire-framing & session reconnect

- **Per-line size caps**: requests are kept under 1 MiB (FEAT-011 FR-003a); responses can be up to 8 MiB. The app pre-validates large requests (e.g. operator notes on a handoff have a soft cap below 1 MiB).
- **Framing**: every JSON envelope is terminated with `\n`; the app rejects responses containing `\r` or `\x00` or trailing content per FR-003b and triggers `malformed_request` recovery (re-bootstrap).
- **Reconnect**: on socket close mid-request, the app surfaces FR-004 `runtime-unreachable` and (per FR-003) re-bootstraps on the next operator-driven action or "Retry connection" affordance. In-flight mutations are NOT silently retried per FR-018.
