# Implementation Plan: Container-Local Thin Client Connectivity

**Branch**: `005-container-thin-client` | **Date**: 2026-05-06 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/005-container-thin-client/spec.md`

## Summary

Add a container-local thin-client surface on top of the FEAT-001 /
FEAT-002 / FEAT-003 / FEAT-004 host daemon. The same `agenttower`
binary, run from inside a bench container whose mount namespace
exposes the host daemon's `AF_UNIX` socket, MUST connect to that
socket and return identical results to the host CLI. The feature
introduces no new socket method, no schema change, no network
listener, and no in-container daemon (FR-022, FR-026). Every new
line of code is read-only inspection of `/proc`, `/etc`, and the
process environment, plus reuse of the existing FEAT-002 client over
the existing FEAT-002 / FEAT-003 / FEAT-004 socket methods (FR-020).

Socket-path resolution becomes a pure function `(env, host_paths) →
(path, source)` with priority `AGENTTOWER_SOCKET` (`env_override`) →
mounted-default `/run/agenttower/agenttowerd.sock`
(`mounted_default`, only when container-runtime detection fires AND
the path resolves to a Unix socket) → FEAT-001 host default
(`host_default`) (FR-001, FR-003). The override is validated as an
absolute path, non-empty, NUL-free, and pointing at a Unix socket;
invalid values exit `1` within the FR-002 / SC-002 50 ms pre-flight
budget rather than silently falling back. Container-runtime detection
is a closed-set signal pipeline over `/.dockerenv`, `/run/.containerenv`,
and `/proc/self/cgroup` (FR-004) that requires no root and no
subprocess.

Container identity converges through a four-signal precedence chain:
`AGENTTOWER_CONTAINER_ID` env override → cgroup-derived id →
`/etc/hostname` → `$HOSTNAME`, cross-checked against the daemon's
FEAT-003 `list_containers` result by full-id-then-12-char-prefix
match (FR-006, FR-007). The cross-check classifies into the closed
set `{unique_match, multi_match, no_match, no_candidate,
host_context}` and NEVER widens the FEAT-003 container set (FR-008).
Tmux self-identity parses `$TMUX` (comma-split
`socket_path,server_pid,session_id`) and `$TMUX_PANE` (`%N`), then
cross-checks the daemon's FEAT-004 `list_panes` filtered by the
resolved container id when known, classifying into
`{pane_match, pane_unknown_to_daemon, pane_ambiguous, not_in_tmux}`
(FR-009, FR-010, FR-011).

A new subcommand `agenttower config doctor` runs the closed-set
checks `socket_resolved → socket_reachable → daemon_status →
container_identity → tmux_present → tmux_pane_match` in order
(FR-012). Every check emits exactly one `CheckResult` row on every
invocation (FR-027) — the doctor never aborts early and never omits
a check from the output. When an upstream gate has already failed
(per Clarifications 2026-05-06 in spec.md) the dependent check
still emits its row but skips the actual socket round-trip; the
row carries `status=info` with sub-code `daemon_unavailable`. This
keeps the FR-014 JSON contract complete without burning the
SC-003 budget on round-trips that cannot succeed. Default output
is one TSV row per check plus a
summary line; `--json` emits one canonical object per invocation
with stable keys (FR-013, FR-014). Exit codes map through
`{0, 1, 2, 3, 5}` per FR-018, mirroring FEAT-002 / FEAT-003 codes
exactly. Doctor is pure read-only: zero SQLite writes, zero JSONL
appends, zero file creation (FR-029). All untrusted inputs (env,
cgroup, hostname, tmux env) are NUL-byte-stripped, control-byte-
stripped, length-bounded to 4096 chars in (FR-021), and every
doctor row's `details` / `actionable_message` is bounded to 2048
chars with multi-byte-safe `…` truncation (FR-028).

`agenttower config paths` is extended with exactly one trailing line
`SOCKET_SOURCE=<env_override|mounted_default|host_default>`; no
other existing line is altered (FR-019). All FEAT-001 / FEAT-002 /
FEAT-003 / FEAT-004 commands run from the host with no container
context produce byte-identical stdout, stderr, and exit codes
(FR-005, FR-026, SC-006, SC-007). The feature is testable end-to-end
without a real container, real Docker, or real tmux server through
a single new test seam `AGENTTOWER_TEST_PROC_ROOT` that points at a
fake `/proc` + `/etc` fixture directory (FR-025); the host-side
daemon harness from FEAT-002 / FEAT-003 / FEAT-004 is reused
unchanged. Doctor wall-clock against a healthy daemon and a
fully-resolvable identity stays under the SC-003 500 ms budget
including the FEAT-002 status round-trip and the FEAT-004
`list_panes` cross-check.

## Technical Context

**Language/Version**: Python 3.11+ (inherits from FEAT-001 /
FEAT-002 / FEAT-003 / FEAT-004; pyproject pins
`requires-python>=3.11`). Standard library only — no third-party
runtime dependency added.

**Primary Dependencies**: Standard library only — `os`, `pathlib`,
`socket`, `argparse`, `json`, `dataclasses`, `typing`, `re` (for
`$TMUX_PANE` shape validation), `stat` (for `S_ISSOCK`),
`unicodedata`/`str` slicing (for multi-byte-safe truncation of
doctor row text). Reuses the existing FEAT-002 socket client
(`socket_api/client.py`) verbatim. No `subprocess`, no `tmux`
binary, no `docker` binary in any FEAT-005 in-container code path
(FR-011, FR-020).

**Storage**: Read-only against every FEAT-001 / FEAT-002 / FEAT-003
/ FEAT-004 surface. **No schema change**, **no new tables**, **no
new files on disk** (FR-026, FR-029). Doctor is a pure read-only
diagnostic that writes nothing — no SQLite writes, no JSONL appends,
no log rotation, no file creation. The host daemon's lifecycle log
MAY record the FR-016 underlying `status` round-trip exactly the way
it already does for FEAT-002 callers; FEAT-005 introduces no new
lifecycle log token.

**Testing**: pytest (≥ 7), reusing the FEAT-002 / FEAT-003 / FEAT-004
daemon harness in `tests/integration/_daemon_helpers.py` verbatim —
every FEAT-005 integration test spins up a real host daemon under an
isolated `$HOME` and drives the `agenttower` console script as a
subprocess. Three test seams are used in concert so no real
container, no real Docker daemon, and no real tmux server is ever
invoked: the existing `AGENTTOWER_TEST_DOCKER_FAKE` (FEAT-003) and
`AGENTTOWER_TEST_TMUX_FAKE` (FEAT-004) seams seed the daemon's
container and pane registries, and a new `AGENTTOWER_TEST_PROC_ROOT`
env var points the in-container detection code at a fixture directory
that stands in for `/proc` and `/etc` (containing a fabricated
`proc/self/cgroup`, optional `proc/1/cgroup`, `etc/hostname`, and the
`/.dockerenv` / `/run/.containerenv` sentinels). The hook is
namespaced under the `AGENTTOWER_TEST_*` prefix so it cannot be set
accidentally in production, and a dedicated host-only integration
test (`test_feat005_proc_root_unset_in_prod.py`) asserts the
production CLI rejects or ignores the variable when run outside the
test harness, satisfying FR-025. Integration tests cover every
US1/US2/US3 acceptance scenario plus the spec's edge cases.
FR-027 is enforced by a dedicated short-circuit test that fails one
required check and asserts the remaining checks still ran. Unit
tests cover every area enumerated in SC-009: socket-path resolution,
container-runtime detection, identity-signal parsing, daemon
cross-check classification, tmux env parsing, doctor TSV/JSON
rendering, exit-code mapping, and per-field sanitization/truncation.
A backwards-compatibility test (`test_feat005_backcompat.py`) gates
SC-007 by re-running every FEAT-001..004 CLI command on the host and
asserting byte-identical stdout, stderr, exit codes, and `--json`
shapes.

**Target Platform**: Linux/WSL developer workstations. The daemon
continues to run exclusively on the host (constitution principle I);
FEAT-005 introduces zero in-container processes beyond the
`agenttower` CLI invocation itself, which is a single short-lived
read-only client.

**Project Type**: Single-project Python CLI + daemon. Extends
`src/agenttower/`. Two existing modules (`cli.py`, `paths.py`) gain
small, additive surfaces; one new package (`config_doctor/`) is
introduced for the doctor implementation, mirroring the
`discovery/` and `tmux/` packages introduced by FEAT-003 and
FEAT-004. The existing `socket_api/client.py` is reused as-is.

**Performance Goals**: SC-002 — pre-flight rejection of an invalid
`AGENTTOWER_SOCKET` exits within 50 ms with no daemon-side state
change (the validator runs entirely in-process before any socket
syscall). SC-003 — `agenttower config doctor` against a healthy
daemon, a healthy `list_panes` cross-check, and a fully-resolvable
identity completes within 500 ms wall clock end-to-end including
the FEAT-002 status round-trip and one `list_panes` socket call.
Doctor runs all six checks on every invocation (FR-027) and never
short-circuits. Daemon-down doctor runs (FR-016 closed-set sub-codes
for `socket_missing`, `connection_refused`, `connect_timeout`)
bound the connect-timeout to the FEAT-002 default (1 s) so a
fully-failing doctor still completes under ~2 s.

**Constraints**:
- No network listener anywhere in FEAT-005; the in-container CLI
  reuses FEAT-002's `AF_UNIX` socket-file authorization (`0600`,
  host user only) verbatim (FR-022, FR-023; constitution
  principle I).
- No third-party runtime dependency; all path resolution, container-
  runtime detection, identity detection, tmux env parsing,
  sanitization, and doctor rendering use Python stdlib only
  (FR-005, FR-026).
- `AGENTTOWER_SOCKET` validation gate: when set, the value MUST be
  non-empty, absolute, free of NUL bytes, and free of shell-metachar
  interpretation (the value is used as a literal filesystem path,
  never passed to a shell); invalid values exit `1` with
  `error: AGENTTOWER_SOCKET must be an absolute path to a Unix
  socket: <reason>` and the CLI MUST NOT silently fall back (FR-002,
  edge cases 1 and 2; SC-002).
- `AGENTTOWER_SOCKET` filesystem-shape gate: regular files,
  directories, broken symlinks, and non-`S_ISSOCK` targets are
  rejected with the FR-002 message; symlinks are followed exactly
  one level before the `S_ISSOCK` check (edge case 2).
- Container-runtime detection is local-filesystem only and MUST NOT
  shell out: no `docker exec`, no `docker inspect`, no subprocess
  of any kind inside the container; only reads of `/.dockerenv`,
  `/run/.containerenv`, `/proc/self/cgroup` (FR-004, FR-011,
  FR-020).
- File-open allowlist (FR-020): `/proc/self/`, `/proc/1/`,
  `/etc/hostname`, `/run/.containerenv`, `/.dockerenv`, the
  resolved socket path, the FEAT-001 host paths, and the
  `AGENTTOWER_TEST_PROC_ROOT` fixture root in tests. No other path
  is opened by FEAT-005 code.
- Detection signal pipeline is the closed set `/.dockerenv` ∨
  `/run/.containerenv` ∨ `/proc/self/cgroup` line containing
  `docker/` | `containerd/` | `kubepods/` | `lxc/`; nothing else
  fires `container_context` (FR-004; edge cases re. unusual
  sandboxes such as Firejail, Bubblewrap, systemd-nspawn).
- Container-identity detection precedence is fixed and total:
  (1) `AGENTTOWER_CONTAINER_ID` env override, (2) `/proc/self/cgroup`
  last-segment match, (3) `/etc/hostname`, (4) `$HOSTNAME` (FR-006;
  edge cases re. `--network host` and empty cgroup).
- Cross-check classification is closed-set: `unique_match` |
  `multi_match` | `no_match` | `no_candidate` | `host_context`;
  full-id equality is checked before 12-char short-id prefix match;
  `multi_match` is reported, never auto-resolved (FR-007; edge
  case re. duplicate short-id prefixes).
- The in-container CLI MUST NOT widen the FEAT-003 container set;
  `scan_containers` is never invoked from inside the container
  (FR-008).
- Tmux self-identity is read-only parsing of `$TMUX`
  (`socket_path,server_pid,session_id`) and `$TMUX_PANE` (`%N`);
  FEAT-005 MUST NOT spawn `tmux`, `id`, `cat`, or any other
  subprocess (FR-009, FR-011, FR-020).
- All untrusted input (`$TMUX`, `$TMUX_PANE`, `/proc/self/cgroup`,
  `/etc/hostname`, `$HOSTNAME`, `AGENTTOWER_CONTAINER_ID`) MUST be
  NUL-stripped, C0-control-stripped, length-bounded to 4096 chars,
  never interpolated into a shell string; out-of-shape values
  surface as `output_malformed` rather than crashing (FR-021;
  edge case re. `$TMUX_PANE` not matching `%N`).
- Doctor row `details` and `actionable_message` are sanitized and
  bounded to 2048 chars, mirroring FEAT-004 R-009 verbatim;
  truncation appends `…` and is UTF-8-aware (never splits a
  multi-byte char) (FR-028).
- `socket_reachable` failures map to the closed sub-code set
  `{socket_missing, socket_not_unix, connection_refused,
  permission_denied, connect_timeout, protocol_error}`; raw
  `socket(2)` / `connect(2)` errno text MUST NOT leak to stderr or
  `--json` output (FR-016, FR-024; SC-004).
- Doctor exit-code mapping is exactly `0` (all pass/info), `1`
  (pre-flight), `2` (`socket_reachable` ∈
  {`socket_missing`, `connection_refused`, `connect_timeout`}),
  `3` (`socket_reachable=pass` AND `daemon_status=fail` with sub-code
  `daemon_error` — FEAT-002 `DaemonError` envelope — or
  `schema_version_newer` — daemon ahead of CLI per R-010), `5`
  (degraded — round-trip ok but a non-required check failed);
  `4` is reserved for internal CLI error per FEAT-002 (FR-018).
- Doctor MUST emit a `CheckResult` row for every closed-set check
  on every invocation; no early abort on a failing check, and no
  check is omitted from the output. When an upstream gate has
  already failed, the dependent check skips its actual socket
  round-trip and emits `status=info` with sub-code
  `daemon_unavailable` per Clarifications 2026-05-06 in spec.md
  (FR-027; SC-004).
- Doctor MUST write nothing to disk: no SQLite writes, no JSONL
  appends, no log rotation, no file creation; the only side effect
  is the existing FEAT-002 `status` round-trip the host daemon
  already records (FR-029).
- Doctor adds no new socket method; reachability uses FEAT-002
  `status`, identity cross-check uses FEAT-003 `list_containers`,
  pane cross-check uses FEAT-004 `list_panes` (FR-010, FR-022).
- No SQLite schema migration; FEAT-001..004 surfaces are read-only
  consumers and their persisted shapes are unchanged (FR-026,
  SC-006).
- `--json` mode emits exactly one canonical JSON object per
  invocation; no incidental stderr lines when `--json` is set;
  check codes and status tokens are stable across releases and
  only added, never renamed (FR-014; edge case re. JSON purity;
  SC-005).
- Test seam is namespaced `AGENTTOWER_TEST_PROC_ROOT` (mirroring
  FEAT-003 `AGENTTOWER_TEST_DOCKER_FAKE` and FEAT-004
  `AGENTTOWER_TEST_TMUX_FAKE`); a production-binary integration
  test asserts the var is unset at startup (FR-025).
- The FEAT-002 `_connect_via_chdir` workaround for `sun_path`
  length (108-byte limit) is preserved verbatim; FEAT-005 MUST NOT
  regress the deep-cwd connect path (edge case re. `sun_path`
  limit).

**Scale/Scope**: One host user, one daemon, zero new tables, zero
new socket methods, zero schema migrations, two additive CLI
surfaces (`config doctor` subcommand; one extra line on
`config paths`), one new env override (`AGENTTOWER_SOCKET`), one
new identity env override (`AGENTTOWER_CONTAINER_ID`), one new
test seam (`AGENTTOWER_TEST_PROC_ROOT`). Expected steady-state
usage: a single `agenttower config doctor` invocation per
debugging session, six checks per invocation, one `status`
round-trip and at most one `list_containers` and one
`list_panes` round-trip per invocation. Response payloads are
single-digit kilobytes.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle                     | Status | Evidence |
| ----------------------------- | ------ | -------- |
| I. Local-First Host Control   | PASS   | The thin client reuses the existing host daemon over the existing `AF_UNIX` socket (FR-001, FR-023). FR-022 forbids any new network listener, in-container daemon, or relay; FEAT-005's tests assert the same harness invariant FEAT-002 / FEAT-003 / FEAT-004 do (no AF_INET/AF_INET6). Durable state stays under the host's `opensoft/agenttower` namespace; FR-029 forbids any in-container disk write. |
| II. Container-First MVP       | PASS   | This is the first MVP step that runs the `agenttower` CLI from *inside* a bench container against the host daemon. The mounted-default socket path (`/run/agenttower/agenttowerd.sock`, FR-003) and the cgroup/hostname/env identity pipeline (FR-006) are explicitly bench-container-shaped. Host-only behavior remains bytewise unchanged (FR-005, SC-007). |
| III. Safe Terminal Input      | PASS (vacuously) | FR-022 forbids any input delivery, prompt queuing, registration, or log capture in this feature. No subprocess is spawned in-container (FR-011, FR-020); no tmux command is sent; every untrusted input is treated as bounded data (FR-021) and never interpolated into a shell string. The remaining "safety" risk — that a future maintainer adds a subprocess to "improve" detection — is closed by FR-011 / FR-020 (no `tmux` subprocess; allowlisted read-only paths only); reviewers MUST reject any such PR unless the spec is amended. |
| IV. Observable and Scriptable | PASS   | The new `config doctor` ships dual output: human-readable TSV rows with a summary line by default (FR-013) and a stable canonical JSON object under `--json` with closed-set check codes and status tokens (FR-014). Every failure carries a one-line `actionable_message` (FR-007, FR-016). Doctor runs every check on every invocation (FR-027) and exit codes mirror existing FEAT-002 / FEAT-003 codes exactly (FR-018). |
| V. Conservative Automation    | PASS   | FR-008 forbids the in-container CLI from widening the FEAT-003 container set (no auto-`scan`); FR-022 forbids registration, role/capability metadata, log capture, and input delivery; FR-027 forbids early-aborting checks (the operator decides what to fix). FEAT-005 reports identity, it does not act on it. |

| Technical Constraint                                                          | Status | Evidence |
| ----------------------------------------------------------------------------- | ------ | -------- |
| Primary language Python                                                       | PASS   | Python 3.11+, stdlib only. No new runtime dependency. |
| Console entrypoints `agenttower` & `agenttowerd`                              | PASS   | Extends `agenttower` with `config doctor` and one new line on `config paths`. `agenttowerd run` is unchanged. |
| Files under `~/.config` / `~/.local/state` / `~/.cache` `opensoft/agenttower` | PASS   | No new path written. The mounted-default in-container socket (`/run/agenttower/agenttowerd.sock`) is an MVP bind-mount target (assumption; resolves architecture.md §25 open question) and is read-only from the CLI's perspective. |
| Docker default `name_contains = ["bench"]`, host `docker exec -u "$USER"`     | PASS (vacuously) | FEAT-005 calls neither `docker` nor `docker exec`. Identity cross-check reuses FEAT-003 `list_containers` rows; tmux cross-check reuses FEAT-004 `list_panes` rows. |
| CLI: human-readable defaults + structured output where it helps               | PASS   | `config doctor` ships TSV by default and `--json` (FR-013, FR-014). `config paths` keeps its existing `KEY=value` line shape with one additive trailing line (FR-019). |

| Development Workflow                                                          | Status | Evidence |
| ----------------------------------------------------------------------------- | ------ | -------- |
| Build in `docs/mvp-feature-sequence.md` order                                 | PASS   | This is FEAT-005, immediately after FEAT-004. |
| Each feature CLI-testable                                                     | PASS   | US1 covered by `test_cli_in_container_status.py`, `test_cli_in_container_socket_override.py`, `test_cli_no_socket_mount.py`. US2 covered by `test_cli_config_doctor_healthy.py`, `test_cli_config_doctor_daemon_down.py`, `test_cli_config_doctor_host_context.py`, `test_cli_config_doctor_json.py`, `test_cli_config_doctor_short_circuit.py`. US3 covered by `test_cli_config_doctor_pane_match.py`, `test_cli_in_container_unsupported_signals.py`, and the unit-level identity/runtime suites. Every acceptance scenario maps to at least one named integration test invoking the real `agenttower` console script. |
| Tests proportional to risk; broader for daemon state, sockets, Docker/tmux adapters, permissions, and input delivery | PASS | Every untrusted-input surface (env, cgroup, hostname, tmux env, daemon-returned strings) has dedicated unit coverage and integration coverage. Socket/permission risks covered by `test_cli_no_socket_mount.py` and the `permission_denied` / `socket_not_unix` paths in `test_cli_config_doctor_daemon_down.py`. Backward compat is gated by `test_feat005_backcompat.py` so SC-007 cannot regress silently. JSON contract stability is locked by `test_doctor_json_contract.py` + `test_cli_config_doctor_json.py`. Exit-code closed set is locked by `test_doctor_exit_codes.py` covering FR-018's 0/1/2/3/5 mapping (with reserved 4). |
| Preserve existing docs and NotebookLM sync mappings                           | PASS   | This feature does not edit existing Markdown under `docs/`. The architecture.md §25 open question on the bind-mount path is resolved in the spec assumptions, not in the docs themselves. |
| No TUI, web UI, or relay before the core slices work                          | PASS   | None introduced here. FEAT-005 is the fourth core slice (after FEAT-002 daemon, FEAT-003 container discovery, FEAT-004 pane discovery). |
| Decide explicitly whether `/speckit.checklist <topic>` is needed before tasks | DECISION | A `security` checklist is recommended before `/speckit.tasks` because FEAT-005 is the *first* feature whose code path consumes container-side untrusted strings (`AGENTTOWER_SOCKET`, `AGENTTOWER_CONTAINER_ID`, `$TMUX`, `$TMUX_PANE`, `/proc/self/cgroup`, `/etc/hostname`, `$HOSTNAME`) and exposes them through a stable JSON contract (FR-014). FEAT-004 ran a `security` checklist for the same class of risk; the spec here introduces strictly more attacker-controlled inputs because the in-container CLI consumes container-provided env and `/proc` content rather than host-driven `docker exec` output. Verifying the FR-021 sanitization bounds, the FR-024 stderr-leak guard, the FR-002 absolute-path validator, and the host/container parity in FR-005 / SC-007 before tasks are generated is worth a topic-specific gate. A second `cli-contract` checklist is *not* recommended because the JSON shape is already pinned by FR-014's stable-key clause. |

**Result**: Gates pass. No `Complexity Tracking` entries required.

## Project Structure

### Documentation (this feature)

```text
specs/005-container-thin-client/
├── plan.md                        # This file (/speckit.plan output)
├── research.md                    # Phase 0 output: resolved decisions
├── data-model.md                  # Phase 1 output: in-memory entity shapes (no SQLite)
├── quickstart.md                  # Phase 1 output: end-to-end CLI walkthrough
├── contracts/
│   ├── cli.md                     # User-facing CLI contracts (C-CLI-501 config doctor; C-CLI-502 config paths SOCKET_SOURCE)
│   └── socket-api.md              # No-new-method contract: pin FR-022; document the reused FEAT-002/003/004 calls used by doctor
├── checklists/                    # /speckit.checklist outputs (security recommended)
└── tasks.md                       # /speckit.tasks output (NOT created by /speckit.plan)
```

### Source Code (repository root)

Only files actually touched by FEAT-005 are listed. FEAT-001 /
FEAT-002 / FEAT-003 / FEAT-004 files remain unchanged unless an
explicit "EXTENDS" note appears.

```text
src/agenttower/
├── cli.py                                # EXTENDS: add `config doctor` subparser; add `AGENTTOWER_SOCKET` resolution at every command's socket-using path; add one new line `SOCKET_SOURCE=<token>` to `config paths` output (FR-019)
├── paths.py                              # EXTENDS: socket resolution returns a `(path, source)` pair via a new `resolve_socket_path(env, paths) -> ResolvedSocket` helper; existing `Paths.socket` field unchanged for back-compat readers
├── socket_api/
│   └── client.py                         # EXTENDS (additive only): tag `DaemonUnavailable` with a structured `.kind` attribute so doctor can map to FR-016 sub-codes without parsing the message; existing message strings unchanged byte-for-byte
└── config_doctor/                        # NEW package: container-thin-client diagnostic surface
    ├── __init__.py                       # NEW: package marker; re-exports run_doctor, ResolvedSocket, IdentityResolution, TmuxIdentity
    ├── runner.py                         # NEW: top-level orchestrator; runs all six FR-012 checks in order; aggregates DoctorReport; computes FR-018 exit code
    ├── checks.py                         # NEW: pure per-check functions (socket_resolved, socket_reachable, daemon_status, container_identity, tmux_present, tmux_pane_match); each returns a CheckResult dataclass
    ├── render.py                         # NEW: TSV row rendering (FR-013) and canonical JSON serializer (FR-014); both consume DoctorReport
    ├── socket_resolve.py                 # NEW: pure FR-001 + FR-002 resolution (env_override → mounted_default → host_default); validates absolute path, NUL, non-empty, exists-as-socket; one-level symlink follow + S_ISSOCK
    ├── runtime_detect.py                 # NEW: FR-004 closed-set signal pipeline (`/.dockerenv`, `/run/.containerenv`, `/proc/self/cgroup` prefix scan); honors AGENTTOWER_TEST_PROC_ROOT
    ├── identity.py                       # NEW: FR-006 + FR-007 container identity resolution (env override → cgroup → /etc/hostname → $HOSTNAME) + cross-check classifier against FEAT-003 list_containers
    ├── tmux_identity.py                  # NEW: FR-009 + FR-010 tmux self-identity parser ($TMUX comma-split, $TMUX_PANE %N validation) + cross-check classifier against FEAT-004 list_panes
    └── sanitize.py                       # NEW: FR-021 + FR-028 untrusted-string bounding (NUL strip, control-byte strip, 4096/2048 char bounds, multi-byte-safe `…` truncation)

tests/
├── unit/
│   ├── test_socket_path_resolution.py        # NEW: FR-001 / FR-002 / SC-002 — env override / mounted-default / host-default precedence; rejects relative path, empty, NUL byte, non-absolute; (path, source) shape
│   ├── test_runtime_detect.py                # NEW: FR-003 / FR-004 — /.dockerenv, /run/.containerenv, cgroup pipeline (docker/, containerd/, kubepods/, lxc/); unparseable cgroup returns no_signal; host-context fall-through; AGENTTOWER_TEST_PROC_ROOT fixture isolation
│   ├── test_container_identity.py            # NEW: FR-006 / FR-007 / SC-008 — env override; cgroup precedence; /etc/hostname fallback; $HOSTNAME fallback; full-id vs 12-char short-id match; classification (unique_match | multi_match | no_match | no_candidate | host_context); --network host hostname collision
│   ├── test_tmux_self_identity.py            # NEW: FR-009 / FR-010 / FR-021 — $TMUX comma-split; $TMUX_PANE %N regex; output_malformed; not_in_tmux; cross-check classifier against fake list_panes rows
│   ├── test_doctor_render.py                 # NEW: FR-013 / FR-024 / FR-028 — TSV row formatting; truncation appends "…" without splitting multi-byte UTF-8; NUL / C0 stripping; no AGENTTOWER_SOCKET leak in error path
│   ├── test_doctor_json_contract.py          # NEW: FR-014 — canonical JSON envelope shape (summary + checks); stable check codes; stable status tokens (pass/warn/fail/info); per-check actionable_message only on non-pass
│   ├── test_doctor_exit_codes.py             # NEW: FR-018 — closed-set mapping 0/1/2/3/5 across every per-check status pattern; reserved 4 never emitted
│   └── test_path_sanitize.py                 # NEW: FR-021 / FR-028 — 2048 (details) and 4096 (env value) caps; NUL strip; C0 strip; multi-byte UTF-8 boundary preservation
└── integration/
    ├── test_cli_config_doctor_healthy.py             # NEW: US2 AS1 + US3 AS1 — every check pass; cgroup→unique_match; exit 0
    ├── test_cli_config_doctor_daemon_down.py         # NEW: US1 AS4 + US2 AS2 + SC-004 — daemon down ⇒ socket_reachable / daemon_status fail, identity + tmux still run, exit non-zero, no raw errno text (FR-024)
    ├── test_cli_config_doctor_host_context.py        # NEW: US2 AS3 — host shell ⇒ container check is host_context (not fail); tmux is pass or not_in_tmux
    ├── test_cli_config_doctor_pane_match.py          # NEW: US2 AS4 + US3 AS5 — pane_match when $TMUX/$TMUX_PANE align with FEAT-004 row; pane_unknown_to_daemon when they do not
    ├── test_cli_config_doctor_json.py                # NEW: US2 AS5 + SC-005 — canonical JSON across healthy + every degraded path; summary.exit_code matches CLI exit; --json suppresses incidental stderr
    ├── test_cli_config_doctor_short_circuit.py       # NEW: FR-027 + SC-003 — every required check runs even when one fails; 500 ms wall-clock budget against healthy daemon
    ├── test_cli_config_paths_socket_source.py        # NEW: FR-019 — extra SOCKET_SOURCE=<token> line appended; existing FEAT-001 KEY=value lines unchanged byte-for-byte; new line is last
    ├── test_cli_in_container_status.py               # NEW: US1 AS1 + SC-001 — simulated in-container env returns same eight-key status payload as host CLI
    ├── test_cli_in_container_socket_override.py      # NEW: US1 AS2 — AGENTTOWER_SOCKET wins over both host and mounted defaults; resolved source = env_override
    ├── test_cli_no_socket_mount.py                   # NEW: US1 AS4 + edge case "default mounted path missing" — exit 2 with the existing FEAT-002 daemon-unavailable message preserved byte-for-byte
    ├── test_cli_in_container_unsupported_signals.py  # NEW: edge cases — privileged container with empty /proc/self/cgroup, --network host hostname collision, multi_match, NUL-byte env, broken socket symlink, regular file at socket path
    ├── test_cli_doctor_identity_hostname.py          # NEW: US3 AS2 — empty cgroup + hostname matches short-prefix; source=hostname
    ├── test_cli_doctor_tmux_unset.py                 # NEW: US3 AS4 — $TMUX unset → not_in_tmux (info, not fail)
    ├── test_feat005_backcompat.py                    # NEW: SC-006 / SC-007 — every FEAT-001..004 CLI command produces byte-identical output on the host; no existing socket method gains a code or shape
    ├── test_feat005_no_real_container.py             # NEW: SC-009 — parallel to test_feat004_no_network.py and test_cli_scan_panes_no_real_docker.py; asserts no docker, tmux, container-runtime, or unexpected subprocess is spawned during the FEAT-005 test session; also asserts no AF_INET/AF_INET6 socket is opened
    └── test_feat005_proc_root_unset_in_prod.py       # NEW: FR-025 — production-binary check that AGENTTOWER_TEST_PROC_ROOT is unset (or refused) when not in the test harness
```

**Structure Decision**: Keep the FEAT-001 / FEAT-002 / FEAT-003 /
FEAT-004 single-project layout. The new `config_doctor/` package
mirrors the Protocol-plus-pure-helper split established by
FEAT-003's `docker/` and FEAT-004's `tmux/` packages: `runner.py`
orchestrates, `checks.py` holds the closed-set per-check functions,
`render.py` owns dual-output formatting, and four narrow helpers
(`socket_resolve.py`, `runtime_detect.py`, `identity.py`,
`tmux_identity.py`) keep each FR's logic in one testable unit.
`sanitize.py` is a single-source-of-truth for FR-021 / FR-028
bounds and is reused by every check that emits text. `paths.py`
gains a `(path, source)` resolver but keeps its existing
`Paths.socket` field unchanged so every FEAT-001 / FEAT-002 reader
continues to work without modification. `cli.py` gets two surgical
edits — the new `config doctor` subparser and one new line on
`config paths` — and nothing else in `cli.py` changes its byte
output (FR-005, SC-007). `socket_api/client.py` gets exactly one
additive change (a `.kind` attribute on `DaemonUnavailable`) so the
doctor can map to FR-016 sub-codes without parsing message strings;
existing message text is unchanged byte-for-byte. FR-022's
no-new-socket-method clause is enforced by the absence of any edit
to `socket_api/methods.py`, `socket_api/server.py`, or
`socket_api/errors.py`.

## Complexity Tracking

> No constitutional violations to justify. This section is intentionally empty.
