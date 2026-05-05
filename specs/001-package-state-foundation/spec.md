# Feature Specification: Package, Config, and State Foundation

**Feature Branch**: `001-package-state-foundation`
**Created**: 2026-05-05
**Status**: Draft
**Input**: User description: "FEAT-001: Package, Config, and State Foundation — create the Python package skeleton and durable local state layout for AgentTower (host-daemon/container-first per the AgentTower constitution)."

## Clarifications

### Session 2026-05-05

- Q: What file-permission posture should `config init` apply to every artifact it creates (config file/dir, registry database file, state dir holding the future socket and logs, cache dir, logs dir)? → A: Strict host-only — directories `0700`, files `0600` for every created artifact.
- Q: What canonical output shape should `agenttower config paths` use? → A: `KEY=value` per line (one path per line, uppercase keys), single canonical output for both humans and scripts; no `--format` flag for MVP.
- Q: How should the registry database represent its schema version? → A: A monotonically increasing integer starting at `1`, stored as a single row in a `schema_version(version INTEGER NOT NULL)` table; decoupled from the package release version.
- Q: Should `config init` itself emit JSONL audit records to `events.jsonl`? → A: No. The event-writer utility ships ready for callers in FEAT-002+, but FEAT-001 commands write no event records; init outcomes are observable only via stdout and exit code.
- Q: What should happen when a pre-existing AgentTower-owned artifact that FEAT-001 must use has permissions broader than the required host-only mode? → A: Refuse with exit code `1` and an actionable path-specific error, leaving the artifact byte-identical; do not silently accept the weaker mode and do not chmod user-created artifacts.
- Q: Who owns schema-version increments after the initial `1`? → A: The AgentTower codebase owns `CURRENT_SCHEMA_VERSION`; FEAT-001 seeds value `1`, later schema-migration features increment it when they introduce a durable schema change, and package release versions remain independent.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - First-time installation produces a usable AgentTower CLI (Priority: P1)

A developer installs AgentTower on their Linux/WSL workstation for the first
time and needs a fast, unambiguous way to confirm the installation works before
attempting any further setup. They run the primary CLI to print its version and
expect it to succeed without first creating any files or running a daemon.

**Why this priority**: Every later feature (FEAT-002 through FEAT-010) depends
on the package being importable and the CLI being callable. Without this slice
the product cannot be installed, demonstrated, or reviewed at all.

**Independent Test**: From a clean dev install of the repo, running the user
CLI with the `--version` flag prints a non-empty version string and exits with
status `0`, with no requirement that any host directory or state file already
exist.

**Acceptance Scenarios**:

1. **Given** a fresh repo checkout with the package installed in development
   mode and no AgentTower directories on disk, **When** the user runs the
   primary CLI with `--version`, **Then** the CLI prints the package version
   and exits with status `0`.
2. **Given** the package is installed, **When** the user invokes the daemon
   entrypoint with `--version`, **Then** it prints the same package version
   and exits with status `0`.
3. **Given** the package is installed, **When** the user runs the primary CLI
   with `--help`, **Then** it lists at least the `config paths` and
   `config init` subcommands and the `--version` flag.

---

### User Story 2 - Initialize the durable host state layout (Priority: P1)

A developer who has just installed AgentTower needs to create the durable
on-disk state layout under the Opensoft namespace before any daemon, registry,
or event work can proceed. They run a single initialization command and expect
the configuration directory, state directory, log directory, and cache
directory to be created, a default configuration file to be written, and the
local registry database to be opened with a recorded schema version.

**Why this priority**: This is the foundation every other MVP feature builds
on. Container discovery, agent registration, log attachment, and event
ingestion all require the state directories, the registry database, and a
schema-versioned starting point. Without this slice no later feature can be
implemented or tested end-to-end.

**Independent Test**: From a clean host with no AgentTower directories,
running the initialization command once produces every documented Opensoft
path on disk, writes a default configuration file, opens the registry
database, and records the current schema version — verifiable by listing the
filesystem and reading the schema version from the database, without requiring
any other AgentTower feature.

**Acceptance Scenarios**:

1. **Given** a host where none of the AgentTower Opensoft directories exist,
   **When** the user runs `agenttower config init`, **Then** the command
   creates the configuration directory, state directory, logs directory, and
   cache directory under the Opensoft namespace, writes a default
   configuration file at the configuration path, creates the registry
   database file at the state path, and records the current schema version in
   the database.
2. **Given** initialization has completed successfully, **When** the user
   inspects the registry database, **Then** a `schema_version` table exists
   with a single non-null integer `version` column, contains exactly one
   row, and that row's value matches the integer the package declares as
   the current schema generation.
3. **Given** initialization has completed successfully, **When** the user
   runs `agenttower config init` again, **Then** the command exits with
   status `0`, leaves the existing configuration file unchanged, leaves the
   existing schema version unchanged, and does not duplicate or corrupt any
   state directory or file.
4. **Given** a host with a write-protected target directory (for example, the
   parent of the state path is not writable), **When** the user runs
   `agenttower config init`, **Then** the command exits with a non-zero
   status, prints an actionable error identifying the unwritable path, and
   does not leave a partially initialized database file behind.

---

### User Story 3 - Inspect resolved Opensoft paths for diagnosis (Priority: P2)

A developer or shell helper needs to know exactly which configuration, state,
log, socket, and cache paths AgentTower will use on this host so they can
inspect the database, tail an event file, mount the daemon socket into a
bench container, or wire shell helpers (`yodex`, `yolo`, `cta`) without
hard-coding paths.

**Why this priority**: Path inspection is critical for diagnosis, scripting,
and the container-side socket mount that FEAT-005 depends on. It is not on the
critical path for installation, so it sits below initialization. It is still
foundational because every later CLI subcommand and the daemon itself rely on
the same path resolution.

**Independent Test**: After initialization, running `agenttower config paths`
prints the configuration file path, registry database path, event history
path, logs directory, daemon socket path, and cache directory in a stable,
machine-parseable form, and each printed path lives under the Opensoft
namespace as defined by the constitution.

**Acceptance Scenarios**:

1. **Given** AgentTower has been initialized on the host, **When** the user
   runs `agenttower config paths`, **Then** the command prints exactly six
   lines in `KEY=value` form using the fixed, ordered keys `CONFIG_FILE`,
   `STATE_DB`, `EVENTS_FILE`, `LOGS_DIR`, `SOCKET`, and `CACHE_DIR`, with
   each value pointing at its resolved path.
2. **Given** AgentTower has not yet been initialized, **When** the user runs
   `agenttower config paths`, **Then** the command still prints the resolved
   paths it would use without creating any files, and indicates that
   initialization has not yet been performed.
3. **Given** the user has set the standard XDG base-directory environment
   variables (`XDG_CONFIG_HOME`, `XDG_STATE_HOME`, `XDG_CACHE_HOME`),
   **When** the user runs `agenttower config paths`, **Then** the printed
   configuration, state, and cache paths reflect those overrides while
   remaining under the `opensoft/agenttower` namespace.

---

### User Story 4 - Append durable audit history to the event file (Priority: P3)

Internal AgentTower components (host daemon, CLI subcommands) need a single,
shared way to append timestamped JSON-line records to the durable event
history file. Later features (notably FEAT-008 event ingestion and FEAT-009
prompt delivery) require this writer to exist with stable, predictable
behavior so audit history is uniform and inspectable.

**Why this priority**: The writer is foundational infrastructure but is not
directly user-visible in this feature. Lower priority than installation and
initialization because no end-user CLI workflow in FEAT-001 produces events
yet; the writer ships ready for FEAT-002+ to call.

**Independent Test**: Calling the event-writer utility from a controlled test
appends one JSON-encoded line per call to the resolved event history file,
each line includes a timestamp and the supplied payload fields, the file
ends with a newline after each append, and concurrent appends from multiple
callers do not interleave bytes within a single record.

**Acceptance Scenarios**:

1. **Given** the host has been initialized, **When** an internal caller asks
   the event writer to record a payload, **Then** the writer appends exactly
   one line to the event history file containing a timestamp and the supplied
   payload fields, terminated by a newline.
2. **Given** two callers append events nearly simultaneously, **When** the
   file is read, **Then** each appended record appears on its own line and no
   record is interleaved or truncated by the other.
3. **Given** the event history file does not yet exist when the writer is
   first called, **When** the writer appends a record, **Then** the file is
   created at the resolved event history path and the record is written
   without error.

---

### Edge Cases

- The user runs `config init` while a previous run was interrupted and only
  some directories exist: subsequent runs MUST complete the layout without
  overwriting anything that already exists.
- A pre-existing configuration file with user edits is present when the user
  runs `config init`: the user's file MUST be preserved unchanged if it has
  required host-only permissions; if it has broader permissions, init MUST
  refuse with an actionable error and leave the file byte-identical.
- A pre-existing registry database is present and already contains a schema
  version row: re-running initialization MUST leave the recorded version
  untouched and MUST NOT add a second version row. (Schema migration is
  explicitly out of scope for this feature.)
- The XDG base-directory environment variables are set to paths that do not
  yet exist: the resolver MUST still produce well-defined paths under the
  Opensoft namespace, and `config init` MUST create those parent directories.
- `XDG_RUNTIME_DIR` is unset or unwritable on a system where it would
  normally hold the daemon socket: path resolution MUST fall back
  deterministically to the documented state-directory location for the
  socket so the daemon and clients agree on a single path.
- The user's home directory is not writable, or any required parent directory
  is not writable: `config init` MUST exit non-zero with an actionable error
  identifying the unwritable path and MUST NOT leave behind partial files.
- A stale socket file or log file from a prior install exists in the state
  directory when `config init` runs: initialization MUST NOT delete or
  truncate them and MUST NOT fail because of them.
- The package is invoked from a development checkout where version metadata
  is sourced from package distribution metadata: `--version` MUST still
  succeed and report a meaningful version string.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The product MUST be distributable as a Python package whose
  importable name is `agenttower`, installable from the existing `src/`
  layout via a standard editable/development install.
- **FR-002**: The product MUST expose two console-script entrypoints:
  `agenttower` (user-facing CLI) and `agenttowerd` (daemon entrypoint).
  Both entrypoints MUST be invokable after a development install of the
  package without further setup.
- **FR-003**: The CLI MUST accept a `--version` flag that prints the package
  version and exits with status `0`. The same flag MUST be available on the
  `agenttowerd` entrypoint and MUST report the same version.
- **FR-004**: The CLI MUST provide a `config paths` subcommand that prints
  exactly one resolved path per line in `KEY=value` form, with no
  surrounding whitespace and no quoting. The keys MUST be the stable,
  uppercase identifiers `CONFIG_FILE`, `STATE_DB`, `EVENTS_FILE`,
  `LOGS_DIR`, `SOCKET`, and `CACHE_DIR`, in that order. Each line MUST
  contain exactly one `=` separator. The same canonical output is used for
  both human and script consumers; MVP MUST NOT introduce a `--format`
  flag or any alternative output shape.
- **FR-005**: The CLI MUST provide a `config init` subcommand that creates
  every directory required for the durable layout, writes a default
  configuration file when none exists, creates the registry database file,
  and records the package's current schema version in the database.
- **FR-006**: Path resolution MUST place all durable artifacts under the
  Opensoft namespace using the canonical defaults documented in the
  constitution: `~/.config/opensoft/agenttower/config.toml`,
  `~/.local/state/opensoft/agenttower/agenttower.sqlite3`,
  `~/.local/state/opensoft/agenttower/events.jsonl`,
  `~/.local/state/opensoft/agenttower/logs/`,
  `~/.local/state/opensoft/agenttower/agenttowerd.sock`, and
  `~/.cache/opensoft/agenttower/`.
- **FR-007**: Path resolution MUST honor the standard XDG base-directory
  environment variables (`XDG_CONFIG_HOME`, `XDG_STATE_HOME`,
  `XDG_CACHE_HOME`) when set, by joining the `opensoft/agenttower`
  sub-namespace under the override, while preserving the canonical defaults
  when those variables are unset.
- **FR-008**: The default configuration file written by `config init` MUST
  include the MVP container-discovery defaults defined in the architecture
  document: a `[containers]` section with `name_contains = ["bench"]` and a
  `scan_interval_seconds` field set to a documented MVP default.
- **FR-009**: The registry database created by `config init` MUST contain
  a table named `schema_version` with a single non-null integer column
  named `version`. Initialization MUST insert exactly one row whose value
  is the current schema generation, expressed as a monotonically
  increasing integer starting at `1`. The codebase MUST expose this value
  as `CURRENT_SCHEMA_VERSION`; FEAT-001 sets it to `1`, and FEAT-002+
  schema-migration features increment it only when they introduce a
  durable schema change. The schema generation is intentionally decoupled
  from the package release version. The database MUST open cleanly on
  subsequent `config init` runs and subsequent registry opens, and MUST
  never contain more than one row in `schema_version`.
- **FR-010**: `config init` MUST be idempotent: running it any number of
  times in succession on a host that has already been initialized MUST exit
  with status `0`, MUST NOT modify the existing configuration file, MUST NOT
  change the recorded schema version, and MUST NOT create duplicate
  artifacts.
- **FR-011**: `config init` MUST NOT delete, truncate, or otherwise mutate
  any pre-existing log file, socket file, event history file, or other state
  artifact present in the resolved paths.
- **FR-012**: The product MUST provide a shared internal event-writer
  utility that appends a single JSON-encoded record per call to the resolved
  event history file, includes a timestamp on every record, terminates each
  record with a newline, and creates the file if it does not yet exist.
- **FR-013**: Concurrent calls into the event-writer utility from multiple
  in-process callers MUST produce one whole record per call with no record
  interleaved within another.
- **FR-014**: When a CLI subcommand fails (for example, `config init`
  encounters an unwritable directory), the CLI MUST exit with a non-zero
  status and print exactly one actionable stderr line in the
  `error: <action verb>: <absolute path>: <reason>` shape defined by
  `contracts/cli.md` C-CLI-004; failures MUST NOT be silently swallowed.
- **FR-015**: All durable artifacts created by `config init` MUST be created
  with strict host-only permissions: every directory it creates (the
  intermediate `opensoft/` parents, configuration directory, state
  directory, logs directory, and cache directory) MUST have mode `0700`
  (read/write/execute for the owning user only), and every file it creates
  (the default configuration file, the registry database file, any SQLite
  companion files it creates such as `-wal` / `-shm`, and any file the
  event-writer utility creates) MUST have mode `0600` (read/write for the
  owning user only). The implementation MUST set or verify these modes
  after creation so process `umask` cannot make newly-created artifacts
  broader than specified. For FEAT-001, "AgentTower-owned" means any path
  under the resolved `opensoft/agenttower` namespace; UID, ACL, and label
  ownership are out of scope because the MVP assumes one host user. If a
  required pre-existing AgentTower-owned file or directory that FEAT-001
  must read, write, or append to has a broader mode than required, the
  command or writer MUST refuse with exit code `1` or a propagated
  `OSError`, name the offending path, and leave the artifact
  byte-identical. Pre-existing artifacts that FEAT-001 does not touch,
  such as stale socket files and prior log files, MAY retain their
  existing permissions.
- **FR-016**: The product MUST NOT open any network listener, start any
  daemon, scan Docker, scan tmux, register agents, ingest logs, classify
  events, route messages, or send terminal input as part of `--version`,
  `config paths`, or `config init`. Those behaviors are owned by later
  features. In particular, no FEAT-001 CLI command MUST write any record
  to the event history file; the event-writer utility introduced by this
  feature is exercised only by tests until FEAT-002+ adopts it.
- **FR-017**: Automated tests MUST cover, at minimum: path resolution under
  default and XDG-overridden environments, idempotent re-runs of
  `config init`, presence and value of the schema-version row after
  initialization, end-to-end invocation of the `--version`, `config paths`,
  and `config init` commands, and append behavior of the event-writer
  utility.

### Key Entities *(include if feature involves data)*

- **Resolved Path Set**: The set of canonical filesystem locations
  AgentTower will use on a given host. Members are: configuration file,
  registry database, event history file, logs directory, daemon socket
  file, and cache directory. Each member is derived from environment and
  defaults; the set is the source of truth shared by the CLI, the daemon,
  and tests.
- **Default Configuration File**: A human-editable configuration document
  written at the resolved configuration path on first initialization.
  Carries the MVP container-discovery defaults so later features inherit a
  consistent starting point.
- **Registry Database**: The durable local store for AgentTower state. In
  this feature it carries only a schema-version record; later features
  (FEAT-002 onward) extend the schema. The database is the host's source
  of truth.
- **Schema Version Record**: A single non-null integer stored as the only
  row of the `schema_version(version INTEGER NOT NULL)` table inside the
  registry database. The integer increases monotonically across schema
  generations (starting at `1`) and is decoupled from the package release
  version. Future features use it to gate or trigger migrations; this
  feature only creates and reads it.
- **Event History File**: The durable, append-only audit history written
  one JSON-encoded record per line. In this feature only the writer
  utility and the file's resolved location are introduced; later features
  populate it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: From a clean development install of the repo, a developer can
  run the `--version` command on the user CLI and on the daemon entrypoint
  and receive matching, non-empty version output in under five seconds each,
  with no prior initialization required.
- **SC-002**: After a single successful run of `agenttower config init` on a
  host that previously had no AgentTower directories, every init-owned path
  needed by the six-member Resolved Path Set exists on disk: configuration
  file, registry database file, event history parent directory, logs
  directory, daemon socket parent directory, and cache directory. The
  `EVENTS_FILE` and `SOCKET` path values themselves MUST remain absent.
- **SC-003**: Running `agenttower config init` ten times consecutively on the
  same host produces no errors and leaves the configuration file content,
  the registry database file size and schema-version row, and the directory
  layout byte-identical to the state after the first run.
- **SC-004**: After initialization, a single-row `SELECT version FROM
  schema_version` returns the integer value the package declares as the
  current schema generation (with `1` for the initial release), and a
  `SELECT COUNT(*) FROM schema_version` returns exactly `1`; both can be
  asserted by tests without invoking any other AgentTower feature.
- **SC-005**: Output from `agenttower config paths` is exactly six lines,
  one per Resolved Path Set member, each in `KEY=value` form using the
  fixed keys `CONFIG_FILE`, `STATE_DB`, `EVENTS_FILE`, `LOGS_DIR`,
  `SOCKET`, and `CACHE_DIR` in that order. A shell helper can load every
  variable into its environment with a single pass (e.g.
  `eval "$(agenttower config paths)"`), and every value lives under the
  Opensoft namespace.
- **SC-006**: When `config init` is run against an unwritable target, the
  command exits non-zero, prints an error message identifying the offending
  path, and leaves no partial files behind for the current failing call,
  including `agenttower.sqlite3` and SQLite companion files such as
  `agenttower.sqlite3-wal`, `agenttower.sqlite3-shm`, and rollback journal
  files; this behavior is reproducible from a test fixture without manual
  intervention.
- **SC-007**: The internal event-writer utility, exercised from a test that
  appends one hundred records from concurrent callers, produces a file with
  exactly one hundred well-formed JSON lines and no truncated or interleaved
  bytes within any record.
- **SC-008**: Path resolution under XDG overrides yields the same final
  `opensoft/agenttower` sub-namespace under the overridden parent, verified
  by tests that set each XDG variable in isolation and by one test that
  sets `XDG_CONFIG_HOME`, `XDG_STATE_HOME`, and `XDG_CACHE_HOME` together.
- **SC-009**: After a successful `config init` on a clean host, the
  intermediate `opensoft/` parents, configuration directory, state
  directory, logs directory, and cache directory created by the command
  each have mode `0700`, and the default configuration file, the registry
  database file, any SQLite companion file created by init, and any event
  history file the writer has produced each have mode `0600`; this is
  verified by a filesystem permission test on each created artifact.

## Assumptions

- The MVP target is Linux/WSL workstations, consistent with the PRD and
  constitution. Path resolution is defined for POSIX-style filesystems; no
  Windows-native path handling is required for this feature.
- The single host user owns and runs both the CLI and the daemon. Multi-user
  installations and shared system-wide installs are out of scope.
- Path resolution honors the standard XDG base-directory environment
  variables. When an XDG variable is set, the resolver joins the
  `opensoft/agenttower` sub-namespace under that override; when it is unset,
  the canonical default from the constitution applies.
- The default value for `containers.scan_interval_seconds` in the generated
  configuration file follows the architecture document's example
  (`5` seconds) unless implementation-time discovery surfaces a reason to
  change it; the value is captured in configuration so later features can
  override it without code change.
- The schema-version record is stored as a single row in a single
  schema-version table. Migration tooling, multi-version history, and
  upgrade flows are explicitly deferred to later features.
- Strict host-only permissions are defined by POSIX mode bits only. ACLs,
  security labels, extended attributes, and hard-link attack hardening are
  out of scope for FEAT-001 and may be handled by later audit-hardening
  work.
- FEAT-001 implementations enforce required file modes by setting or
  verifying modes after creating files/directories rather than changing the
  process-wide `umask`.
- The event-writer utility uses ordinary append-mode file writes with
  whatever locking is available on the host filesystem; cross-host or
  network-filesystem semantics are out of scope for MVP.
- All filesystem artifacts are created with single-user permissions
  (read/write for the owning user, no world or group write); this aligns
  with the constitution's "no network listener" and "host user only"
  posture.
- The package's current version is sourced from standard Python package
  metadata so that `--version` works identically from a development install
  and from a future built distribution.
- This feature does not start, supervise, or communicate with `agenttowerd`
  beyond verifying its `--version` entrypoint exists. Daemon lifecycle is
  the responsibility of FEAT-002.
- This feature does not invoke Docker, tmux, the Unix socket listener, the
  log attacher, the event classifier, the routing layer, or the input
  delivery layer. Those are owned by FEAT-002 through FEAT-010.
