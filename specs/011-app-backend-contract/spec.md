# Feature Specification: Local App Backend Contract for Desktop Control Panel

**Feature Branch**: `011-app-backend-contract`
**Created**: 2026-05-18
**Status**: Draft
**Input**: User description: "FEAT-011: Local App Backend Contract for Desktop Control Panel — make `agenttowerd` a stable local backend for a packaged desktop control panel so a future Flutter app can operate AgentTower without scraping human CLI output. Local-only, no remote SaaS control plane, adopt-existing-panes workflow first, managed session creation deferred to FEAT-013."

## Summary

FEAT-011 turns `agenttowerd` into a stable **local-only application backend** for a future packaged desktop control panel (first target: Flutter desktop on Windows, macOS, Linux). It introduces a deliberate, versioned, app-facing namespace (`app.*`) over the **existing** newline-delimited JSON Unix socket so a UI process can render every primary AgentTower operational surface — daemon health, containers, panes, agents, log attachments, events, queue, routes — and perform every adopt-mode mutation **without parsing human-readable CLI output**.

FEAT-011 is post-MVP (depends on FEAT-001..FEAT-010). It is **backend contract only**: no Flutter UI, no managed tmux session/pane creation (deferred to FEAT-013), no network listener, no hosted/SaaS control plane, no multi-user remote collaboration.

Three core design decisions are fixed in this spec:

1. **A new `app.*` method namespace is added alongside the existing socket methods.** Existing CLI-facing methods (`ping`, `status`, `list_agents`, `register_self`, `route add`, etc.) remain unchanged and continue to be supported as-is for FEAT-002..FEAT-010 callers. The app namespace is a **façade** built on the same daemon-internal validation and persistence paths — never a parallel write path.
2. **The app identifies itself via a per-process opaque session token** issued by `app.hello` and presented on every subsequent `app.*` call. The token is local-only, has no user identity, and rides on top of the existing same-machine trust model (Unix socket file permissions + `SO_PEERCRED` UID match to the host user, FEAT-002 §23).
3. **The contract is versioned via `app_contract_version` (major.minor)** returned from `app.hello`. Additive minor changes do not break clients; major bumps require client opt-in.

## Clarifications

### Session 2026-05-19

- Q: List pagination — default and maximum `limit` for `app.<entity>.list`? → A: Default `limit = 50`, hard cap `limit = 200`. Requests above 200 MUST fail with `validation_failed` and `details.field == "limit"`.
- Q: Concurrency semantics for `app.agent.update` / `app.route.update` when two app sessions (or app + CLI) update the same row? → A: Last-write-wins. No `expected_version` / `etag` in FEAT-011. Mutation responses return the post-update row so the app can refresh immediately. `stale_object` remains scoped to queue lifecycle / terminal-state guards, not entity updates.
- Q: Idempotency / retry semantics on side-effectful mutations when the socket drops between request and response? → A: Add an optional `idempotency_key` to `app.send_input` only, scoped per `(app_session_id, idempotency_key)`. A duplicate retry within the dedupe window MUST return the original `message_id` and include `deduplicated: true` on the success envelope. Other app mutations rely on their existing natural idempotency (`update` by value, `route.add` by identity) or closed-set guards (`pane_already_registered`, `stale_object`); no global idempotency mechanism is introduced.
- Q: Initial `capability_flags` set at v1.0? → A: `capability_flags = {}` (empty object) at v1.0. All FEAT-011 methods are required and inferred from `app_contract_version` support, not flags. The field MUST still be present in every `app.hello` response so clients can rely on it. Future optional features (e.g., event stream subscribe, managed pane create) add named flags additively in later minors.
- Q: `app.scan.*` `wait=true` timeout cap and client-cancel behavior? → A: Hard cap `wait=true` at **30 s**. On timeout, the response MUST be a structured failure with `code == "scan_timeout"` and `details.scan_id` populated so the app can poll `app.scan.status`. Client socket disconnect MUST NOT cancel an in-flight scan; the scan completes server-side and remains reachable via the same `scan_id` on a later `app.scan.status` call.

### Session 2026-05-18

The following decisions are recorded as design defaults. They may be revisited by `/speckit.clarify` if the operator wants them surfaced as explicit questions; otherwise they bind the rest of the FEAT-011 design.

- **Q: Should the desktop app consume the existing socket API directly, or a new app namespace over the same socket?**
  → A: **New `app.*` namespace on the same socket.** Existing methods remain supported unchanged for the CLI; the app namespace adds aggregate/summary reads, app-suitable mutation envelopes, and bootstrap/readiness calls tuned for a UI consumer. Internally, both surfaces dispatch into the same daemon services so validation and persistence behavior are identical.
- **Q: How does the app identify itself?**
  → A: **Local app session marker** issued by `app.hello`. The daemon assigns an opaque `app_session_token` (uuid v4, kept in memory only, not persisted) and an `app_session_id` (short numeric, useful for audit). The client echoes the token on every subsequent `app.*` call. Sessions are best-effort scoped to the calling process — when the socket connection that called `app.hello` closes, the session is invalidated. There is no per-user identity; the underlying trust assumption remains "same-machine, host UID" as enforced by Unix socket permissions and SO_PEERCRED (already required by FEAT-002).
- **Q: What is the bootstrap / readiness contract?**
  → A: **Two calls.** `app.hello` is the cheap handshake — proves the socket is reachable, returns daemon identity, schema/runtime versions, app contract version, supported capability flags, and a fresh session token. `app.readiness` returns a structured "is the local runtime healthy enough to render the control panel?" assessment with a top-level `state ∈ {ready, degraded, unavailable}` and per-subsystem rows (docker, tmux discovery, sqlite, jsonl, routing worker, log attachment workers).
- **Q: Which views need aggregate responses rather than forcing the app to compose many small calls?**
  → A: **One `app.dashboard` call** returns the home-view payload (counts, top-line health, the few "most-recent" event/queue/route rows). Individual list pages (containers, panes, agents, queue, routes, events) have their own `app.<entity>.list` calls. Detail pages call `app.<entity>.detail`. No deep cross-joins required client-side for the dashboard or the entity list pages.
- **Q: How is version compatibility surfaced?**
  → A: **`app_contract_version` is `MAJOR.MINOR`** (e.g., `1.0`). `app.hello` returns the version the daemon implements plus a `supported_minor_range` for the current major (e.g., `1.0–1.0` initially). A newer-app/older-daemon mismatch on major returns `app_contract_major_unsupported` from `app.hello` with the daemon's actual version, and the client MUST refuse to call any other `app.*` method. Newer-daemon/older-app is always allowed within the same major (additive evolution rule, see FR-035).
- **Q: What distinguishes "discovered but unmanaged" panes from "registered agents" in the contract?**
  → A: **Two distinct read types and an explicit adopt mutation.** `app.pane.list` / `app.pane.detail` return discovered tmux panes (FEAT-004 `panes` rows) including a derived `registered: bool` and, if registered, the `agent_id` they map to. `app.agent.list` / `app.agent.detail` return registered agents (FEAT-006 `agents` rows). The adopt-mode mutation `app.agent.register_from_pane` is the only path the app uses to promote a discovered pane to a registered agent; it is **explicitly scoped to host-driven registration** (no `register-self` semantics, no agent-side execution) and is rejected for already-registered panes with `pane_already_registered`.
- **Q: Which operations are synchronous vs asynchronous from the app's perspective?**
  → A: **All FEAT-011 mutations are synchronous from the app's perspective**, returning a final-state envelope. Scans (`app.scan.containers`, `app.scan.panes`) accept an optional `wait: bool` (default `true`): when `true`, the call blocks until the scan cycle completes and returns the post-scan state; when `false`, the call returns immediately with a `scan_id` the app can poll via `app.scan.status`. Long-running event/queue follow streams are **not** introduced in FEAT-011 (event stream subscription is deferred to a follow-up feature); the app polls `app.events.list` / `app.queue.list` with cursor pagination instead.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — App boots, learns the local runtime state, and renders a usable dashboard (Priority: P1)

A packaged desktop control panel launches on a workstation. Before showing any AgentTower-specific UI, it locates the daemon socket, performs the `app.hello` handshake, and reads `app.readiness` to decide whether to display the operational control panel, a degraded-mode banner, or a setup-required screen. Once `ready` or `degraded`, the app issues a single `app.dashboard` call and renders aggregate counts, daemon health, and the most recent events/queue/route activity. Throughout, the app never parses any human CLI text.

**Why this priority**: This is FEAT-011 reduced to one slice. Without a stable handshake, readiness signal, and aggregate dashboard the app cannot legitimately open a window. Every other story in this spec depends on this happy path working. The full value proposition — "Flutter operates AgentTower without scraping CLI output" — is proven by this one story.

**Independent Test**: With a packaged daemon installed and FEAT-001..FEAT-010 already shipped, a test harness imitating the app:

1. Opens the configured daemon Unix socket; if the socket file is missing or unreadable, the harness MUST receive a structured "socket missing / permission denied" failure from a single `app.preflight` call (which does not require the socket to be open) OR an OS-level connection error mapped through the client library — in either case the failure is structured, not log-scraped.
2. Calls `app.hello` (no params beyond optional `client_id` / `client_version`) and receives `app_session_token`, `app_session_id`, `daemon_version`, `schema_version`, `app_contract_version`, `supported_minor_range`, `host_user_id`, and `capability_flags`.
3. Calls `app.readiness` with the session token and receives `state ∈ {ready, degraded, unavailable}` plus per-subsystem rows.
4. Calls `app.dashboard` and receives a single payload that includes: container counts (active/inactive/degraded), pane counts (total/registered/unregistered), agent counts (by role), log-attachment counts (active/degraded/none), queue counts (pending/in-flight/blocked), route counts (enabled/disabled), the N most-recent durable events, the N most-recent queue rows, and recent route activity — all as structured JSON, all without log scraping.

**Acceptance Scenarios**:

1. **Given** a healthy local AgentTower install with the daemon running, **When** the harness calls `app.hello`, **Then** the response includes a non-empty `app_session_token`, an `app_contract_version` of the form `MAJOR.MINOR`, a `daemon_version` matching the running daemon, and `state == "ok"`.
2. **Given** a healthy install, **When** the harness calls `app.readiness`, **Then** the response includes `state == "ready"` and per-subsystem rows for at least `docker`, `tmux_discovery`, `sqlite`, `jsonl`, `routing_worker`, `log_attachment_workers`, each with `status ∈ {ok, degraded, unavailable}` and a structured `reason` field that is the empty string when `status == "ok"`.
3. **Given** a healthy install with some active and inactive containers, registered and unregistered panes, attached and unattached logs, and at least one enabled route, **When** the harness calls `app.dashboard`, **Then** the response contains counts and recent-activity rows for every primary surface (containers, panes, agents, log-attachments, events, queue, routes) and the harness can render every count and every row from structured fields alone.
4. **Given** the daemon is not running, **When** the harness performs the preflight ("can I open the socket?") check, **Then** the harness receives a structured failure naming `daemon_unavailable` or `socket_missing` (closed-set codes) and the failure is distinguishable from a generic "EOF / connection reset" race.
5. **Given** the daemon is running but Docker is unavailable (degraded), **When** the harness calls `app.readiness`, **Then** the response has `state == "degraded"`, the `docker` subsystem row has `status == "unavailable"` with a human-actionable `reason`, and `app.dashboard` still returns successfully with container counts at zero and a degraded flag.

---

### User Story 2 — App lists discovered panes and adopts one into a registered agent (Priority: P1)

The control panel renders a "Panes" tab. The user sees every tmux pane the daemon has discovered inside every active bench container, distinguishes panes that are already registered as agents from panes that are still unmanaged, selects an unregistered pane, fills in role/capability/label/project from a structured form, and clicks Adopt. The daemon validates and persists the new agent record using the **same** code path the existing `register-self` CLI uses, returns the resulting agent envelope to the app, and the panes tab refreshes with the pane now marked `registered: true` linked to the new `agent_id`.

**Why this priority**: Adopt-existing-panes is the explicit MVP workflow for the first packaged app per the FEAT-011 brief. Managed session creation is deferred to FEAT-013, so the app's only entry point for promoting tmux to AgentTower must be reliable and entirely structured. Until this works, the desktop app is read-only.

**Independent Test**: With at least one running bench container exposing at least one tmux pane that has not yet registered itself, a test harness:

1. Calls `app.scan.panes` with `wait=true` (so the daemon rediscovers panes) and receives the post-scan pane count.
2. Calls `app.pane.list` and identifies at least one pane with `registered == false`.
3. Calls `app.agent.register_from_pane` with the pane's structured identity (container_id, tmux_socket, session_name, window_index, pane_index, pane_id) plus role, capability, label, project_path. The mutation returns a success envelope containing the new `agent_id` and the full agent detail.
4. Calls `app.pane.list` again and confirms that same pane now has `registered == true` and `agent_id` set to the just-created agent.
5. Calls `app.agent.detail` for that `agent_id` and confirms the role/capability/label/project_path/container/pane fields match the inputs from step 3.

**Acceptance Scenarios**:

1. **Given** at least one running bench container with one unregistered tmux pane, **When** the harness calls `app.scan.panes` with `wait=true`, **Then** the response includes a `scan_id`, `state == "completed"`, the total panes discovered, and the per-container/per-tmux-server breakdown.
2. **Given** the discovered pane is unregistered, **When** the harness calls `app.pane.list`, **Then** that pane appears with `registered == false`, `agent_id == null`, and the same container/tmux/session/window/pane identity fields exposed in FEAT-004 `panes` rows.
3. **Given** the harness calls `app.agent.register_from_pane` with valid inputs, **When** the daemon validates the request, **Then** the response is a success envelope containing `agent_id`, full agent fields, and `app_contract_version`, and the new `agents` row is durable in SQLite.
4. **Given** the same pane is already registered, **When** the harness calls `app.agent.register_from_pane` again, **Then** the response is a structured failure with `code == "pane_already_registered"`, the existing `agent_id` in `details`, and no second `agents` row is created.
5. **Given** the role argument is invalid (e.g., not in the FEAT-006 closed set), **When** the harness calls `app.agent.register_from_pane`, **Then** the response is a structured failure with `code == "validation_failed"` and `details.field == "role"`.

---

### User Story 3 — App drives queue, routes, and log-attachment operator actions (Priority: P2)

Once panes are adopted, the control panel must let the operator do day-to-day routing work: approve / delay / cancel queue rows (FEAT-009 actions), add / remove / enable / disable routes (FEAT-010 actions), attach / detach durable logs (FEAT-007), update an agent's role / capability / label, and send arbitrary structured input to a permitted target. Every action runs through the same daemon validation as the CLI; the app receives the same closed-set error codes and the same post-mutation state.

**Why this priority**: This is the second wave of value. The dashboard + adopt loop covers "see the world and onboard new agents." This story covers "actually operate AgentTower from the panel" — the reason a desktop app exists in the first place. It is P2 because none of the underlying mutations are net-new (they already exist as FEAT-007 / FEAT-009 / FEAT-010 CLI commands); FEAT-011 just exposes them through structured app methods.

**Independent Test**: With the FEAT-009 queue and FEAT-010 routing layer running and at least one master + one slave registered, a test harness:

1. Creates a route via `app.route.add`, confirms it appears in `app.route.list` with `enabled == true`, then disables it via `app.route.update` (`enabled=false`) and confirms `enabled == false`.
2. Triggers a synthetic queue row via `app.send_input` (master → slave) and confirms `app.queue.list` includes it with the expected `state`.
3. Approves a pending arbitration via `app.queue.approve`, delays another via `app.queue.delay`, and cancels a third via `app.queue.cancel`; each returns the post-mutation row state and the row is updated in `app.queue.list`.
4. Attaches a log to a registered agent via `app.log.attach`, observes `log_attached == true` in `app.agent.detail`, then detaches via `app.log.detach` and observes `log_attached == false`.
5. Updates the agent's role / capability / label via `app.agent.update` and confirms the new values in `app.agent.detail`.

**Acceptance Scenarios**:

1. **Given** the harness calls `app.route.add` with valid parameters, **When** the response returns, **Then** the response is a success envelope containing the new `route_id`, and `app.route.list` shows the route enabled.
2. **Given** a route exists, **When** the harness calls `app.route.update` with `enabled=false`, **Then** the response includes the updated `enabled` value and matches what `app.route.list` returns next.
3. **Given** a pending queue row exists, **When** the harness calls `app.queue.approve`, **Then** the response returns the post-mutation row state and the audit JSONL receives the appropriate FEAT-009 audit event.
4. **Given** the same queue row id is approved twice, **When** the second `app.queue.approve` is called, **Then** the response is a structured failure with `code == "stale_object"` (terminal-state guard) and no duplicate audit row is written.
5. **Given** the harness calls `app.agent.update` with a role outside the FEAT-006 closed set, **When** the daemon validates, **Then** the response is `validation_failed` with `details.field == "role"`.
6. **Given** the harness calls `app.log.attach` for an agent whose container is inactive, **When** the daemon validates, **Then** the response is a structured failure with a closed-set code such as `container_inactive` or `log_attach_blocked`.

---

### User Story 4 — App correctly surfaces degraded and unavailable states (Priority: P2)

The control panel must show meaningful UX when something on the host is wrong: the daemon is not running, the socket file is missing, the schema/runtime version is incompatible, Docker is unavailable, no bench containers are discovered, containers exist but no panes, panes exist but none are registered. Every one of these cases must be a structured response from the contract — the app never parses a human-readable error.

**Why this priority**: A control panel that crashes or silently shows an empty view when the daemon is degraded is worse than the CLI. The brief explicitly demands "fail fast with actionable diagnostics." P2 because the happy path (Stories 1–3) is the first thing to prove; degraded UX hardens it.

**Independent Test**: A test harness manually induces each failure class and verifies the contract behavior:

1. Daemon process not running → preflight returns `daemon_unavailable`.
2. Socket file missing → preflight returns `socket_missing`.
3. Daemon running but a major version newer than the client expects → `app.hello` returns `app_contract_major_unsupported` with the daemon's actual version.
4. Daemon running but Docker unavailable → `app.readiness.state == "degraded"`, `docker.status == "unavailable"`.
5. Docker available but no bench containers discovered → `app.dashboard.containers.active == 0`, `app.readiness.state ∈ {ready, degraded}` (degraded only if other subsystems also fail), readiness row carries `containers_discovered == false`.
6. Containers discovered but no panes → `app.dashboard.panes.total == 0`, readiness row carries `panes_discovered == false`.
7. Panes discovered but none registered → `app.dashboard.agents.total == 0`, `app.dashboard.panes.unregistered > 0`.

**Acceptance Scenarios**:

1. **Given** the daemon is not running, **When** the harness performs the preflight, **Then** the response identifies `daemon_unavailable` (closed-set code) distinctly from `socket_missing` and from generic OS errors.
2. **Given** the daemon's `app_contract_version` major is newer than the harness's expected major, **When** the harness calls `app.hello`, **Then** the response returns `app_contract_major_unsupported` and includes both versions; the harness MUST NOT call any other `app.*` method.
3. **Given** Docker is unavailable, **When** the harness calls `app.readiness`, **Then** the `docker` subsystem row has `status == "unavailable"`, `reason != ""`, and the top-level `state` is at least `degraded`.
4. **Given** zero bench containers are discovered, **When** the harness calls `app.dashboard`, **Then** the response is successful, `containers.active == 0`, and a structured `hints[]` array suggests at least one actionable next step (e.g., `start_bench_container`, `check_container_filter`).

---

### User Story 5 — App and daemon negotiate contract version cleanly across upgrades (Priority: P3)

A newer app talks to an older daemon, or an older app talks to a newer daemon. The contract MUST detect major-version mismatch in `app.hello` and refuse. Within a major version, additive minor changes (new optional fields, new optional methods) MUST be transparent — older clients ignore unknown fields and never call new methods; newer clients use new optional methods only when `capability_flags` advertises them.

**Why this priority**: Required for the upgrade story to work without breaking already-deployed app builds. P3 because the very first packaged app and daemon will ship together; cross-version drift becomes a problem after.

**Independent Test**: A test harness with one daemon at `app_contract_version=1.0` and one synthetic client emitting `client_app_contract_major=2`:

1. The handshake fails with `app_contract_major_unsupported`, no session is issued, and no other `app.*` call is accepted.

A second harness simulating a newer client (`client_app_contract_major=1`) but using a method only available at minor `1.1` against a `1.0` daemon:

2. `app.hello` succeeds; the client inspects `capability_flags` and chooses not to call the `1.1`-only method, OR if it does, receives a structured `unknown_method` failure.

**Acceptance Scenarios**:

1. **Given** a major-version mismatch, **When** `app.hello` is called, **Then** the response is `app_contract_major_unsupported`, no session token is issued, and subsequent `app.*` calls fail with `app_session_required`.
2. **Given** a within-major minor difference, **When** the client calls `app.hello`, **Then** the response includes `capability_flags` so the client can decide whether to use optional newer methods.
3. **Given** the client calls an `app.*` method not implemented at the daemon's minor, **When** the daemon dispatches, **Then** the response is `unknown_method` (closed-set code) and the daemon's running state is unchanged.

---

### Edge Cases

- **Socket file present but daemon crashed mid-init**: the preflight or `app.hello` must surface `daemon_unavailable` rather than hang. The daemon socket file existing without an alive process is the FEAT-002 stale-pid scenario; the app contract MUST inherit that semantics with a closed-set code.
- **Concurrent app sessions**: more than one packaged app instance MAY connect at once; each receives its own `app_session_token`. The daemon does not gate concurrency between sessions; all mutations remain ordered by the same daemon-side locks as the CLI.
- **App calls `app.*` without first calling `app.hello`**: returns `app_session_required` from every `app.*` method except `app.hello` itself and the lightweight `app.preflight`.
- **Session token replay across reconnects**: closing the underlying socket connection invalidates the session. Reconnecting and presenting the old token returns `app_session_expired`; the app MUST call `app.hello` again.
- **Permission boundary**: any caller that successfully passes the SO_PEERCRED + socket-permission gate is treated as fully authorized at the daemon level — the app contract does not introduce a finer-grained per-method authorization layer in FEAT-011. The trust assumption is "same host UID" and is documented explicitly so the rest of the security boundary is auditable.
- **Adopt-mode race**: between `app.pane.list` and `app.agent.register_from_pane`, another caller (CLI inside the container, or another app session) may register the pane first. `app.agent.register_from_pane` MUST return `pane_already_registered` with the existing `agent_id` rather than overwriting silently.
- **Dashboard atomicity**: `app.dashboard` is read-only and best-effort consistent — it does not take a single global snapshot. Counts within one response are read sequentially and may slightly disagree under heavy concurrent mutation; this is acceptable for a UI dashboard and is documented in the contract.
- **Schema version vs contract version drift**: the underlying SQLite/JSONL `schema_version` is independent from `app_contract_version`. A daemon that supports the same `app_contract_version` MUST behave identically from the app's perspective even if its internal schema migrated. `app.hello` returns both for transparency.
- **No network listener invariant**: FEAT-011 MUST NOT introduce any non-Unix-socket listener, even behind a flag. Any future remote/multi-host access is explicitly a different feature and out of scope.

## Requirements *(mandatory)*

### Functional Requirements

#### Contract surface and namespace

- **FR-001**: The daemon MUST expose a new socket method namespace prefixed `app.*` over the existing Unix socket. Newline-delimited JSON request/response framing per FEAT-002 §19 is reused unchanged.
- **FR-002**: All existing socket methods (FEAT-002..FEAT-010, e.g., `ping`, `status`, `list_agents`, `register_self`, `set_role`, `attach_log`, `send_input`, `queue *`, `route *`, `routing enable|disable`, `events`) MUST continue to be supported with their current request/response shapes for FEAT-011. The `app.*` namespace is additive, not a replacement.
- **FR-003**: The daemon MUST NOT introduce any non-Unix-socket listener (TCP, HTTP, WebSocket, named pipe over a non-Unix mechanism) as part of FEAT-011. Local-only is invariant.
- **FR-004**: Internally, every `app.*` method MUST dispatch into the same daemon-internal service layer used by the existing CLI-facing methods so that validation, persistence, audit JSONL emission, and FEAT-009/FEAT-010 worker integration are identical regardless of caller surface.

#### Identity, sessions, and authorization

- **FR-005**: The daemon MUST treat any caller reaching the socket as authorized at the host-user level, gated by the existing FEAT-002 socket file permissions and SO_PEERCRED UID check. FEAT-011 introduces no additional per-method ACL.
- **FR-006**: The app MUST initiate every session with `app.hello`. The daemon MUST issue an opaque `app_session_token` and a numeric `app_session_id`, neither of which is persisted across daemon restarts.
- **FR-007**: Every `app.*` method other than `app.hello` and `app.preflight` MUST require a valid `app_session_token` and return `app_session_required` when missing or `app_session_expired` when invalid/stale.
- **FR-008**: The daemon MUST invalidate the session when the underlying socket connection that issued it closes. The same client MAY reconnect and call `app.hello` again to obtain a new session.
- **FR-009**: The daemon SHOULD record `app_session_id` in audit JSONL rows produced by app-driven mutations so an operator can attribute changes to a UI session vs CLI calls. Recording MUST NOT include the opaque `app_session_token` itself.

#### Bootstrap and readiness

- **FR-010**: `app.hello` MUST return at minimum: `app_session_token`, `app_session_id`, `daemon_version`, `schema_version`, `app_contract_version` (string `MAJOR.MINOR`), `supported_minor_range` (object with `min` and `max` strings), `host_user_id`, `capability_flags` (object with named boolean flags), and `state == "ok"`. The set of fields is **additive**: future minor versions may add fields but MUST NOT remove or rename existing ones.
- **FR-011**: `app.preflight` MUST be callable without `app_session_token` and MUST be safe before `app.hello`. It returns a small envelope reporting `socket_reachable`, `daemon_reachable`, and a closed-set `code` ∈ {`ok`, `daemon_unavailable`, `socket_missing`, `socket_permission_denied`} so the app can fail fast on the lowest-level errors.
- **FR-012**: `app.readiness` MUST return a top-level `state ∈ {ready, degraded, unavailable}` and a `subsystems` array. Each subsystem row MUST include: `name`, `status ∈ {ok, degraded, unavailable}`, `reason` (string, empty when `status == "ok"`), and an optional `hint` field for human-actionable next steps.
- **FR-013**: The `subsystems` array MUST cover at minimum: `docker`, `tmux_discovery`, `sqlite`, `jsonl`, `routing_worker`, `log_attachment_workers`. The contract MAY add subsystems in additive minor releases.
- **FR-014**: `app.readiness` MUST distinguish "no bench containers discovered" (a readiness hint) from "Docker unavailable" (a degraded subsystem). The former is `state == ready` (or `degraded` only if another subsystem fails) with a hint; the latter is `degraded`.

#### Aggregate dashboard

- **FR-015**: `app.dashboard` MUST return a single response payload containing structured counts and recent-activity rows for: containers, panes, agents, log_attachments, events, queue, routes.
- **FR-016**: Container counts MUST include at minimum `active`, `inactive`, and `degraded_scan`. Pane counts MUST include `total`, `registered`, `unregistered`. Agent counts MUST include totals plus per-role breakdown for the FEAT-006 closed set (`master`, `slave`, `swarm`, `test-runner`, `shell`, `unknown`). Queue counts MUST include `pending`, `in_flight`, `delivered`, `cancelled`, `expired` (using the FEAT-009 closed set). Route counts MUST include `enabled` and `disabled`.
- **FR-017**: The `recent` sub-payloads MUST include compact rows (id, timestamp, type, key labels, derived summary) sufficient to render a "Recent activity" UI block without a follow-up call. Default size is `10` per surface; the app MAY request a different size via an optional `recent_limit` parameter bounded by `[1, 50]`.
- **FR-018**: `app.dashboard` MUST be read-only, MUST NOT take any global lock, and MUST tolerate slight inter-surface inconsistency under concurrent mutation. This is explicitly called out in the contract documentation.

#### Read surfaces (per entity)

- **FR-019**: For each of the following entities the daemon MUST expose `app.<entity>.list` and `app.<entity>.detail`: `container`, `pane`, `agent`, `log_attachment`, `event`, `queue`, `route`.
- **FR-020**: Every `app.<entity>.list` response MUST include: a `rows[]` array, a `total` (or `total_estimate` if pagination cursors are used), an explicit ordering rule documented per surface, and a stable cursor for pagination (`cursor_next`).
- **FR-020a**: Every `app.<entity>.list` MUST accept an optional `limit` parameter with default `50` and hard cap `200`. A request with `limit > 200` MUST be rejected with `validation_failed` and `details.field == "limit"`. A request with `limit < 1` or a non-integer `limit` MUST be rejected with the same code and field.
- **FR-021**: Default ordering MUST be: `containers` by `name` ASC, `panes` by `(container_name, session_name, window_index, pane_index)` ASC, `agents` by `(role_priority, registered_at)` ASC, `log_attachments` by `last_output_at` DESC, `events` by `(event_id)` DESC (newest first), `queue` by `(state_priority, created_at)` ASC, `routes` by `(created_at, route_id)` ASC. Each list method MAY accept an `order_by` override from a closed set defined per surface.
- **FR-022**: `app.pane.list` rows MUST include a derived `registered: bool` and a nullable `agent_id` so the app can render unmanaged vs managed panes without joining `agents` client-side.
- **FR-023**: `app.agent.list` rows MUST include the agent's container/pane identity plus a derived `log_attached: bool` and a derived `pane_active: bool`.
- **FR-024**: `app.event.list`, `app.queue.list`, and `app.route.list` MUST support filter parameters consistent with FEAT-008/FEAT-009/FEAT-010 closed-set fields (e.g., `event_type`, `origin`, `state`, `role`, `capability`, `route_id`, time-range `since`/`until`).

#### Adopt-mode mutation

- **FR-025**: `app.agent.register_from_pane` MUST accept a structured pane identity (`container_id`, `tmux_socket`, `session_name`, `window_index`, `pane_index`, `pane_id`) plus `role`, `capability`, `label`, optional `project_path`, optional `parent_agent_id`, optional `attach_log: bool`.
- **FR-026**: `app.agent.register_from_pane` MUST reuse the same daemon-side validation and persistence path as FEAT-006 `register-self`. It MUST NOT bypass any validation rule, including the "no silent promotion to master" rule (the operator may set `role=master` only if the existing FEAT-006 rules already allow it from a host-driven caller).
- **FR-027**: If the named pane is already registered, the response MUST be `pane_already_registered` with the existing `agent_id` in `details` and no second `agents` row created.
- **FR-028**: If the pane identity does not match a currently-discovered pane, the response MUST be `pane_not_found` and the app MUST be instructed to call `app.scan.panes` first.

#### Operator mutation surfaces

- **FR-029**: The contract MUST expose the following mutation methods, each returning a structured success envelope containing the post-mutation state of the affected entity: `app.scan.containers`, `app.scan.panes`, `app.agent.update` (role/capability/label/project), `app.log.attach`, `app.log.detach`, `app.send_input`, `app.queue.approve`, `app.queue.delay`, `app.queue.cancel`, `app.route.add`, `app.route.remove`, `app.route.update` (enable/disable only — per FEAT-010 immutability).
- **FR-030**: Every mutation MUST be synchronous from the caller's perspective and return the final post-mutation state in the response. `app.scan.containers` and `app.scan.panes` MAY accept `wait: bool` (default `true`); when `wait == false` the response returns immediately with a `scan_id` and the app polls `app.scan.status`.
- **FR-030a**: `app.agent.update` and `app.route.update` MUST be last-write-wins. FEAT-011 MUST NOT introduce an `expected_version` / `etag` / `If-Match` field on entity-update mutations. The mutation response MUST contain the full post-update row so the app can refresh its local view immediately. The closed-set code `stale_object` MUST NOT be returned by entity-update mutations; it remains scoped to queue lifecycle / terminal-state guards (FEAT-009).
- **FR-030b**: `app.scan.containers` and `app.scan.panes` with `wait == true` MUST enforce a hard timeout of **30 s**. On timeout, the response MUST be a structured failure with `code == "scan_timeout"` and `details.scan_id` populated so the app can poll `app.scan.status` to retrieve the eventual result. A client socket disconnect during an in-flight scan MUST NOT cancel the scan; the scan MUST complete server-side and remain reachable via the same `scan_id` on a later `app.scan.status` call.
- **FR-031**: `app.send_input` MUST go through the FEAT-009 message_queue and respect the FEAT-009 permission gate and global routing kill switch. The response MUST include the resulting `message_id` and queue row state.
- **FR-031a**: `app.send_input` MUST accept an optional `idempotency_key` (caller-supplied string). When present, the daemon MUST deduplicate against a store keyed by `(app_session_id, idempotency_key)`. A duplicate retry within the dedupe window MUST return the original `message_id` and include `deduplicated: true` on the success envelope; no second queue row is created and no duplicate audit JSONL entry is emitted. The dedupe store is per-session and in-memory only (lost across daemon restart or session close, which is acceptable because the same `app_session_id` cannot survive either). No other `app.*` mutation MUST accept `idempotency_key` in FEAT-011.
- **FR-032**: `app.route.add` / `app.route.remove` / `app.route.update` MUST go through the FEAT-010 route catalog and emit the same `route_created` / `route_updated` / `route_deleted` audit JSONL entries.

#### Error envelopes and closed-set codes

- **FR-033**: Every `app.*` response MUST use one of two envelope shapes: `{ok: true, app_contract_version, result}` for success or `{ok: false, app_contract_version, error: {code, message, details}}` for failure. The `app_contract_version` MUST always be present on the response so the app can detect drift.
- **FR-034**: `error.code` MUST come from a documented closed set. Initial closed set (additive in future minors): `app_session_required`, `app_session_expired`, `app_contract_major_unsupported`, `unknown_method`, `validation_failed`, `not_found`, `stale_object`, `pane_already_registered`, `pane_not_found`, `agent_not_found`, `route_not_found`, `queue_message_not_found`, `scan_timeout`, `daemon_unavailable`, `socket_missing`, `socket_permission_denied`, `docker_unavailable`, `tmux_unavailable`, `container_inactive`, `log_attach_blocked`, `routing_disabled`, `permission_denied`, `internal_error`. Free-form prose belongs in `error.message` and `error.details`, never in `error.code`.

#### Versioning and evolution

- **FR-035**: `app_contract_version` MUST follow `MAJOR.MINOR` semantics. Within a major: only additive changes (new optional fields, new optional methods, new closed-set codes, new readiness subsystems, new capability flags). Removing or renaming any of the above MUST increment major.
- **FR-036**: A client whose declared `client_app_contract_major` does not match the daemon's major MUST receive `app_contract_major_unsupported` from `app.hello`, no session token, and `app_session_required` from every other `app.*` call.
- **FR-037**: Clients MUST treat unknown response fields as ignorable so newer daemons remain compatible.
- **FR-038**: Daemons MUST treat unknown request fields as ignorable so newer clients remain compatible within a major.
- **FR-039**: `capability_flags` returned by `app.hello` MUST declare optional methods/features available at the daemon's minor. Clients MUST check the flag before invoking an optional method. At v1.0 specifically, `capability_flags` MUST be the empty object `{}` because every FEAT-011 method is required; the field MUST still be present so clients can rely on its shape. Optional methods introduced in later minors (e.g., event stream subscribe, managed pane create) MUST add named boolean flags here additively.

#### Local-only security boundary

- **FR-040**: FEAT-011 MUST NOT alter the FEAT-002 socket-permission model. The socket file remains user-owned, mode-restricted, and accessed only by clients on the same host (host OR mounted into a bench container).
- **FR-041**: The daemon MUST reject any `app.*` call whose peer UID does not match the host user (same rule that already applies to existing methods via FEAT-002).
- **FR-042**: The daemon MUST NOT expose `app.routing.enable` / `app.routing.disable` to bench-container callers — the host-only constraint from FEAT-009 carries over via `routing_toggle_host_only` (or a closed-set equivalent) when called from a container.
- **FR-043**: The contract MUST NOT introduce any new persisted secret, token, key, or remote authentication primitive.

#### Observability

- **FR-044**: The daemon SHOULD emit JSONL audit entries for app-initiated mutations consistent with existing FEAT-006..FEAT-010 audit semantics. An app-initiated mutation row SHOULD carry an `origin == "app"` marker plus `app_session_id` so operators can distinguish app-driven changes from CLI-driven ones.
- **FR-045**: `app.readiness` and `app.dashboard` MUST be cheap and side-effect-free. They MUST NOT trigger a discovery scan (the app uses `app.scan.*` explicitly when it wants one).

### Key Entities

- **App Session**: Per-connection identity held in memory by the daemon. Attributes: `app_session_token` (opaque), `app_session_id` (numeric, audit-friendly), `client_id` (informational), `client_version` (informational), `app_contract_major` (the major the client claims to speak), `connection_started_at`. Sessions are not durable.
- **App Contract Version**: A `MAJOR.MINOR` value advertised by `app.hello`. Additive evolution within a major; major bumps require client opt-in.
- **Readiness Subsystem Row**: `name`, `status ∈ {ok, degraded, unavailable}`, `reason`, optional `hint`. Aggregated to a top-level `state`.
- **Dashboard Snapshot**: A single read-only payload containing structured counts (per surface) and a small set of recent rows per surface; not durable, no global lock.
- **App-Facing Container/Pane/Agent/Log Attachment/Event/Queue Message/Route view models**: Each derived from the same underlying SQLite/JSONL state as the CLI's read surfaces, exposed with explicit ordering and derived summary fields suitable for direct UI rendering.
- **Adopt Mutation Input**: Structured pane identity (`container_id`, `tmux_socket`, `session_name`, `window_index`, `pane_index`, `pane_id`) + agent metadata (`role`, `capability`, `label`, optional `project_path`, optional `parent_agent_id`, optional `attach_log`).
- **App-Originated Mutation Audit Row**: A JSONL entry produced by an app-driven mutation, carrying `origin == "app"` and `app_session_id` for operator-side attribution.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A control panel can render the dashboard, panes, agents, log-attachments, queue, routes, and events surfaces using `app.*` responses alone, with **zero** lines parsing human CLI text. Verified by an integration harness that asserts no `agenttower` subprocess output is consumed for any UI-rendering code path.
- **SC-002**: From process start to first rendered dashboard payload (cold start, daemon already running), the app reaches `app.dashboard` success in **≤ 500 ms** on a workstation with at least one running bench container and at least one registered agent. Measured as wall-clock from `app.hello` request send to `app.dashboard` response receive in a no-cache test.
- **SC-003**: 100% of FEAT-011 mutation methods return a structured success envelope or a closed-set error code; no method returns a free-form prose error in `error.code`. Verified by a contract test that asserts `error.code` is in the documented closed set for **every** error path covered in the contract test suite, with **zero** exceptions.
- **SC-004**: Adopt-mode round-trip — `app.scan.panes` → `app.pane.list` → `app.agent.register_from_pane` → `app.agent.detail` — completes in **≤ 2 s** wall-clock and produces an `agents` row indistinguishable from a CLI `register-self` row for the same pane, validated by a side-by-side SQLite fixture comparison.
- **SC-005**: Major-version drift is enforced: a synthetic client with mismatched major receives `app_contract_major_unsupported` from `app.hello` and `app_session_required` from every other `app.*` method, with **zero** stray fields and **zero** internal state mutation on the daemon side. Verified by a contract test using a synthetic client identity.
- **SC-006**: Local-only invariant: a packet capture during the FEAT-011 contract test suite shows **zero** non-Unix-socket I/O from the daemon attributable to FEAT-011, and the daemon process MUST NOT bind any TCP or non-Unix-domain socket during the entire test run.
- **SC-007**: Degraded-state coverage: each of the readiness failure modes called out in the Edge Cases (daemon unavailable, socket missing, schema/version incompatible, Docker unavailable, no bench containers, no panes, no registered agents) produces a structured, app-renderable state where the app can decide UI behavior **without** parsing any prose. Verified by an integration harness covering each failure mode.
- **SC-008**: Audit attribution: every app-driven mutation in the contract test suite produces at least one JSONL audit row with `origin == "app"` and the issuing `app_session_id`. The opaque `app_session_token` MUST NOT appear in any JSONL row.
- **SC-009**: Within-major additive evolution does not break older clients: a synthetic minor-N client running against a minor-(N+1) daemon completes the dashboard + adopt + queue + route flows with **zero** failures attributable to unknown response fields and **zero** failures attributable to unknown closed-set codes (clients are expected to surface unknown codes as `internal_error`-class display states without crashing).
- **SC-010**: Operator parity: at least the FEAT-006 (set role / set capability / set label), FEAT-007 (attach log / detach log), FEAT-009 (queue approve / delay / cancel), FEAT-010 (route add / remove / enable / disable), and the FEAT-006 register-self equivalent (`app.agent.register_from_pane`) are all reachable through `app.*` and each produces SQLite/JSONL state byte-for-byte identical (modulo `origin`/`app_session_id` metadata) to the equivalent CLI invocation. Verified by a fixture-comparison test.

## Assumptions

- FEAT-001 through FEAT-010 are shipped and stable. FEAT-011 builds on existing services (FEAT-002 socket, FEAT-003 container discovery, FEAT-004 pane discovery, FEAT-005 thin client, FEAT-006 agent registration, FEAT-007 log attachment, FEAT-008 event pipeline, FEAT-009 message queue, FEAT-010 routing layer) rather than reimplementing them.
- The packaged desktop app runs on the same host as the daemon (Windows/macOS/Linux). Bench-container thin clients are not the target consumer of `app.*`; only the host-resident app is.
- Operator UID identifies the trust boundary. The contract assumes the host user owns the daemon socket and the running app process. Multi-user desktops are out of scope (one user, one daemon, one or more concurrent app sessions).
- Same daemon, multiple app sessions, no cross-session isolation beyond per-connection lifetime. Two concurrent apps see the same mutations land in the same SQLite/JSONL.
- The Flutter target is informational. The contract is language-agnostic and could be consumed by a Rust, Swift, or Electron client as long as it speaks newline-delimited JSON over the Unix socket.
- The CLI continues to be the primary scriptable interface; `app.*` is the structured-UI interface. The two MUST never diverge in validation/persistence behavior.
- Event subscription/push (a long-running daemon→app event stream) is **deferred**. The app polls list endpoints with cursor pagination in FEAT-011. Adding a subscription is an additive minor change later.
- Managed tmux session/pane creation is **deferred to FEAT-013**. The adopt-existing-panes workflow is the only path to a registered agent for FEAT-011.
- No Antigravity, no TUI, no mobile, no remote multi-host, no hosted SaaS — all explicitly out of scope per the FEAT-011 brief.
- The opaque `app_session_token` is **not** a security boundary against malicious local processes; the security boundary remains the Unix socket file permissions and SO_PEERCRED UID check inherited from FEAT-002. The token's job is connection-scoped identity and audit attribution, nothing more.

## Out of Scope

- Flutter UI implementation (deferred to FEAT-012).
- Managed tmux session/pane creation, automatic agent launch (deferred to FEAT-013).
- A hosted website, SaaS backend, mobile app, remote multi-host control, TUI, Antigravity support — all explicitly excluded.
- Network listeners of any kind (TCP, HTTP, WebSocket). The contract is Unix-socket-only.
- Per-user authentication, RBAC, or sub-user permission models — the trust boundary remains "same host UID."
- A long-running daemon→app push/subscribe event stream — left for a follow-up additive minor release.
- Schema migration of existing SQLite tables purely for app-rendering convenience — FEAT-011 adds derived fields in the response envelopes, not new persisted columns.
- Cross-host federation or cluster mode — the daemon remains a single-host process.
