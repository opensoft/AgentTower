# Feature Specification: Bench Container Discovery

**Feature Branch**: `003-bench-container-discovery`
**Created**: 2026-05-05
**Status**: Draft
**Input**: User description: "FEAT-003: discover in-scope Docker bench containers from the host daemon and expose them through CLI commands."

## Clarifications

### Session 2026-05-05

- Q: How should the daemon behave when a second container scan request arrives while one is already in flight? → A: Serialize via in-process mutex; second request blocks until the first completes, then runs.
- Q: What per-call timeout should bound each Docker subprocess invocation? → A: 5 seconds per `docker ps` and per `docker inspect` call; exceeding it produces a degraded scan result, not a daemon crash.
- Q: How should Container Scan Results be persisted? → A: Each scan is stored as a row in a new SQLite `container_scans` table; degraded scans also append a JSONL event to the FEAT-001 events file.
- Q: When `docker inspect` fails for a matching container, what happens to its container record? → A: If a prior record exists, preserve last-known inspect metadata, leave the `active` flag unchanged from the previous scan, and update only `last_scanned_at`. If no prior record exists, do not create a container row; record the failure only in the degraded scan result and the JSONL event.
- Q: What should `agenttower list-containers` show by default? → A: All matching containers (active + inactive history) with active rows first, then inactive rows; offer an `--active-only` flag for callers that want only currently active containers.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Scan Running Bench Containers (Priority: P1)

A developer starts AgentTower, runs a container scan, and sees only running bench containers recorded by the host daemon.

**Why this priority**: Container discovery is the first control-plane capability after daemon startup. Later pane discovery depends on knowing which containers are active and in scope.

**Independent Test**: Can be fully tested with a fake Docker command/adapter that returns a mix of running bench and non-bench containers, then invoking `agenttower scan --containers` and inspecting persisted records through `agenttower list-containers`.

**Acceptance Scenarios**:

1. **Given** the daemon is running and Docker reports running containers named `py-bench` and `redis`, **When** the user runs `agenttower scan --containers`, **Then** AgentTower persists only the container whose name matches the configured bench-name rule.
2. **Given** a matching running bench container was persisted, **When** the user runs `agenttower list-containers`, **Then** the container appears with id, name, image, status, labels, mounts, active state, and last scanned timestamp.
3. **Given** a previously discovered bench container no longer appears in the latest running-container scan, **When** the scan completes, **Then** AgentTower marks that container inactive instead of deleting its history.

---

### User Story 2 - Configure Bench Name Matching (Priority: P2)

A developer can define which running containers are in scope by editing the AgentTower config, while the default configuration recognizes containers whose names contain `bench`.

**Why this priority**: Opensoft bench containers are the MVP target, but local naming can vary. The feature must avoid scanning unrelated containers by default and still allow project-specific names.

**Independent Test**: Can be tested by writing a temporary config with `name_contains = ["bench", "dev"]`, running the scan against fake Docker output, and verifying only containers matching one of those case-insensitive substrings are persisted as active.

**Acceptance Scenarios**:

1. **Given** no explicit container matching config, **When** Docker reports `py-bench` and `api-dev`, **Then** only `py-bench` is in scope.
2. **Given** the config includes `name_contains = ["bench", "dev"]`, **When** Docker reports `py-bench`, `api-dev`, and `postgres`, **Then** `py-bench` and `api-dev` are in scope and `postgres` is ignored.
3. **Given** the config has an empty or malformed `name_contains` value, **When** the scan runs, **Then** AgentTower reports an actionable config error and does not silently widen scope to all containers.

---

### User Story 3 - Handle Docker Degraded States (Priority: P3)

A developer receives clear scan output when Docker is unavailable, denied, slow, or returns malformed data, and the daemon keeps running.

**Why this priority**: Docker access varies across developer machines and WSL sessions. AgentTower must remain usable even when discovery cannot complete.

**Independent Test**: Can be tested with fake adapters that raise command-not-found, permission denied, timeout, non-zero exit, and malformed-inspect errors, then verifying CLI output, exit codes, daemon health, and persisted scan status.

**Acceptance Scenarios**:

1. **Given** Docker is not installed or not on `PATH`, **When** the user runs `agenttower scan --containers`, **Then** the command exits with a non-success status and prints a message that Docker could not be executed.
2. **Given** Docker returns permission denied, **When** the scan runs, **Then** AgentTower reports the permission problem and does not crash the daemon.
3. **Given** `docker ps` succeeds but `docker inspect` fails for one candidate, **When** the scan completes, **Then** AgentTower records a degraded scan result while preserving any successfully inspected matching containers; if the failed candidate already has a prior record, its last-known inspect metadata and `active` flag are preserved and only `last_scanned_at` is updated; if it has no prior record, no container row is created and the failure is captured only in the degraded scan result and JSONL event.

### Edge Cases

- Docker reports no running containers.
- Docker reports running containers, but none match the bench-name rule.
- A container name matches by case-insensitive substring.
- Docker output includes multiple names or leading slash prefixes from inspect data.
- `docker inspect` returns valid JSON with missing optional fields such as labels or mounts.
- A container id is reused after an old record exists.
- A scan starts while another container scan is already running (second request waits on a daemon-side mutex and runs after the first completes).
- The daemon is unavailable when a CLI scan or list command is invoked.
- Existing FEAT-002 status/ping/shutdown methods must continue to work after adding discovery methods.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide a Docker adapter that executes host-side Docker discovery commands through a testable abstraction.
- **FR-002**: The adapter MUST discover running containers using Docker CLI output equivalent to `docker ps`.
- **FR-003**: The adapter MUST inspect each candidate container and normalize inspect data into structured container metadata.
- **FR-004**: The default bench-name matching rule MUST be a case-insensitive substring match for `bench`.
- **FR-005**: The system MUST read optional container matching config from the Opensoft config file using `containers.name_contains`.
- **FR-006**: The system MUST reject empty, non-list, or non-string `containers.name_contains` values with actionable errors rather than scanning all containers.
- **FR-007**: The system MUST scan only running containers in FEAT-003.
- **FR-008**: The system MUST ignore non-matching containers by default and MUST NOT persist them as active scan results.
- **FR-009**: The system MUST persist matching container records in SQLite.
- **FR-010**: Persisted container records MUST include container id, name, image, status, labels, mounts, active/inactive state, first seen timestamp, and last scanned timestamp.
- **FR-011**: Persisted container records SHOULD include normalized inspect metadata useful to FEAT-004, including configured user when available, working directory when available, environment keys needed for identity, and mount source/target pairs.
- **FR-012**: The system MUST mark previously active matching containers inactive when they are absent from a successful later running-container scan.
- **FR-013**: The system MUST preserve historical container records instead of deleting records during scan reconciliation.
- **FR-014**: The daemon socket API MUST expose a method for scanning containers and a method for listing persisted containers.
- **FR-015**: `agenttower scan --containers` MUST call the daemon over the existing Unix socket API and print a concise scan summary.
- **FR-016**: `agenttower list-containers` MUST call the daemon and print persisted container records in a stable, scriptable format. By default the command MUST return all matching containers (active and inactive) with active rows ordered before inactive rows. The command MUST accept an `--active-only` flag that restricts the result to currently active containers only.
- **FR-017**: `agenttower scan --containers --json` and `agenttower list-containers --json` MUST emit one JSON object per command invocation.
- **FR-018**: Docker command-not-found, permission denied, timeout, non-zero exit, invalid JSON, and malformed inspect payloads MUST produce degraded scan results without crashing the daemon.
- **FR-019**: Degraded scan results MUST be visible in CLI output, persisted as a row in the `container_scans` SQLite table, and appended as a JSONL event to the FEAT-001 events file with enough detail (error code, error message, affected container ids where applicable) for troubleshooting.
- **FR-020**: The feature MUST be testable without a real Docker daemon by injecting fake Docker command results or adapter implementations.
- **FR-021**: FEAT-003 MUST NOT add a network listener, in-container daemon, tmux discovery, pane discovery, agent registration, log attachment, or input delivery.
- **FR-022**: Existing FEAT-001 and FEAT-002 CLI behavior and daemon socket methods MUST remain backward compatible.
- **FR-023**: The daemon MUST serialize concurrent container scan requests using an in-process mutex so that at most one container scan runs at a time; subsequent scan callers MUST block until the in-flight scan completes and then run, each receiving its own complete scan result.
- **FR-024**: Each Docker subprocess invocation (`docker ps` and each `docker inspect`) MUST be bounded by a 5-second timeout; a timeout MUST be normalized into a degraded scan result with a timeout error code rather than crashing the daemon or surfacing as an uncaught exception.
- **FR-025**: Each container scan MUST be persisted as a row in a new SQLite `container_scans` table capturing scan id, started_at, completed_at, scan status (ok or degraded), matched container count, inactive-reconciled count, ignored container count, and degraded error details when applicable. The scan id MUST be returned in the socket response and CLI output so callers can correlate logs and history.
- **FR-026**: When `docker inspect` fails for a matching container that has a prior record, AgentTower MUST preserve the prior inspect metadata, leave the `active` flag unchanged from the previous scan, and update only `last_scanned_at`. When the failing candidate has no prior record, AgentTower MUST NOT create a container row; the failure is recorded only in the degraded scan result and JSONL event.

### Key Entities *(include if feature involves data)*

- **Bench Container**: A Docker container considered in scope for AgentTower MVP discovery. Key attributes include id, name, image, status, labels, mounts, active state, first seen timestamp, last scanned timestamp, and normalized inspect metadata.
- **Container Scan Result**: The outcome of one container scan request, persisted as one row in the SQLite `container_scans` table. Includes scan id, started_at, completed_at, scan status (ok or degraded), count of discovered matching containers, count of inactive records after reconciliation, ignored container count, and any degraded error details. Degraded results additionally produce one JSONL event in the FEAT-001 events file.
- **Container Matching Rule**: Config-derived rule that decides whether a running container belongs to AgentTower's MVP bench scope. In FEAT-003 this is limited to case-insensitive `name_contains` substrings.
- **Docker Adapter Error**: A normalized failure result for command-not-found, permission denied, timeout (per-call 5 s budget), non-zero Docker exit, invalid JSON, or malformed inspect payloads.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With a fake Docker adapter returning 10 running containers, including 3 bench-name matches, `agenttower scan --containers` persists exactly 3 active container records.
- **SC-002**: After a successful scan where one previously active bench container disappears from Docker output, `agenttower list-containers` shows that record as inactive within the same scan invocation.
- **SC-003**: `agenttower list-containers --json` returns valid JSON containing id, name, image, status, labels, mounts, active, and last_scanned_at for each persisted record.
- **SC-004**: Docker unavailable, permission denied, timeout, and malformed inspect scenarios return non-zero or degraded CLI output within 3 seconds when using fake adapters, while `agenttower status` still succeeds afterward.
- **SC-005**: Existing FEAT-001 and FEAT-002 test suites continue to pass after FEAT-003 is implemented.
- **SC-006**: The feature has unit coverage for matching rules, Docker adapter parsing/error normalization, persistence reconciliation, and socket method response shapes.
- **SC-007**: The feature has integration coverage for `scan --containers`, `list-containers`, JSON output, no-match scans, inactive reconciliation, and degraded Docker states without requiring a real Docker daemon.

## Assumptions

- Docker CLI access is the MVP integration point; no Docker SDK runtime dependency is added for FEAT-003.
- The host daemon performs container discovery from the host environment.
- Bench containers are identified by container name in FEAT-003; label-based matching can be added later if needed.
- Only running containers are scanned as active control targets in FEAT-003.
- SQLite remains the durable source of truth for discovered container records.
- Container scans are request-driven by CLI in this feature; recurring background scans can be introduced later.
- The existing Unix socket API can be extended with additional closed-set methods for container scan/list behavior.
- Container records are keyed by container id. When a container id is reused after a prior record exists, the existing row is updated in place: `first_seen_at` is preserved, mutable fields (name, image, status, labels, mounts, active flag, last_scanned_at) are overwritten with the latest scan's values. Distinguishing reused-id incarnations is out of scope for FEAT-003.
- Scan ids are UUID4 strings generated by the daemon at scan start.
- Redaction of label values, mount sources, and other potentially sensitive inspect fields is out of scope for FEAT-003 and is deferred to the redaction utility introduced in FEAT-007.

