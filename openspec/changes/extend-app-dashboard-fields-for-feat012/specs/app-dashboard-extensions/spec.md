## ADDED Requirements

### Requirement: app.dashboard returns per-state pane counts

The daemon SHALL extend the `app.dashboard` success result with an
optional `counts.panes.by_state` field: a JSON object whose keys are
the members of the `PaneState` closed set and whose values are
non-negative integers counting the number of currently-discovered
panes in each state.

When the field is present it MUST contain a key for every member of
the `PaneState` closed set at the daemon's `app_contract_version`
minor; empty buckets MUST be reported as the integer `0` (not
omitted, not `null`). The field MAY be omitted entirely only by a
pre-`1.1` daemon; any daemon advertising
`app_contract_version >= "1.1"` MUST emit the field.

The `PaneState` closed set at v1.1 is exactly:
`{discovered-and-unmanaged, discovered-and-registered,
inactive-or-stale, discovery-degraded}`. `discovery-degraded` is
reserved at v1.1 and is always reported as `0` (the underlying
FEAT-004 per-pane discovery health signal is not surfaced yet, the
same reserved-key pattern used by container `degraded_scan` in
FR-016a and hint code `check_container_filter` in FR-014a).

Adding a new `PaneState` value in a future minor MUST be additive
per FR-035; renaming or removing a value MUST require a major bump.

#### Scenario: Healthy daemon at v1.1 reports per-state pane counts

- **GIVEN** a daemon at `app_contract_version = "1.1"` with one
  registered pane and two unadopted panes across one active container
- **WHEN** an authenticated app session calls `app.dashboard`
- **THEN** the success result `counts.panes.by_state` is present and
  equals `{"discovered-and-unmanaged": 2, "discovered-and-registered":
  1, "inactive-or-stale": 0, "discovery-degraded": 0}`
- **AND** every key from the `PaneState` closed set is present
- **AND** the existing v1.0 fields `counts.panes.{total, registered,
  unregistered}` are unchanged

#### Scenario: v1.0 client tolerates the new field

- **GIVEN** a daemon at `app_contract_version = "1.1"` and a client
  built against the FEAT-011 v1.0 contract that ignores unknown keys
- **WHEN** the client calls `app.dashboard`
- **THEN** the response is well-formed under the v1.0 schema (every
  v1.0 field present with the v1.0 types)
- **AND** the client reads the unchanged v1.0 fields without error

#### Scenario: Empty daemon reports all-zero buckets

- **GIVEN** a daemon at `app_contract_version = "1.1"` with zero panes
  discovered
- **WHEN** an authenticated app session calls `app.dashboard`
- **THEN** `counts.panes.by_state` is
  `{"discovered-and-unmanaged": 0, "discovered-and-registered": 0,
  "inactive-or-stale": 0, "discovery-degraded": 0}`
- **AND** the field is NOT omitted, NOT `null`, NOT `{}`

### Requirement: app.dashboard returns per-state agent counts

The daemon SHALL extend the `app.dashboard` success result with an
optional `counts.agents.by_state` field: a JSON object whose keys are
the members of the `AgentState` closed set and whose values are
non-negative integers.

When the field is present it MUST contain a key for every member of
the `AgentState` closed set; empty buckets MUST be reported as `0`.
Daemons advertising `app_contract_version >= "1.1"` MUST emit the
field.

The `AgentState` closed set at v1.1 is exactly:
`{active, inactive, partially_configured, log-attached, log-detached}`.

Bucket derivation rules (normative):

- `active` — registered agent whose pane is currently discovered AND
  whose container is `active`.
- `inactive` — registered agent whose pane is no longer discovered OR
  whose container is `inactive`.
- `partially_configured` — registered agent missing one of the
  required adopt-mode fields; at v1.1 this bucket is permitted to be
  always `0` (FEAT-011 adopt validation prevents it; the bucket is
  reserved for future minors that relax adopt validation).
- `log-attached` — agent has an active `log_attachments` row
  (FEAT-007 status `active`).
- `log-detached` — agent has no active `log_attachments` row (status
  is `detached`, `stale`, `superseded`, or no row at all).

`log-attached` / `log-detached` are reported as first-class buckets
and are orthogonal to `active` / `inactive`; therefore the sum of all
five buckets MAY exceed `counts.agents.total`. This is intentional
and MUST be documented in `closed-sets.md`.

Adding a new `AgentState` value in a future minor MUST be additive
per FR-035; renaming or removing a value MUST require a major bump.

#### Scenario: Mixed-state agents are bucketed correctly

- **GIVEN** a daemon at `app_contract_version = "1.1"` with two
  registered agents: agent A is active with logs attached; agent B is
  registered but its container is inactive
- **WHEN** an authenticated app session calls `app.dashboard`
- **THEN** the success result `counts.agents.by_state` equals
  `{"active": 1, "inactive": 1, "partially_configured": 0,
  "log-attached": 1, "log-detached": 1}`
- **AND** `counts.agents.total == 2`
- **AND** the sum across buckets (`1+1+0+1+1 = 4`) is allowed to
  exceed `total`

#### Scenario: by_state coexists with the unchanged by_role map

- **GIVEN** a v1.1 daemon
- **WHEN** an authenticated app session calls `app.dashboard`
- **THEN** `counts.agents.by_role` is present with its v1.0 shape
- **AND** `counts.agents.by_state` is present with the v1.1 shape
- **AND** both maps describe the same underlying agent set

### Requirement: app.dashboard returns a recently-skipped route counter

The daemon SHALL extend the `app.dashboard` success result with two
optional sibling fields on the `counts.routes` object:

- `recently_skipped_count: int` — the number of FEAT-010 arbitration
  decisions that resulted in a route skip within the last
  `recently_skipped_window_ms` milliseconds, measured at the time the
  `app.dashboard` request is handled.
- `recently_skipped_window_ms: int` — the size of the window the
  daemon actually used. At v1.1 the default value is `300000` (5
  minutes). Future minors MAY change the default; clients MUST read
  the value from the response rather than hard-coding it.

The daemon SHALL maintain the window in process memory and SHALL NOT
persist individual skip timestamps. A daemon restart resets the
counter to `0`; the post-restart count refills as new skips occur.

Both fields MUST be present together when reported; a daemon MUST
NOT emit one without the other. Daemons advertising
`app_contract_version >= "1.1"` MUST emit both fields.

#### Scenario: Daemon counts skips inside the active window

- **GIVEN** a v1.1 daemon that has recorded three FEAT-010 route
  skips: one 2 minutes ago, one 4 minutes ago, one 10 minutes ago
- **WHEN** an authenticated app session calls `app.dashboard`
- **THEN** `counts.routes.recently_skipped_count == 2` (the 10-minute
  entry is outside the 5-minute window)
- **AND** `counts.routes.recently_skipped_window_ms == 300000`

#### Scenario: Daemon restart resets the counter

- **GIVEN** a v1.1 daemon that recorded five skips, then restarted
- **WHEN** an authenticated app session calls `app.dashboard`
  immediately after restart with no further skips having occurred
- **THEN** `counts.routes.recently_skipped_count == 0`
- **AND** `counts.routes.recently_skipped_window_ms == 300000`

#### Scenario: Zero skips report explicit zero, not omission

- **GIVEN** a v1.1 daemon that has never recorded a skip
- **WHEN** an authenticated app session calls `app.dashboard`
- **THEN** `counts.routes.recently_skipped_count == 0` (present, not
  omitted, not `null`)

### Requirement: app.dashboard returns a daemon-computed recommended next action

The daemon SHALL extend the `app.dashboard` success result with a
top-level optional field `recommended_next_action`, shaped as either
`null` or a JSON object with these fields:

- `code` (string, required when the parent is non-null) — drawn from
  the closed set `{no_containers, no_panes_discovered,
  unadopted_panes_present, no_routes_configured, blocked_queue_drain,
  subsystem_degraded, all_clear}` at v1.1.
- `title` (string, required when the parent is non-null) — short
  English prose, ≤ 80 characters after trim.
- `detail` (string, optional) — longer English prose, ≤ 280
  characters after trim.
- `target` (object, optional) — `{kind: string, id: string}` pointing
  to the most relevant entity for the recommendation.

A sibling optional top-level field `recommended_next_action_refreshed_at`
SHALL be emitted alongside `recommended_next_action`, formatted as
an ISO-8601 UTC timestamp string (e.g., `"2026-05-24T18:42:03Z"`).
At v1.1 the value equals the request-handling time; a future minor
MAY introduce caching, in which case the timestamp reflects when the
recommendation was last computed.

The daemon SHALL compute the recommendation server-side using the
fixed rule order documented in
`contracts/dashboard-next-actions.md`. Clients MUST NOT recompute the
recommendation from the other dashboard fields.

`recommended_next_action` MAY be `null` only when a future minor
explicitly opts out of recommending (none such case at v1.1). At
v1.1 the daemon MUST always emit a non-null recommendation (at
minimum `code: "all_clear"`).

Clients MUST treat an unknown `code` value as forward compatibility:
the client SHALL silently render no tile (or fall back to its
`all_clear` rendering) when it encounters a code it does not
recognize. Daemons MUST NOT remove a `code` value from the closed
set without a major bump per FR-035.

Daemons advertising `app_contract_version >= "1.1"` MUST emit both
fields.

#### Scenario: Empty daemon recommends starting a bench container

- **GIVEN** a v1.1 daemon with readiness `state == "ready"`, zero
  containers, zero panes, zero agents, zero routes, zero queue rows
- **WHEN** an authenticated app session calls `app.dashboard`
- **THEN** `recommended_next_action.code == "no_containers"`
- **AND** `recommended_next_action.title` is non-empty and ≤ 80 chars
- **AND** `recommended_next_action_refreshed_at` is a valid ISO-8601
  UTC timestamp string

#### Scenario: Degraded subsystem outranks every other recommendation

- **GIVEN** a v1.1 daemon with readiness `state == "degraded"` AND
  zero containers (which alone would emit `no_containers`)
- **WHEN** an authenticated app session calls `app.dashboard`
- **THEN** `recommended_next_action.code == "subsystem_degraded"`
- **AND** `recommended_next_action.target.kind == "subsystem"`
- **AND** `recommended_next_action.target.id` equals the name of the
  first degraded subsystem in the readiness response

#### Scenario: Adopted, routed, healthy daemon recommends all_clear

- **GIVEN** a v1.1 daemon with readiness `state == "ready"`, at least
  one active container, at least one registered agent, at least one
  enabled route, no blocked queue rows, no unadopted panes
- **WHEN** an authenticated app session calls `app.dashboard`
- **THEN** `recommended_next_action.code == "all_clear"`
- **AND** `recommended_next_action.target` is absent

#### Scenario: Unknown code in a hypothetical v1.2 response is ignored by a v1.1 client

- **GIVEN** a v1.1 client and a hypothetical v1.2 daemon response
  carrying `recommended_next_action.code == "some_future_code"`
- **WHEN** the client parses the response
- **THEN** the client renders no tile (or its `all_clear` fallback)
- **AND** the client does NOT raise an error or refuse other fields

### Requirement: app_contract_version bumps from 1.0 to 1.1

The daemon SHALL advertise `app_contract_version == "1.1"` and
`supported_minor_range == {"min": "1.0", "max": "1.1"}` in every
`app.hello` response once the new fields are wired. The new version
string MUST also appear on the FR-033 envelope for every `app.*`
response.

The bump is an **additive** minor under FR-035: no v1.0 field is
removed or renamed, no v1.0 error code is removed, no v1.0 method is
removed. Clients built against `app_contract_version == "1.0"` MUST
keep functioning byte-for-byte against the v1.1 daemon. Clients
built against `app_contract_version == "1.1"` MAY rely on the new
fields documented in this spec.

The dispatcher smoke-test guard (FR-035 / SC-029) MUST exercise
`app.dashboard` at v1.1 and assert that the new fields
(`counts.panes.by_state`, `counts.agents.by_state`,
`counts.routes.recently_skipped_count`,
`counts.routes.recently_skipped_window_ms`,
`recommended_next_action`, `recommended_next_action_refreshed_at`)
are all present in a single response.

The bump MUST NOT change `capability_flags`. Per FR-039, new optional
**methods** require flags; new optional **fields** on existing
required methods are advertised by the contract version itself.

#### Scenario: Daemon advertises v1.1 to a fresh app.hello

- **GIVEN** a daemon built with this change applied
- **WHEN** an unauthenticated process calls `app.hello`
- **THEN** the success result includes
  `app_contract_version == "1.1"`
- **AND** `supported_minor_range == {"min": "1.0", "max": "1.1"}`
- **AND** `capability_flags == {}` (unchanged from v1.0)

#### Scenario: v1.0 client major matches and proceeds normally

- **GIVEN** a v1.1 daemon and a client supplying
  `client_app_contract_major == 1`
- **WHEN** the client calls `app.hello` and then every other `app.*`
  read method exercised by FEAT-011's v1.0 contract tests
- **THEN** every call succeeds with the v1.1 envelope
  (`app_contract_version: "1.1"`)
- **AND** every v1.0 response field is present with v1.0 types
- **AND** the client functions without modification

#### Scenario: Newer-major client is still refused

- **GIVEN** a v1.1 daemon and a client supplying
  `client_app_contract_major == 2`
- **WHEN** the client calls `app.hello`
- **THEN** the daemon returns `app_contract_major_unsupported` with
  `details = {daemon_app_contract_version: "1.1",
  client_app_contract_major: 2}`
- **AND** the client MUST NOT call any other `app.*` method

### Requirement: dashboard-next-actions.md documents the closed set and rule order

The change SHALL introduce a new contract file
`specs/011-app-backend-contract/contracts/dashboard-next-actions.md`
documenting:

- The exact closed set of `recommended_next_action.code` values at
  v1.1 (the seven codes enumerated above).
- The fixed evaluation order the daemon uses (`subsystem_degraded`,
  `no_containers`, `no_panes_discovered`, `unadopted_panes_present`,
  `blocked_queue_drain`, `no_routes_configured`, `all_clear`).
- The per-code `target.kind` rules (which codes carry a target and
  what kind of entity its `id` points at).
- The forward-compatibility rule: clients MUST ignore unknown codes;
  removing or renaming a code requires a major bump (FR-035).

#### Scenario: Contract file enumerates all v1.1 codes

- **WHEN** a reviewer reads
  `specs/011-app-backend-contract/contracts/dashboard-next-actions.md`
- **THEN** the file lists every v1.1 `code` value with its title
  template, target rule, and the runtime condition the daemon uses
  to emit it
- **AND** the rule order is documented as a numbered list with the
  exact priority used by the daemon

### Requirement: closed-sets.md registers PaneState, AgentState, and next-action codes

The change SHALL extend
`specs/011-app-backend-contract/contracts/closed-sets.md` with three
new closed sets:

- `PaneState` — the four-value set used by `counts.panes.by_state`.
- `AgentState` — the five-value set used by `counts.agents.by_state`,
  including the normative note that `log-attached`/`log-detached`
  overlap with `active`/`inactive` and the sum may exceed
  `counts.agents.total`.
- `RecommendedNextActionCode` — the seven-value set used by
  `recommended_next_action.code`.

Each new closed-set entry MUST include the FR-035 evolution rule:
adding a new value is an additive minor bump; renaming or removing a
value requires a major bump.

#### Scenario: closed-sets.md gains three new sets

- **WHEN** a reviewer reads
  `specs/011-app-backend-contract/contracts/closed-sets.md`
- **THEN** sections for `PaneState`, `AgentState`, and
  `RecommendedNextActionCode` are present with their full v1.1 value
  lists and the additive-evolution note
