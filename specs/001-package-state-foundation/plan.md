# Implementation Plan: Package, Config, and State Foundation

**Branch**: `001-package-state-foundation` | **Date**: 2026-05-05 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-package-state-foundation/spec.md`

## Summary

Establish the AgentTower Python package, two console-script entrypoints
(`agenttower`, `agenttowerd`), the Opensoft-namespaced filesystem layout
(config / state / logs / socket / cache), an idempotent `config init` that
creates that layout with strict host-only permissions, an integer
`schema_version`-tabled SQLite registry, and a shared internal JSONL
event-writer utility. The technical approach is Python 3.11+ stdlib only
(no runtime third-party dependencies), packaged with `pyproject.toml` using
hatchling, structured around the existing `src/agenttower/` layout. All
filesystem behavior is gated by an explicit `Paths` resolver that honors
the XDG base-directory variables under the canonical `opensoft/agenttower`
sub-namespace and falls back to constitutional defaults otherwise.

## Technical Context

**Language/Version**: Python 3.11+ (selected so that `tomllib` is available
in the standard library for any future TOML reads; FEAT-001 itself only
writes TOML).
**Primary Dependencies**: Standard library only — `argparse`, `sqlite3`,
`pathlib`, `os`, `json`, `datetime`, `threading`, `importlib.metadata`,
`stat`, `errno`. No third-party runtime dependencies.
**Storage**: SQLite single-file registry at the resolved `STATE_DB` path;
append-only JSONL audit history at the resolved `EVENTS_FILE` path. SQLite
opened with `journal_mode=WAL` for forward-compatibility with FEAT-002+
daemon reads.
**Testing**: pytest (≥ 7) with `tmp_path` and `monkeypatch` fixtures;
environment isolation via per-test override of `$HOME`, `$XDG_CONFIG_HOME`,
`$XDG_STATE_HOME`, `$XDG_CACHE_HOME`. No Docker, no tmux, no network
required to run the FEAT-001 test suite.
**Target Platform**: Linux/WSL developer workstations with POSIX filesystem
semantics. Single host user.
**Project Type**: Single-project Python CLI + daemon entrypoint (the daemon
ships only as a `--version`-reporting stub in this feature; FEAT-002 owns
its lifecycle).
**Performance Goals**: `agenttower --version` and `agenttowerd --version`
each return in well under five seconds on a clean dev install (SC-001);
`config init` completes a cold-start initialization in well under one
second; the event-writer handles 100 concurrent in-process appends without
record interleaving (SC-007).
**Constraints**: No network listener (FR-016); strict host-only file modes
(`0700` for directories, `0600` for files, FR-015); no FEAT-001 command
emits a JSONL event (FR-016); no third-party runtime dependencies; nothing
in `--version`, `config paths`, or `config init` may invoke Docker, tmux,
the daemon socket listener, the registry beyond the schema-version row,
the event classifier, or any input delivery path.
**Scale/Scope**: One host user, one config file, one SQLite DB with one
table and one row, one append-only event file. The entire feature surface
is two console scripts and three subcommands.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Local-First Host Control | PASS | No network listener (FR-016); durable state strictly under Opensoft namespace (FR-006/FR-007); single-host-user permissions (FR-015). |
| II. Container-First MVP | PASS | Feature scope deliberately excludes host-only tmux discovery, Antigravity, mailbox bridges, in-container relays (FR-016). The host-side CLI/daemon scaffolding it produces is exactly what container-first MVP requires next. |
| III. Safe Terminal Input | PASS (vacuously) | FEAT-001 introduces no input delivery path. FR-016 explicitly forbids any of `--version`, `config paths`, `config init` from sending terminal input. |
| IV. Observable and Scriptable | PASS | Every behavior is a CLI subcommand. `config paths` is `KEY=value` machine-parseable (FR-004). Errors are non-zero-exit + actionable stderr (FR-014). Durable state is plain SQLite + JSONL on disk. |
| V. Conservative Automation | PASS | No classification, no routing, no automation. The package is registry/path-layout only. |

| Technical Constraint | Status | Evidence |
|----------------------|--------|----------|
| Primary language is Python | PASS | Python 3.11+, stdlib only. |
| Console entrypoints `agenttower` & `agenttowerd` | PASS | `pyproject.toml` `[project.scripts]` defined in Phase 1 contracts. |
| Files under `~/.config/opensoft/agenttower/`, `~/.local/state/opensoft/agenttower/`, `~/.cache/opensoft/agenttower/` | PASS | FR-006/FR-007 with XDG override semantics. |
| Docker default `name_contains = ["bench"]`, host `docker exec -u "$USER"` | OUT OF SCOPE for FEAT-001 | Default config emits the `[containers]` section so FEAT-003 inherits it (FR-008). |
| CLI: human-readable defaults + structured output where it helps | PASS | `config paths` is single-canonical `KEY=value`; clarified Q2. |

| Development Workflow | Status | Evidence |
|----------------------|--------|----------|
| Build in `docs/mvp-feature-sequence.md` order | PASS | This is FEAT-001. |
| Each feature CLI-testable | PASS | All three subcommands and `--version` exercise the full feature. |
| Tests proportional to risk; broader for daemon state, sockets, Docker/tmux/permissions/input | PASS | Permissions, idempotence, schema-version, path resolution, and concurrent JSONL appends all have dedicated tests (FR-017, SC-009). No daemon/socket/Docker/tmux/input surface to test in this feature. |
| Preserve existing docs and NotebookLM sync mappings | PASS | This feature does not edit existing Markdown under `docs/`. |
| No TUI, web UI, or relay before the core slices work | PASS | None introduced here. |

**Result**: Gates pass. No `Complexity Tracking` entries required.

## Project Structure

### Documentation (this feature)

```text
specs/001-package-state-foundation/
├── plan.md              # This file (/speckit.plan output)
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   ├── cli.md           # User-facing CLI contracts (agenttower / agenttowerd)
│   └── event-writer.md  # Internal event-writer utility contract
├── checklists/
│   └── requirements.md  # /speckit.specify quality checklist
└── tasks.md             # /speckit.tasks output (NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
pyproject.toml                          # NEW: package metadata + console scripts
README.md                               # (existing, untouched by this feature)

src/agenttower/
├── __init__.py                         # __version__ sourced from importlib.metadata
├── cli.py                              # argparse-based user CLI (--version, config paths, config init)
├── daemon.py                           # daemon entrypoint stub (--version only in FEAT-001)
├── paths.py                            # Paths resolver (Resolved Path Set + XDG)
├── config.py                           # Default config writer + read helpers
├── state/
│   ├── __init__.py
│   └── schema.py                       # SQLite open + schema_version creation/read
└── events/
    ├── __init__.py
    └── writer.py                       # JSONL append-only event-writer utility

tests/
├── unit/
│   ├── __init__.py
│   ├── test_imports.py                 # (existing) sanity import test
│   ├── test_paths.py                   # NEW: defaults + XDG overrides + socket fallback
│   ├── test_state_schema.py            # NEW: schema_version create + idempotent read
│   └── test_events_writer.py           # NEW: append, timestamp, concurrent threads
└── integration/
    ├── __init__.py
    └── test_cli.py                     # NEW: end-to-end --version / config paths / config init / idempotence / unwritable-target / permissions
```

**Structure Decision**: Single-project layout, kept consistent with the
existing `src/agenttower/` scaffolding. Empty subpackages already present
on disk (`discovery/`, `docker/`, `logging/`, `routing/`, `socket_api/`,
`tmux/`) are intentionally **left untouched** by FEAT-001 — they are
placeholders owned by FEAT-002 through FEAT-010. Only the four modules
this feature actually populates (`cli.py`, `daemon.py`, `paths.py`,
`config.py`) plus two new subpackages (`state/`, `events/`) are in scope.

## Complexity Tracking

> No constitutional violations to justify. This section is intentionally empty.
