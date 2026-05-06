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
- A configured `name_contains` substring contains shell metacharacters such as `;`, `|`, or `$(`.
- A malicious container name contains newlines, tabs, ANSI escape bytes, or argv-injection-shaped text.
- Docker output includes multiple names or leading slash prefixes from inspect data.
- `docker inspect` returns valid JSON with missing optional fields such as labels or mounts.
- `docker inspect` returns oversized strings, unusual label values, or unexpected JSON shapes.
- A container id is reused after an old record exists.
- A scan starts while another container scan is already running (second request waits on a daemon-side mutex and runs after the first completes).
- More than two scan callers arrive while a scan is already in flight.
- The daemon restarts while a scan is in flight.
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
- **FR-015**: `agenttower scan --containers` MUST call the daemon over the existing Unix socket API and print a concise scan summary as defined in `contracts/cli.md` C-CLI-201.
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
- **FR-027**: FEAT-003 MUST spawn only the enumerated Docker subprocesses `docker ps --no-trunc --format '{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}'` and `docker inspect <container-id>...` (one or more ids in a single batch invocation); all other Docker subcommands are out of scope. Every invocation MUST use typed argv with `shell=False` or the direct equivalent, and container names, ids, and config-derived strings MUST NOT be interpolated into shell strings. Shell metacharacters in config values or container metadata MUST be treated as ordinary data.
- **FR-028**: The daemon MUST resolve the Docker binary with `shutil.which("docker")` against the daemon process environment `PATH` at scan time. The daemon `PATH` is inherited from the process that launched `agenttowerd`; FEAT-003 does not pin or scrub it. A missing or non-executable resolved binary MUST produce `docker_unavailable`. A malicious or shadowed `docker` earlier on a trusted host user's `PATH` is out of scope for FEAT-003.
- **FR-029**: When a Docker subprocess exceeds the 5-second timeout, AgentTower MUST terminate and wait for that subprocess before returning a `docker_timeout` degraded result so no child process is intentionally leaked.
- **FR-030**: The config loader MUST read `[containers] name_contains` for each scan, strip each configured substring before matching, and reject empty lists, non-lists, non-string elements, blank-after-strip elements, more than 32 entries, or entries longer than 128 characters with `config_invalid`. Invalid config MUST NOT widen scope to all containers.
- **FR-031**: FEAT-003 MUST run Docker discovery as the existing daemon user only; it MUST NOT use `sudo`, change uid/gid, start containers, stop containers, or exec into containers. The new socket methods inherit FEAT-002 socket-file authorization (`0600`, host user only) and add no roles or secondary auth checks.
- **FR-032**: Persisted inspect metadata MUST be a normalized allowlist only: id, name, image, status, labels, mounts, config user, working directory, allowlisted environment keys (`USER`, `HOME`, `WORKDIR`, `TMUX`), and full status. Raw `HostConfig`, raw non-allowlisted environment variables, and raw inspect output MUST NOT be stored. Error messages and per-container error details persisted to SQLite or JSONL MUST be bounded to 2048 characters per message and sanitized of NUL bytes and terminal control bytes; FEAT-003 does not attempt semantic secret redaction beyond this bound.
- **FR-033**: Degraded scan JSONL events and lifecycle log rows MUST contain only scan id, status, counts, closed error code, bounded/sanitized error message, and affected container ids where applicable; they MUST NOT include raw inspect output, raw environment values, or full Docker stderr beyond the bounded error message.
- **FR-034**: `list_containers` MUST be read-only, MUST NOT call Docker or acquire the scan mutex, and MUST expose persisted labels and mount sources only through the inherited host-user socket boundary. Redaction of label values and mount sources is deferred to FEAT-007.
- **FR-035**: If more than one scan caller waits on the scan mutex, callers MUST run one at a time after the current scan completes, but FEAT-003 does not guarantee FIFO fairness beyond the operating system's lock scheduling. The scan mutex is in-process only and is recreated on daemon restart; in-flight scans are aborted if the daemon process exits.
- **FR-036**: Existing FEAT-002 request framing remains request-size-limited only; FEAT-003 adds no separate response-size cap. FEAT-003 response payloads MUST remain bounded by omitting raw inspect/env data and by the config limits above; unexpected socket write failures are handled by FEAT-002's existing `internal_error` and daemon-liveness guarantees.
- **FR-037**: A scan status is `ok` only when config validation succeeds, `docker ps` succeeds, every parseable running-container row is classified, and every matching candidate inspects successfully. A scan status is `degraded` when config validation fails, Docker is unavailable/denied/timed out/non-zero, Docker output is malformed, or at least one matching candidate fails inspect.
- **FR-038**: Every `scan_containers` request that acquires the scan mutex MUST allocate a new UUID4 scan id and persist exactly one `container_scans` row, including whole-scan failures that return an `ok:false` socket envelope. The `ok:false` envelope omits a `result` object, but the persisted row, lifecycle log, and degraded JSONL event remain the audit trail.
- **FR-039**: Active-to-inactive reconciliation MUST run only after a successful `docker ps` parse. If `docker ps` fails or config validation fails, AgentTower MUST NOT modify any `containers` rows. If `docker ps` succeeds but one or more matching inspect calls fail, the scan is still authoritative for containers absent from the successful `docker ps` result: previously active rows absent from the matched candidate set are marked inactive.
- **FR-040**: When a previously inactive container reappears in `docker ps` and inspect succeeds, AgentTower MUST preserve `first_seen_at`, update mutable metadata, update `last_scanned_at`, and set `active=1`. When a previously inactive container reappears but inspect fails, FR-026 applies and the row remains inactive with only `last_scanned_at` updated.
- **FR-041**: Scan counters are per-scan, not cumulative. `matched_count` is the number of running `docker ps` rows whose normalized names matched the current rule, including matching candidates whose inspect failed. `ignored_count` is the number of parseable running `docker ps` rows that did not match the rule. For successful `docker ps` output, `matched_count + ignored_count` MUST equal the number of parseable `docker ps` rows. `inactive_reconciled_count` is the number of rows transitioned from active to inactive by this scan only.
- **FR-042**: The `container_scans` insert and all `containers` upsert/touch/inactivate writes for one scan MUST commit in one SQLite transaction. If that transaction fails, AgentTower MUST roll it back, MUST NOT append the degraded JSONL event for that failed transaction, MUST release the scan mutex, and MUST return `internal_error` while keeping the daemon alive.
- **FR-043**: Scan side effects MUST occur in this order: emit `scan_started` after acquiring the mutex and before Docker/config execution; execute config/Docker/reconciliation; commit the SQLite scan transaction; append a degraded JSONL event only if the committed scan is degraded; emit `scan_completed`; return the socket response. If JSONL or lifecycle logging fails after the SQLite commit, AgentTower MUST return `internal_error` but MUST NOT roll back the already committed SQLite row.
- **FR-044**: Per-container error details MUST use the same shape in SQLite, JSONL, socket, and CLI JSON: `{container_id, error_code, error_message}`. Per-container errors are recorded only for matching candidates, and each matching candidate MUST contribute at most one detail entry. For partial inspect failures, the top-level `error_code` MUST equal the first per-container error code in Docker ps order.
- **FR-045**: Two scan requests against unchanged Docker state MUST produce distinct scan ids and distinct `container_scans` rows while converging `containers` rows to the same final content. A degraded scan MUST append at most one JSONL event for its scan id.
- **FR-046**: Healthy scans MUST NOT append to `events.jsonl`, but every scan that commits a `container_scans` row MUST emit `scan_started` and `scan_completed` lifecycle log lines carrying the same scan id. An empty healthy scan still persists a `container_scans` row with zero counters.
- **FR-047**: The v1-to-v2 SQLite migration MUST run in one transaction, be idempotent on re-open, create the new tables even for an otherwise empty v1 database, and bump `schema_version` only after the tables exist. If migration fails, AgentTower MUST roll back and refuse to serve the daemon rather than serving partial schema. Future schema versions greater than the build supports MUST cause daemon startup refusal.
- **FR-048**: `list_containers` MUST return the latest committed SQLite state only; it MUST NOT expose in-flight scan writes. Results MUST be deterministic between calls with no intervening committed scan using order `active DESC, last_scanned_at DESC, container_id ASC`.
- **FR-049**: The current scan's matching rule is loaded once per scan and applied consistently to slash-stripped `docker ps` names for matching and reconciliation. If `name_contains` changes between scans, rows that were previously active but do not match the current rule during a later successful scan are marked inactive because they are no longer in the current in-scope set.
- **FR-050**: `config_invalid` MUST short-circuit before any Docker subprocess is spawned.

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
- FEAT-003 threat model: the host user, daemon process environment, resolved Docker binary, and Docker daemon are trusted; container names, labels, mounts, inspect JSON, and command stderr are untrusted data. PATH hardening beyond documenting the inherited daemon `PATH` is deferred to a later security-hardening feature.
- FEAT-003 preserves backward compatibility by migrating v1 SQLite state forward to schema v2. Downgrading a v2 state database for use by a FEAT-002-only daemon is out of scope.
