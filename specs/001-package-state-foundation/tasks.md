# Tasks: Package, Config, and State Foundation

**Input**: Design documents from `/specs/001-package-state-foundation/`
**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/ ✓ (cli.md, event-writer.md), quickstart.md ✓

**Tests**: REQUIRED. Spec FR-017 explicitly mandates automated tests for path resolution (default + XDG), `config init` idempotence, schema-version row presence/value, end-to-end `--version` / `config paths` / `config init`, and event-writer append behavior.

**Organization**: Tasks are grouped by user story so each story can be implemented and validated independently. User stories are numbered per `spec.md`: US1 and US2 are both P1, US3 is P2, US4 is P3.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Maps the task to the user story it serves (US1, US2, US3, US4)
- Every task names the exact file path it touches

## Path Conventions

Single-project Python layout (per `plan.md` §Project Structure):

- Source: `src/agenttower/`
- Tests: `tests/unit/`, `tests/integration/`
- Package metadata: `pyproject.toml` at repo root

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Land the package metadata and version-source plumbing that every later phase depends on.

- [X] T001 Create `pyproject.toml` at repo root with the hatchling build backend, `requires-python = ">=3.11"`, project name `agenttower`, static `version = "0.1.0"`, console scripts `agenttower = "agenttower.cli:main"` and `agenttowerd = "agenttower.daemon:main"`, `[project.optional-dependencies] test = ["pytest>=7"]`, and a `[tool.hatch.build.targets.wheel] packages = ["src/agenttower"]` block per `research.md` R-002 / `plan.md` Technical Context
- [X] T002 Update `src/agenttower/__init__.py` to source `__version__` via `importlib.metadata.version("agenttower")` with `PackageNotFoundError` fallback to `"0.0.0+local"` per `research.md` R-009 / FR-003
- [X] T003 Update `tests/unit/test_imports.py` so `test_agenttower_imports` asserts `__version__` is a non-empty `str` (no longer hard-coded `"0.0.0"`), and add an assertion that the value matches `importlib.metadata.version("agenttower")` when the package is installed
- [X] T004 Install the package in editable mode with test extras from the repo root (`python -m pip install -e '.[test]'`) so the `agenttower` and `agenttowerd` console scripts and `pytest` are available for every later test task — re-run any time `pyproject.toml` changes

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Implement the single piece of infrastructure shared by US2, US3, and US4 — the `Paths` resolver. US1 does not depend on it, but every other story does.

**⚠️ CRITICAL**: US2, US3, and US4 cannot start until this phase is complete.

- [X] T005 Implement `src/agenttower/paths.py` exposing a frozen `@dataclass(frozen=True)` `Paths` with the six members `config_file`, `state_db`, `events_file`, `logs_dir`, `socket`, `cache_dir` (all `pathlib.Path`) and a `resolve_paths(env: Mapping[str, str] | None = None) -> Paths` function that reads `XDG_CONFIG_HOME` / `XDG_STATE_HOME` / `XDG_CACHE_HOME` (treating empty string as unset per the XDG base-directory spec), falls back to `$HOME/.config`, `$HOME/.local/state`, `$HOME/.cache`, joins the `opensoft/agenttower` sub-namespace under each base, and pins the daemon socket at `<state_base>/opensoft/agenttower/agenttowerd.sock` without consulting `XDG_RUNTIME_DIR` per `research.md` R-003 / R-004 and `data-model.md` §1 (FR-006, FR-007)
- [X] T006 [P] Write `tests/unit/test_paths.py` covering: defaults when no XDG variables are set (assert each of the six members equals the canonical `~/.config/...`, `~/.local/state/...`, `~/.cache/...` location under a `tmp_path` `HOME`); each XDG variable in isolation correctly redirects only its own subset of paths while the `opensoft/agenttower` sub-namespace is preserved; all three XDG variables set together redirect their respective subsets simultaneously; empty-string XDG variables are treated as unset; socket falls back to the state dir even when `XDG_RUNTIME_DIR` is set; the returned `Paths` instance is frozen (assigning to a member raises) — uses `monkeypatch.setenv` / `monkeypatch.delenv` and `tmp_path` only (FR-007, FR-017, SC-008)

**Checkpoint**: `Paths` resolver is locked. US2, US3, US4 may now begin in parallel. US1 may have started earlier in parallel with this phase.

---

## Phase 3: User Story 1 — First-time installation produces a usable CLI (Priority: P1, part of P1 MVP)

**Goal**: A developer can `pip install -e .`, run `agenttower --version` / `agenttowerd --version` / `agenttower --help` on a clean host, and see correct output without any prior initialization or daemon.

**Independent Test**: From a clean dev install with no AgentTower directories on disk, `agenttower --version` prints `agenttower 0.1.0` (or the installed version) and exits `0`; `agenttowerd --version` prints the matching `agenttowerd <VERSION>` and exits `0`; `agenttower --help` lists `--version`, `config`, `paths`, and `init` substrings. No file is created under the resolved path set.

### Implementation for User Story 1

- [X] T007 [US1] Replace `src/agenttower/cli.py` with an `argparse`-based user CLI: a top-level parser named `agenttower` with `--version` (using `action="version"` and `version=f"agenttower {__version__}"`), a `config` subparser, and two sub-subparsers `paths` and `init` registered with placeholder handlers (e.g. `lambda args: parser.error("not yet implemented")` — to be replaced in T015 and T012 respectively); `main(argv: list[str] | None = None) -> int` parses args, dispatches the selected handler, returns its int exit code, and prints the usage text + returns `0` when invoked with no arguments per `research.md` R-008 and `contracts/cli.md` C-CLI-001 / C-CLI-002 (FR-002, FR-003)
- [X] T008 [P] [US1] Replace `src/agenttower/daemon.py` with an `argparse`-based parser for `agenttowerd` exposing only `--version` (using `action="version"` and `version=f"agenttowerd {__version__}"`), `main(argv: list[str] | None = None) -> int` returning `0`, with no socket binding, no Docker / tmux call, and no daemon lifecycle work per `contracts/cli.md` C-CLI-005 (FR-002, FR-003, FR-016)
- [X] T009 [P] [US1] Write `tests/integration/test_cli_version.py` that uses the installed console scripts via `subprocess.run(["agenttower", ...], env=...)` and `subprocess.run(["agenttowerd", ...], env=...)` under an isolated `tmp_path` `HOME` with all `XDG_*` unset to assert: `agenttower --version` exits `0` with stdout `agenttower <VERSION>\n`; `agenttowerd --version` exits `0` with the same `<VERSION>` substring; both complete in under five seconds; `agenttower --help` exits `0` and stdout contains the literal substrings `usage: agenttower`, `--version`, `config`, `paths`, and `init`, including visible entries for `config paths` and `config init`; running `agenttower --version` does not create any file under the resolved path set (FR-002, FR-003, FR-016, SC-001, C-CLI-001 / C-CLI-002 / C-CLI-005)

**Checkpoint**: User Story 1 ships an installable, version-reporting CLI. The `config paths` and `config init` subcommands are registered but not yet implemented.

---

## Phase 4: User Story 2 — Initialize the durable host state layout (Priority: P1)

**Goal**: A developer runs `agenttower config init` once on a clean host and gets the full Opensoft directory layout, the default config file, and a SQLite registry containing one `schema_version` row with `version=1`, all with strict host-only permissions and idempotent re-runs.

**Independent Test**: From a clean host with all AgentTower directories absent, a single `agenttower config init` produces every Resolved Path Set member that this story owns (config file, state DB file, logs dir, cache dir; not events file, not socket); a follow-up `sqlite3 STATE_DB 'SELECT version FROM schema_version'` returns `1` and `SELECT COUNT(*)` returns `1`; ten consecutive re-runs leave bytes and rows unchanged; running against an unwritable target exits non-zero with an actionable stderr message and leaves no partial sqlite file behind.

### Implementation for User Story 2

- [X] T010 [US2] Implement `src/agenttower/config.py` with `_render_default_config() -> str` that returns the exact TOML content from `research.md` R-005 (header comments + `[containers]` section with `name_contains = ["bench"]` and `scan_interval_seconds = 5`) and `write_default_config(config_file: Path) -> str` that ensures the parent directory chain exists with final mode `0o700` on every directory this call creates (including intermediate `opensoft/` parents, chmod after creation to defeat `umask`), refuses with `OSError` if a required pre-existing parent directory is broader than `0o700` or a pre-existing config file is broader than `0o600`, writes the rendered content with `os.open(..., O_WRONLY | O_CREAT | O_EXCL, 0o600)` only when the file is absent, fchmods the newly-created file to `0o600`, and returns either `"created"` or `"already initialized"` per `data-model.md` §2 and `contracts/cli.md` C-CLI-004 (FR-005, FR-008, FR-010, FR-015)
- [X] T011 [P] [US2] Implement `src/agenttower/state/schema.py` with module-level constant `CURRENT_SCHEMA_VERSION = 1` and `open_registry(state_db: Path) -> tuple[sqlite3.Connection, str]` that ensures the parent directory exists with final mode `0o700`, records whether the file pre-existed, refuses with `OSError` if a required pre-existing parent directory is broader than `0o700` or a pre-existing `state_db` is broader than `0o600`, opens via `sqlite3.connect(state_db, isolation_level=None)`, sets `PRAGMA journal_mode = WAL` and `PRAGMA foreign_keys = ON`, executes `CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)`, inserts `CURRENT_SCHEMA_VERSION` only when the table is empty (`SELECT COUNT(*)` then conditional INSERT), chmods the main DB and any SQLite companion files created by this call to `0o600`, and returns the connection plus a `"created"` / `"already initialized"` status string per `research.md` R-006 / `data-model.md` §3 (FR-005, FR-009, FR-010, FR-015)
- [X] T012 [US2] Replace the `config init` placeholder in `src/agenttower/cli.py` with a real handler that resolves paths via `resolve_paths()`, creates `LOGS_DIR`, `CACHE_DIR`, the state directory, and the configuration directory with final mode `0o700` when absent (including intermediate `opensoft/` parents, never chmod'ing pre-existing dirs), validates required pre-existing AgentTower-owned dirs/files (defined as paths under the resolved `opensoft/agenttower` namespace) are no broader than their required modes before using them, calls `write_default_config(paths.config_file)` and `open_registry(paths.state_db)`, prints `created config: <path>` / `already initialized: <path>` and `created registry: <path>` / `already initialized: <path>` lines on stdout (config first, then registry), returns `0` on success; on `OSError` writes `error: <verb>: <absolute path>: <strerror>\n` to stderr, removes any sqlite file or SQLite companion file created by the same failing call (so failure leaves no partial DB artifacts), and returns `1` per `contracts/cli.md` C-CLI-004 (FR-005, FR-010, FR-011, FR-014, FR-015, FR-016)
- [X] T013 [P] [US2] Write `tests/unit/test_state_schema.py` covering: a fresh `state_db` path under `tmp_path` produces a file with mode `0o600` after `open_registry`, a `schema_version` table with a single row whose `version` equals `CURRENT_SCHEMA_VERSION` (== 1); ten sequential re-opens leave row count at exactly 1 and the version unchanged; the function never raises on a pre-initialized DB; pragma `journal_mode` returns `wal` after open (FR-009, FR-010, SC-004)
- [X] T014 [P] [US2] Write `tests/integration/test_cli_init.py` that exercises the installed `agenttower` console script via `subprocess.run(["agenttower", ...], env=...)` under an isolated `tmp_path` `HOME` and asserts: first `config init` exits `0`, prints `created config: <CONFIG_FILE>` and `created registry: <STATE_DB>`; ten consecutive re-runs all exit `0`, print `already initialized: ...` lines, and leave `sha256(CONFIG_FILE)` and `SELECT version, COUNT(*) FROM schema_version` byte-identical; mixed cases where only `CONFIG_FILE` or only `STATE_DB` pre-exists print independent `created ...` / `already initialized ...` statuses for config and registry; `CONFIG_FILE`, `STATE_DB`, and any created SQLite companion files have mode `0o600`; `LOGS_DIR`, `CACHE_DIR`, the configuration directory, the state directory, and intermediate `opensoft/` parents created by init have mode `0o700`; modes still land at `0o600` / `0o700` under a permissive process `umask`; `EVENTS_FILE` and `SOCKET` are NOT created by init (FR-016 / Q4); pre-existing stale `EVENTS_FILE`, log file, and socket placeholder bytes are left byte-identical after init; a pre-existing user-edited `CONFIG_FILE` with mode `0o600` is left byte-identical after re-running init; a pre-existing required artifact with mode broader than required causes exit `1`, path-specific `error: ...` stderr, and byte-identical preservation; running against an unwritable target (e.g. `chmod -w` on a parent under `tmp_path`) exits `1`, writes `error: ...: <path>: ...` to stderr, and leaves no `agenttower.sqlite3`, `agenttower.sqlite3-wal`, `agenttower.sqlite3-shm`, or journal file created by that failing call behind (FR-005, FR-010, FR-011, FR-014, FR-015, FR-016, SC-002, SC-003, SC-006, SC-009)

**Checkpoint**: User Story 2 stands independently — a fresh host can be initialized, re-initialization is safe, and failure modes are observable.

---

## Phase 5: User Story 3 — Inspect resolved Opensoft paths for diagnosis (Priority: P2)

**Goal**: A developer or shell helper runs `agenttower config paths` to discover every path AgentTower will use, in a stable `KEY=value` form they can `eval` into their environment.

**Independent Test**: After a fresh install, `agenttower config paths` prints exactly six lines in the fixed order `CONFIG_FILE`, `STATE_DB`, `EVENTS_FILE`, `LOGS_DIR`, `SOCKET`, `CACHE_DIR`, each value an absolute path under `opensoft/agenttower`; `eval "$(agenttower config paths)"` populates the six environment variables in any POSIX shell; before init, stderr carries the informational `note: agenttower has not been initialized; ...` line; after init, stderr is empty; setting any of `XDG_CONFIG_HOME` / `XDG_STATE_HOME` / `XDG_CACHE_HOME` shifts the corresponding paths under the override while preserving the `opensoft/agenttower` namespace.

### Implementation for User Story 3

- [X] T015 [US3] Replace the `config paths` placeholder in `src/agenttower/cli.py` with a real handler that calls `resolve_paths()` and prints the six members to stdout in the fixed order `CONFIG_FILE=<path>`, `STATE_DB=<path>`, `EVENTS_FILE=<path>`, `LOGS_DIR=<path>`, `SOCKET=<path>`, `CACHE_DIR=<path>` (one `=` per line, no quoting, no surrounding whitespace, trailing newline per line), checks whether `paths.state_db` exists and — if not — writes the exact line `note: agenttower has not been initialized; run \`agenttower config init\`` to stderr, and returns `0` in both initialized and uninitialized states per `contracts/cli.md` C-CLI-003 (FR-004, FR-014, FR-016)
- [X] T016 [P] [US3] Write `tests/integration/test_cli_paths.py` that runs `agenttower config paths` via `subprocess.run(["agenttower", "config", "paths"], env=...)` under an isolated `tmp_path` `HOME` and asserts: exactly six lines on stdout in the fixed order with the canonical keys; each value is an absolute path under `opensoft/agenttower`; `eval`-equivalent parsing (split on first `=`) recovers the six expected env vars; before init the stderr `note: ...` line is present; after running `config init` via `subprocess.run(["agenttower", "config", "init"], env=...)` the stderr is empty while stdout is unchanged; setting `XDG_CONFIG_HOME=$tmp_path/cfg` shifts only `CONFIG_FILE` under that base; setting `XDG_STATE_HOME=$tmp_path/state` shifts `STATE_DB`, `EVENTS_FILE`, `LOGS_DIR`, and `SOCKET` under that base; setting `XDG_CACHE_HOME=$tmp_path/cache` shifts only `CACHE_DIR`; setting all three XDG variables together shifts every path to the expected respective base; running this command does not create any file under the resolved path set (FR-004, FR-007, FR-016, SC-005, SC-008)

**Checkpoint**: All three user-visible CLI surfaces (--version, config init, config paths) are implemented and independently testable.

---

## Phase 6: User Story 4 — Append durable audit history to the event file (Priority: P3)

**Goal**: Internal callers (FEAT-002+) can call a single shared utility to append timestamped JSONL records to `EVENTS_FILE` with predictable concurrency and permission semantics. FEAT-001 itself never invokes the writer outside tests.

**Independent Test**: A unit test that imports `agenttower.events.writer.append_event` and calls it against a `tmp_path` events file produces exactly one well-formed JSON line per call (with writer-injected `ts` plus payload keys), creates the file at mode `0o600` and the parent directory chain at mode `0o700`, and 100 threads each appending one record produce a file with exactly 100 distinct, well-formed JSON lines.

### Implementation for User Story 4

- [X] T017 [US4] Implement `src/agenttower/events/writer.py` exposing `append_event(events_file: Path, payload: Mapping[str, Any]) -> None` that: ensures the parent directory chain exists with final mode `0o700` on dirs created by this call; refuses with `OSError` if a required pre-existing parent directory is broader than `0o700` or a pre-existing `events_file` is broader than `0o600`; builds `record = {"ts": datetime.datetime.now(datetime.UTC).isoformat(timespec="microseconds"), **payload}` so caller-supplied `ts` overrides the writer; serializes via `json.dumps(record, separators=(",", ":"), ensure_ascii=False, allow_nan=False)`; acquires a module-level `threading.Lock` for the duration of the I/O; opens with `os.open(events_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)`, fchmods newly-created files to `0o600`, writes the JSON string + `"\n"` in a single `os.write(fd, ...)` call; calls `os.fsync(fd)`; closes the descriptor; lets `OSError`, `TypeError`, `ValueError` propagate per `research.md` R-007 and `contracts/event-writer.md` C-EVT-001 / C-EVT-002 / C-EVT-003 (FR-012, FR-013, FR-015)
- [X] T018 [P] [US4] Write `tests/unit/test_events_writer.py` covering all C-EVT-004 invariants: one `append_event` call appends exactly one line whose `json.loads` produces a dict containing the writer-injected `ts` plus all payload keys; the `ts` value matches the regex `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00$`; a payload containing `{"ts": "carrier-supplied"}` produces a line whose `ts` equals `"carrier-supplied"`; a fresh `events_file` is created with mode `0o600`, including under a permissive process `umask`; a missing parent directory chain is created with mode `0o700` on each newly created leaf; 100 threads each calling `append_event` once with distinct payloads produce a file with exactly 100 lines whose union of decoded payloads equals the union of submitted payloads (no loss, no duplication, no interleaving); a pre-existing line is preserved when subsequent appends occur (append-only); a pre-existing file with mode broader than `0o600` raises `OSError` before appending and preserves bytes; an `OSError` from a read-only parent propagates unchanged (FR-012, FR-013, FR-015, SC-007)

**Checkpoint**: All four user stories independently functional. Event-writer ships ready for FEAT-002+ to call.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T019 Walk through `specs/001-package-state-foundation/quickstart.md` end-to-end on a clean dev shell (sections 1 through 12) and confirm every documented stdout, stderr, file mode, and `sqlite3` query result matches reality; note any drift in the section's output blocks
- [X] T020 [P] After `pytest -q` passes, manually verify the FR-016 / Q4 cross-cutting invariant from a fresh `HOME=$(mktemp -d)` shell by running `agenttower --version`, `agenttowerd --version`, `agenttower config paths`, and `agenttower config init`, then asserting `[ ! -e "$EVENTS_FILE" ]` (no FEAT-001 command writes to the events file), `[ ! -S "$SOCKET" ]` (no daemon socket opened), and that no AgentTower process owns a listening TCP/UDP socket according to `ss -ltnup` / `ss -lunp`; if `ss` is unavailable, install/provide iproute2 or fail this polish verification rather than silently skipping the listener check

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup, T001–T004)**: No dependencies. T001 must complete before T004; T002 must complete before T003 reads the new version source; T004 unblocks every later test task.
- **Phase 2 (Foundational, T005–T006)**: Depends on Phase 1. Blocks US2, US3, US4 (US1 does NOT depend on this phase).
- **Phase 3 (US1)**: Depends on Phase 1 only. May run in parallel with Phase 2.
- **Phase 4 (US2)**: Depends on Phase 2 (`paths.py`) and Phase 3 (T007 establishes the `config init` subparser slot in `cli.py`).
- **Phase 5 (US3)**: Depends on Phase 2 (`paths.py`) and Phase 3 (T007 establishes the `config paths` subparser slot in `cli.py`).
- **Phase 6 (US4)**: Depends on Phase 2 (`Paths.events_file`). Independent of US1, US2, US3 implementations.
- **Phase 7 (Polish)**: Depends on every prior phase.

### User Story Dependencies

- **US1 (P1)**: Independent. Setup is its only prereq.
- **US2 (P1)**: Needs Foundational + US1's `cli.py` parser skeleton. Independent of US3 and US4.
- **US3 (P2)**: Needs Foundational + US1's `cli.py` parser skeleton. Independent of US2 and US4.
- **US4 (P3)**: Needs only Foundational. Independent of US1, US2, US3 (can be developed in parallel by a second contributor once Phase 2 lands).

### Within Each User Story

- Models / helpers (`config.py`, `state/schema.py`, `events/writer.py`) before CLI handler wiring.
- Unit tests for a module may be authored in parallel with the module itself (TDD-style) as long as both land before the next dependent task runs.
- US2's `cli.py` change (T012) and US3's `cli.py` change (T015) both edit the same file, so they MUST be sequenced (do US2 first since it is P1, then US3).

---

## Parallel Execution Examples

### After Phase 1 lands

Run T005 (foundational paths) and T007–T009 (US1) in parallel — they touch disjoint files (`paths.py` + `test_paths.py` vs `cli.py` / `daemon.py` / `test_cli_version.py`):

```bash
# Worker A (foundational):
Task: "T005 — Implement src/agenttower/paths.py"
Task: "T006 [P] — Write tests/unit/test_paths.py"

# Worker B (US1):
Task: "T007 [US1] — Replace src/agenttower/cli.py"
Task: "T008 [P] [US1] — Replace src/agenttower/daemon.py"
Task: "T009 [P] [US1] — Write tests/integration/test_cli_version.py"
```

### Within US2

T010, T011, and T013 touch independent files and can run in parallel; T012 depends on T010 + T011; T014 depends on T012:

```bash
# Phase 1 (parallel):
Task: "T010 [US2] — Implement src/agenttower/config.py"
Task: "T011 [P] [US2] — Implement src/agenttower/state/schema.py"
Task: "T013 [P] [US2] — Write tests/unit/test_state_schema.py"

# Phase 2 (after T010 + T011):
Task: "T012 [US2] — Wire config init handler in src/agenttower/cli.py"

# Phase 3 (after T012):
Task: "T014 [P] [US2] — Write tests/integration/test_cli_init.py"
```

### After US2 lands, US3 and US4 in parallel

```bash
# US3 (single contributor — only one task touches cli.py):
Task: "T015 [US3] — Wire config paths handler in src/agenttower/cli.py"
Task: "T016 [P] [US3] — Write tests/integration/test_cli_paths.py"

# US4 (independent contributor — disjoint files):
Task: "T017 [US4] — Implement src/agenttower/events/writer.py"
Task: "T018 [P] [US4] — Write tests/unit/test_events_writer.py"
```

---

## Implementation Strategy

### MVP First (US1 + US2 — both P1)

1. Complete Phase 1 (T001–T004): package metadata, version source, editable install.
2. Complete Phase 2 (T005–T006): `Paths` resolver locked.
3. Complete Phase 3 (T007–T009): installable CLI reports its version. **Validate independently** — run `pytest tests/integration/test_cli_version.py -q` and the quickstart §2.
4. Complete Phase 4 (T010–T014): `config init` produces the layout. **Validate independently** — run `pytest tests/integration/test_cli_init.py -q` and the quickstart §4–§8.
5. Stop here for the P1 MVP demo if needed.

### Incremental Delivery

1. Setup + Foundational → foundation ready.
2. + US1 → installable CLI with `--version` (testable, demoable).
3. + US2 → host initialization (testable, demoable, MVP).
4. + US3 → path inspection (`eval`-friendly).
5. + US4 → audit-history writer ready for FEAT-002+.
6. Polish: quickstart walkthrough, FR-016 cross-cutting check.

### Parallel Team Strategy

With two contributors after Phase 1:

- Contributor A: Phase 2 (foundational paths) → US2 (config init).
- Contributor B: Phase 3 (US1 CLI skeleton) → after Phase 2 lands, US4 (event-writer).
- Either contributor takes US3 once US2's `cli.py` edit lands (US3 also touches `cli.py`, so it must follow US2).

---

## Validation Summary

### Independent Test Criteria per Story

| Story | Independent test |
|---|---|
| US1 | `agenttower --version` and `agenttowerd --version` both exit `0` with matching version strings on a clean host; `agenttower --help` lists `config`, `paths`, `init`, and `--version` (no files created). |
| US2 | One `agenttower config init` on a clean host yields `CONFIG_FILE` (mode `0600`), `STATE_DB` (mode `0600`, `SELECT version FROM schema_version` returns `1`, `COUNT(*)` returns `1`), `LOGS_DIR` (mode `0700`), `CACHE_DIR` (mode `0700`); ten re-runs leave bytes / rows / modes unchanged; unwritable target exits `1` with no partial DB. |
| US3 | `agenttower config paths` prints six fixed-order `KEY=value` lines under `opensoft/agenttower`; `eval "$(agenttower config paths)"` populates the six env vars; XDG overrides are respected; uninitialized stderr carries the `note: ...` line. |
| US4 | `append_event` appends one well-formed JSON line per call with `ts` injected, file mode `0600`, parent dir mode `0700`; 100 concurrent appenders produce 100 distinct lines. |

### Parallel Opportunities

- T005 / T006 ↔ T007 / T008 / T009 (Foundational ↔ US1) — disjoint files.
- T010 / T011 / T013 within US2 — three disjoint files.
- US3 ↔ US4 once US2 lands — disjoint files except `cli.py` (US3 owns the next `cli.py` edit; US4 does not touch it).

### Suggested MVP Scope

US1 + US2 — both are P1 in the spec. US1 alone proves the install works; US2 makes the host usable for FEAT-002+. Ship US1 + US2 as the P1 MVP, then layer US3 and US4 in any order.

### Format Validation

Every task above starts with `- [ ]`, has a sequential `T0NN` ID, names the exact file path it touches, and carries a `[Story]` label exactly when it lives in a user-story phase (US1, US2, US3, US4). Setup, Foundational, and Polish tasks deliberately carry no `[Story]` label, per the format rules.

---

## Notes

- All durable artifacts created by FEAT-001 use POSIX modes `0700` for directories and `0600` for files (FR-015). Tests assert these on every artifact (SC-009).
- FR-016 / clarification Q4: no FEAT-001 CLI command may write to `EVENTS_FILE`. Both `test_cli_init.py` and the polish task T020 assert this.
- No third-party runtime dependencies. `pytest>=7` is the only test-time dependency.
- No daemon lifecycle, socket bind, Docker / tmux call, or input delivery anywhere in this feature.
- Schema migrations are explicitly out of scope; FEAT-001 only seeds `schema_version.version = 1` and never updates it.
