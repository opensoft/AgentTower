# Phase 0 Research: Package, Config, and State Foundation

**Branch**: `001-package-state-foundation` | **Date**: 2026-05-05

The four `/speckit.clarify` questions resolved the only spec-level
`NEEDS CLARIFICATION` candidates (file modes, `config paths` shape,
schema-version representation, init-time JSONL emission). This document
captures the remaining technical decisions FEAT-001 must lock so that
`/speckit.tasks` and `/speckit.implement` have nothing implementation-
defining left to invent.

For each topic: **Decision** is what the implementation will do.
**Rationale** explains why it satisfies the spec, the constitution, and
the foreseeable needs of FEAT-002+. **Alternatives considered** lists
options that were evaluated and rejected (with why).

---

## R-001 — Minimum Python version

- **Decision**: `requires-python = ">=3.11"`.
- **Rationale**: Python 3.11 brings `tomllib` into the standard library,
  which removes any third-party dependency for future config reads (this
  feature only writes TOML, but FEAT-002+ will read it). 3.11 is the
  default CPython on bench/devcontainer base images that the project
  already targets, and on Ubuntu 22.04+/Debian 12+/recent WSL distros. It
  also lets us use `datetime.UTC`, `Self` typing, and `ExceptionGroup` in
  later features without backward-compat work.
- **Alternatives considered**:
  - **3.10**: would force pulling `tomli` as a runtime dependency once
    FEAT-002 reads config. Constitution prefers stdlib-only at this layer.
  - **3.12**: too aggressive — some bench images still ship 3.11; no
    feature in MVP-001 needs 3.12-only syntax.
  - **3.9**: misses `match` statements that FEAT-008 classifier rules
    will use; misses `Annotated` improvements.

## R-002 — Build backend and packaging metadata

- **Decision**: `pyproject.toml` with the **hatchling** build backend.
  Source layout `src/agenttower/`. Version sourced via Hatch's `vcs`
  plugin **deferred** — for FEAT-001 we use a **static** `version =
  "0.1.0"` string in `[project]` and re-read it via
  `importlib.metadata.version("agenttower")` at runtime so the source of
  truth is single. Console scripts:
  ```toml
  [project.scripts]
  agenttower = "agenttower.cli:main"
  agenttowerd = "agenttower.daemon:main"
  ```
  Test extras:
  ```toml
  [project.optional-dependencies]
  test = ["pytest>=7"]
  ```
- **Rationale**: Hatchling is the lightest-weight modern PEP 517 backend
  with first-class `src/`-layout support, no setup.py, and no plugin
  baggage. Static version keeps FEAT-001 trivial; we can switch to a vcs
  plugin in a later feature without affecting the runtime version
  source. `importlib.metadata` returns the same value whether installed
  from a wheel or `pip install -e .`, satisfying the edge case that
  `--version` works from a development install.
- **Alternatives considered**:
  - **setuptools**: works fine but pulls a heavier toolchain and historic
    `setup.cfg`/`setup.py` complexity. Nothing about FEAT-001 needs it.
  - **poetry**: imposes its own dependency-resolution and lockfile model;
    too opinionated for a stdlib-only package.
  - **flit**: comparable to hatchling but slightly less common; hatchling
    has clearer src-layout docs.
  - **vcs-derived version**: nice-to-have but couples release tagging to
    the build; defer to a later feature once a release flow exists.

## R-003 — Path resolution: defaults and XDG overrides

- **Decision**: A single resolver function returns a frozen
  `Paths` dataclass with the six members `config_file`, `state_db`,
  `events_file`, `logs_dir`, `socket`, `cache_dir` (matching the FR-004
  uppercase keys `CONFIG_FILE`, `STATE_DB`, `EVENTS_FILE`, `LOGS_DIR`,
  `SOCKET`, `CACHE_DIR`). The resolver reads, in order:
  1. `$XDG_CONFIG_HOME` if set and non-empty, else `$HOME/.config`.
  2. `$XDG_STATE_HOME` if set and non-empty, else `$HOME/.local/state`.
  3. `$XDG_CACHE_HOME` if set and non-empty, else `$HOME/.cache`.

  It then joins each with `opensoft/agenttower/…` to produce:
  | Member | Path under config base | Path under state base | Path under cache base |
  |---|---|---|---|
  | `config_file` | `opensoft/agenttower/config.toml` | — | — |
  | `state_db` | — | `opensoft/agenttower/agenttower.sqlite3` | — |
  | `events_file` | — | `opensoft/agenttower/events.jsonl` | — |
  | `logs_dir` | — | `opensoft/agenttower/logs/` | — |
  | `socket` | — | `opensoft/agenttower/agenttowerd.sock` | — |
  | `cache_dir` | — | — | `opensoft/agenttower/` |

  All values returned as `pathlib.Path` (not strings) and never auto-
  expanded beyond `$HOME`/XDG. Empty XDG values are treated as unset
  (XDG spec requires this).
- **Rationale**: One resolver, one struct, one source of truth. Matches
  the constitution defaults exactly when XDG is unset; honors XDG when
  set; uses `pathlib.Path` so callers can `path.parent.mkdir(...)`
  without string surgery. Empty-string handling per XDG spec
  (https://specifications.freedesktop.org/basedir-spec) prevents silent
  resolution to `/opensoft/agenttower/...` when `XDG_*=`.
- **Alternatives considered**:
  - **Use `appdirs`/`platformdirs`**: pulls a third-party dep for one
    function. Constitution favors stdlib.
  - **Resolve lazily per-call**: makes tests harder to isolate and
    invites drift between CLI and tests.
  - **Treat empty XDG as override-to-empty**: violates the XDG base
    directory spec.

## R-004 — Daemon socket location: state-dir vs `XDG_RUNTIME_DIR`

- **Decision**: The daemon socket lives at `STATE_DB`'s sibling under the
  state base —
  `<state_base>/opensoft/agenttower/agenttowerd.sock`. We do **not**
  consult `XDG_RUNTIME_DIR` for FEAT-001.
- **Rationale**: The architecture document and constitution both pin
  the socket at `~/.local/state/opensoft/agenttower/agenttowerd.sock`.
  `XDG_RUNTIME_DIR` is appealing on systemd-managed hosts but it is
  optional, frequently unset on WSL and inside bench containers, and
  bind-mounting a runtime-dir socket into containers is harder than
  mounting a state-dir path. A single resolved path used by both the
  host CLI and the container client (FEAT-005) reduces failure modes.
  This matches the spec's edge case "`XDG_RUNTIME_DIR` is unset or
  unwritable on a system where it would normally hold the daemon
  socket: path resolution MUST fall back deterministically to the
  documented state-directory location".
- **Alternatives considered**:
  - **Prefer `$XDG_RUNTIME_DIR/opensoft/agenttower/agenttowerd.sock`
    when set, fall back to state dir**: introduces a configuration
    branch FEAT-005's container mount has to discover; rejected for
    FEAT-001's MVP. May revisit when the socket has multiple servers.
  - **Hard-code `/run/user/$UID/...`**: skips XDG entirely and breaks on
    WSL, in containers, and on macOS-style hosts later.

## R-005 — Default configuration content and TOML emission

- **Decision**: `config init` writes the following exact content when
  `CONFIG_FILE` does not already exist:
  ```toml
  # AgentTower configuration
  # Generated by `agenttower config init`. Edit freely; subsequent
  # `config init` runs will not overwrite this file.

  [containers]
  name_contains = ["bench"]
  scan_interval_seconds = 5
  ```
  TOML is emitted by hand (a small `_render_default_config()` function
  produces a constant string). No third-party TOML *writer* dependency.
- **Rationale**: The config has exactly two scalar/array values today;
  hand-rendering keeps stdlib-only. The values match
  `docs/architecture.md` §6 verbatim. Comments explain provenance and
  the idempotence contract so a developer who opens the file
  understands the contract.
- **Alternatives considered**:
  - **`tomli_w`**: third-party dep for a one-time write. Rejected.
  - **JSON-with-comments-stripped**: violates the constitution's
    `config.toml` path. Rejected.
  - **Pull the default from a packaged `config.toml.in` data file**:
    correct longer-term, but adds package-data plumbing for one file.
    Worth revisiting in FEAT-003 when config grows.

## R-006 — SQLite open semantics and schema-version idempotence

- **Decision**: `state.schema.open_registry(state_db: Path) -> sqlite3.Connection`:
  - Ensures the parent directory exists (mode `0700`).
  - Opens with `sqlite3.connect(state_db, isolation_level=None,
    detect_types=0)`.
  - Sets `PRAGMA journal_mode = WAL` (idempotent).
  - Sets `PRAGMA foreign_keys = ON` (forward-compat with FEAT-002+).
  - Executes:
    ```sql
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER NOT NULL
    );
    ```
  - If the table is empty, inserts the current schema generation
    integer (constant `CURRENT_SCHEMA_VERSION = 1`). If the table is
    non-empty, leaves it alone (idempotence).
  - Sets the file mode to `0600` after creation (only if the file did
    not previously exist on this run).
- **Rationale**: All ops use `IF NOT EXISTS` and a count-then-insert
  pattern, satisfying FR-009 and FR-010. WAL mode is the standard for
  long-lived SQLite registries that will be opened concurrently by the
  daemon (FEAT-002+). `foreign_keys=ON` costs nothing today and avoids
  a future PRAGMA-during-migration footgun.
- **Alternatives considered**:
  - **`PRAGMA user_version`**: only one integer, but invisible to
    `SELECT` queries and doesn't survive `.dump`/`.restore`. The
    clarification (Q3) selected an explicit table.
  - **`schema_version` with a single-row `CHECK` constraint enforcing
    `rowid = 1`**: cleaner integrity, but more SQL surface than
    necessary at MVP. Idempotence is enforced application-side.
  - **`CREATE TABLE … STRICT`**: SQLite STRICT tables came in 3.37; not
    universal in all bench images yet. Defer.

## R-007 — JSONL event-writer: format and concurrency

- **Decision**: A single module `agenttower.events.writer` exposes:
  ```python
  def append_event(events_file: Path, payload: Mapping[str, Any]) -> None
  ```
  Behavior:
  - Builds the record as `{"ts": <ISO-8601 UTC with offset>, **payload}`
    (caller-supplied keys win on collision).
  - Serializes with `json.dumps(record, separators=(",", ":"),
    ensure_ascii=False, allow_nan=False)`.
  - Acquires a module-level `threading.Lock` for the duration of the
    open-append-flush.
  - Opens the file with `O_WRONLY | O_CREAT | O_APPEND`, mode `0o600`.
  - Writes the JSON string + `"\n"` in one `write()` call, then
    `os.fsync(fd)`, then closes.
  - If the parent directory does not exist, creates it with mode
    `0o700` first.
  - Timestamps use `datetime.datetime.now(datetime.UTC).isoformat(
    timespec="microseconds")` so records are sortable lexicographically.
- **Rationale**: A single `write()` of `≤ PIPE_BUF` bytes on a regular
  file with `O_APPEND` is atomic on Linux. The added in-process
  `threading.Lock` makes the contract uniform regardless of payload
  size or filesystem (e.g. some FUSE backings on WSL). `fsync` on every
  append is acceptable here because event volume is low and audit
  durability matters more than throughput.
- **Alternatives considered**:
  - **`logging` with `WatchedFileHandler`**: works, but couples our
    audit format to Python's logging filter stack and complicates
    timestamp control.
  - **`fcntl.flock`**: needed only when multiple processes append.
    FEAT-001 is single-process; the in-process lock is sufficient and
    portable. FEAT-002 may add `flock` once the daemon is involved.
  - **Buffered write**: violates the per-record durability spirit of
    JSONL audit history.

## R-008 — CLI framework

- **Decision**: Standard-library `argparse`. The user CLI uses one
  top-level parser with:
  - A top-level `--version` flag.
  - A top-level `config` subparser with two sub-subparsers: `paths` and
    `init`.

  The daemon CLI uses a separate top-level parser with only `--version`
  in FEAT-001.
- **Rationale**: stdlib only; argparse handles `--version` and `--help`
  out of the box; subcommand discovery (`agenttower --help` lists
  `config`) is automatic. Click/typer would add dependencies and
  decorator runtime cost for one feature's worth of plumbing.
- **Alternatives considered**:
  - **click**: nicer UX but third-party dep.
  - **typer**: depends on click + typing-shenanigans; overkill.
  - **plac**: niche; rejected.

## R-009 — Version source

- **Decision**: `__version__` is computed at import time in
  `agenttower/__init__.py` via:
  ```python
  from importlib.metadata import PackageNotFoundError, version as _version
  try:
      __version__ = _version("agenttower")
  except PackageNotFoundError:  # not installed (e.g. running from src tree)
      __version__ = "0.0.0+local"
  ```
- **Rationale**: One source of truth (the `pyproject.toml` `version`
  field). Editable installs via `pip install -e .` populate package
  metadata correctly, so this works in development. The fallback
  prevents an `ImportError` if the package is on `sys.path` without
  metadata (e.g. running tests directly out of `src/` in a dev shell
  before `pip install`).
- **Alternatives considered**:
  - **Hard-coded `__version__ = "0.1.0"`**: drift between code and
    package metadata.
  - **Read `pyproject.toml` at runtime**: violates "don't ship pyproject
    to users" and breaks for built wheels.

## R-010 — Test isolation strategy

- **Decision**: Every test that touches the filesystem uses a
  pytest fixture that:
  1. `monkeypatch.setenv("HOME", str(tmp_path))`.
  2. `monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)` and same for
     `XDG_STATE_HOME`, `XDG_CACHE_HOME`, `XDG_RUNTIME_DIR` — unless the
     test specifically exercises an XDG override.
  3. Returns a `Paths` instance freshly resolved from that environment.

  Integration tests invoke the CLI via
  `subprocess.run([sys.executable, "-m", "agenttower", ...], env=...)`
  so the entry-point wiring is exercised end-to-end.
- **Rationale**: Guarantees cross-test independence, matches the
  spec's "tests can assert this without invoking any other AgentTower
  feature", and avoids polluting the real `~/.config`/`~/.local/state`.
- **Alternatives considered**:
  - **Run tests as a separate user / inside a container**: heavier than
    needed.
  - **Patch `pathlib.Path.home()` directly**: less robust than env
    isolation; `os.path.expanduser` would still see the real `HOME`.
