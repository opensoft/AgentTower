# Phase 1 Data Model: Container-Local Thin Client Connectivity

**Branch**: `005-container-thin-client` | **Date**: 2026-05-06

This document is the canonical reference for FEAT-005 entities and
data flow. Anything here overrides the informal entity descriptions
in spec.md. FEAT-005 introduces **no SQLite schema change**, **no
new tables**, **no new files on disk**, and **no new socket method**;
every entity below is in-memory only and lives for the duration of
one CLI invocation.

---

## 1. Filesystem footprint

FEAT-005 adds **no new files**. Three existing FEAT-001 / FEAT-002 /
FEAT-003 / FEAT-004 paths gain new *read* behavior; nothing is
written.

| Path                                                | Read by FEAT-005 | Written by FEAT-005 |
| --------------------------------------------------- | ---------------- | ------------------- |
| `/.dockerenv`                                       | yes (existence) | no |
| `/run/.containerenv`                                | yes (existence) | no |
| `/proc/self/cgroup`                                 | yes (line scan)  | no |
| `/proc/1/cgroup`                                    | yes (defensive line scan) | no |
| `/etc/hostname`                                     | yes (single read) | no |
| `<RESOLVED_SOCKET>` (env / mounted-default / host-default) | yes (`AF_UNIX` connect; FR-016 round-trip) | no |
| `<HOST_PATHS>.config_file` / `<HOST_PATHS>.state_db` etc. | yes (FEAT-001 paths surface only; through existing `agenttower config paths`) | no |

In-container reads are rooted at
`os.environ.get("AGENTTOWER_TEST_PROC_ROOT", "/")` so test fixtures
substitute a fake root without touching the real filesystem
(R-011).

No SQLite reads at all in FEAT-005 code. The daemon's SQLite reads
for `list_containers` / `list_panes` happen on the daemon side and
are reused as-is (FR-026).

---

## 2. SQLite schema

**No change.** `CURRENT_SCHEMA_VERSION` stays at `3` (the value
FEAT-004 set). FEAT-005 introduces no migration; the daemon does
not write any new row in any table on a `config doctor` invocation
(FR-029).

The `daemon_status` doctor row reports `schema_version` from the
existing FEAT-002 `status` payload (R-010); no FEAT-005 code opens
the SQLite database directly.

---

## 3. Domain entities

All entities below are in-memory dataclasses; no persistence.

### 3.1 `ResolvedSocket` (output of R-001)

```python
@dataclass(frozen=True)
class ResolvedSocket:
    path:   Path                                    # absolute Unix-socket path
    source: Literal["env_override", "mounted_default", "host_default"]
```

Every CLI command that opens the socket calls
`resolve_socket_path(env, host_paths) -> ResolvedSocket` once at
startup. The dataclass is consumed by `socket_api/client.send_request`
(via the `socket_path` parameter), by `agenttower config paths` (the
new `SOCKET_SOURCE=` line; FR-019), and by the doctor's
`socket_resolved` check (FR-015).

### 3.2 `RuntimeContext` (output of R-003)

```python
RuntimeContext = HostContext | ContainerContext

@dataclass(frozen=True)
class HostContext:
    pass

@dataclass(frozen=True)
class ContainerContext:
    detection_signals: tuple[str, ...]   # subset of {"dockerenv", "containerenv", "cgroup"}
```

Produced by `runtime_detect.detect(proc_root) -> RuntimeContext`. Drives
whether the in-container default mounted path is considered (FR-003)
and whether the doctor's container check classifies as `host_context`
when no candidate fires.

### 3.3 `IdentityResolution` (output of R-004)

```python
@dataclass(frozen=True)
class IdentityCandidate:
    candidate:    str                                   # raw candidate id (sanitized)
    signal:       Literal["env", "cgroup", "hostname", "hostname_env"]

@dataclass(frozen=True)
class IdentityResolution:
    candidate:               IdentityCandidate | None       # None when every signal returned empty
    classification:          Literal["unique_match", "multi_match", "no_match", "no_candidate", "host_context"]
    matched_id:              str | None                     # full container id from list_containers when classification == "unique_match"
    matched_name:            str | None                     # container name from list_containers when classification == "unique_match"
    multi_match_ids:         tuple[str, ...]                # both/all matching ids when classification == "multi_match"
    cgroup_candidates:       tuple[str, ...]                # populated only when multi_match was caused by /proc/self/cgroup yielding distinct trailing identifiers across matching lines (FR-006 multi-line rule, Clarifications 2026-05-06); empty tuple otherwise. Surfaced in JSON as details.cgroup_candidates.
    daemon_container_set_empty: bool                        # True when the daemon's list_containers reply was empty (spec edge case 11). Surfaced in JSON as details.daemon_container_set_empty on no_candidate / no_match rows; False when classification == "unique_match" or "multi_match".
```

`classification == "host_context"` only when both:
- `RuntimeContext` is `HostContext`, AND
- `AGENTTOWER_CONTAINER_ID` is unset.

Otherwise `host_context` is impossible — the resolution falls
through to `no_match` or `no_candidate`.

The `no_containers_known` token referenced in spec edge case 11 is
**not** a sub-code; the empty-`list_containers` case is signalled
by `daemon_container_set_empty=True` plus the existing
`no_candidate` / `no_match` classification (per Clarifications
2026-05-06 in spec.md). The closed FR-007 5-token set is not
extended.

### 3.4 `TmuxIdentity` (output of R-005)

```python
@dataclass(frozen=True)
class TmuxIdentity:
    in_tmux:           bool                            # False when $TMUX is unset
    tmux_socket_path:  str | None                      # parsed first comma field of $TMUX
    server_pid:        str | None                      # parsed second comma field (raw, not used in match)
    session_id:        str | None                      # parsed third comma field (raw, not used in match)
    tmux_pane_id:      str | None                      # raw $TMUX_PANE
    pane_id_valid:     bool                            # True iff tmux_pane_id matches ^%[0-9]+$
    classification:    Literal["pane_match", "pane_unknown_to_daemon", "pane_ambiguous", "not_in_tmux", "output_malformed"]
    matched_pane:      MatchedPane | None              # populated only on "pane_match"
    ambiguous_panes:   tuple[MatchedPane, ...]         # populated only on "pane_ambiguous"

@dataclass(frozen=True)
class MatchedPane:
    container_id:        str
    tmux_socket_path:    str
    tmux_session_name:   str
    tmux_window_index:   int
    tmux_pane_index:     int
    tmux_pane_id:        str
```

`output_malformed` fires when `$TMUX` is set but unparseable, or
when `$TMUX_PANE` fails the `^%[0-9]+$` regex (FR-021).

### 3.5 `CheckResult` and `DoctorReport`

```python
CheckCode = Literal[
    "socket_resolved",
    "socket_reachable",
    "daemon_status",
    "container_identity",
    "tmux_present",
    "tmux_pane_match",
]

CheckStatus = Literal["pass", "warn", "fail", "info"]

@dataclass(frozen=True)
class CheckResult:
    code:               CheckCode
    status:             CheckStatus
    source:             str | None                  # closed-set per check (e.g., "env_override", "round_trip", "schema_check", "cgroup", "hostname", "list_panes")
    details:            str                         # sanitized + bounded to 2048 chars
    actionable_message: str | None                  # sanitized + bounded to 2048 chars; only populated when status != "pass"
    sub_code:           str | None                  # closed-set per check (e.g., FR-016 socket_reachable sub-codes; FR-007 identity outcomes; FR-010 tmux outcomes; FR-017 schema sub-codes)

@dataclass(frozen=True)
class DoctorReport:
    checks:    tuple[CheckResult, ...]              # always exactly 6 entries, in FR-012 order
    exit_code: Literal[0, 1, 2, 3, 4, 5]            # computed from checks per R-006
```

`source` is required for `pass` rows (it documents *how* the check
passed) and optional for non-pass rows. `sub_code` is `None` on
`pass`/`info` and is one of the closed-set sub-codes from R-006 /
R-009 / R-010 / FR-007 / FR-010 on `warn`/`fail`.

### 3.6 `DoctorJSONEnvelope` (output of `--json`)

```python
@dataclass(frozen=True)
class DoctorJSONSummary:
    exit_code: int
    total:     int
    passed:    int
    warned:    int
    failed:    int
    info:      int

@dataclass(frozen=True)
class DoctorJSONCheck:
    status:             CheckStatus
    source:             str | None
    details:            str
    actionable_message: str | None        # absent (key omitted) when None
    sub_code:           str | None        # absent (key omitted) when None

@dataclass(frozen=True)
class DoctorJSONEnvelope:
    summary: DoctorJSONSummary
    checks:  dict[CheckCode, DoctorJSONCheck]
```

Serialized verbatim as one JSON object per invocation
(R-007, FR-014). Field order in `summary` is fixed; `checks` is a
JSON object keyed by closed-set check code.

---

## 4. State transitions

FEAT-005 has **no persistent state** to transition. The only
in-memory state machines are:

### 4.1 `ResolvedSocket.source` selection

```text
                (AGENTTOWER_SOCKET set & valid)
   start ──────────────────────────────────────────►  source = "env_override"
        │
        │ (AGENTTOWER_SOCKET unset OR invalid → exit 1)
        │
        ▼
        (RuntimeContext == ContainerContext
         AND /run/agenttower/agenttowerd.sock S_ISSOCK)
   ─────────────────────────────────────────────────►  source = "mounted_default"
        │
        │ (otherwise)
        ▼
   ─────────────────────────────────────────────────►  source = "host_default"
```

`AGENTTOWER_SOCKET` set but invalid never falls through; it produces
exit `1` per FR-002 (R-001).

### 4.2 `IdentityResolution.classification` selection

```text
   AGENTTOWER_CONTAINER_ID set    ──►  IdentityCandidate(signal="env")
         │
         ▼
   /proc/self/cgroup parses        ──►  IdentityCandidate(signal="cgroup")
         │
         ▼
   /etc/hostname non-empty         ──►  IdentityCandidate(signal="hostname")
         │
         ▼
   $HOSTNAME non-empty             ──►  IdentityCandidate(signal="hostname_env")
         │
         ▼
   no candidate                    ──►  classification = (host_context if RuntimeContext == HostContext else no_candidate)

   (with candidate, cross-check list_containers)
   exactly one full-id match            ──►  unique_match
   exactly one short-id-prefix match    ──►  unique_match
   more than one match                  ──►  multi_match
   zero matches                         ──►  no_match
```

### 4.3 `DoctorReport.exit_code` computation

Walks the six `CheckResult`s in order and applies R-006's mapping
table. Pre-flight failures short-circuit to `1` *before* the
`DoctorReport` is constructed: `socket_resolve.py` raises
`SocketPathInvalid` (the FR-002 validator), which propagates out of
`run_doctor` and is caught by the CLI handler in `cli.py` (the
`SocketPathInvalid` → stderr + exit `1` translation lives there,
not in `runner.py`).

---

## 5. Reconciliation algorithm

Not applicable. FEAT-005 introduces no reconciliation because no
durable state is mutated. The closest analogue is the pure
identity / tmux cross-check classifier in §3.3 / §3.4, which is
implemented as two pure functions:

```python
def classify_identity(
    candidate:         IdentityCandidate | None,
    runtime_context:   RuntimeContext,
    list_containers:   tuple[ContainerSummaryRow, ...],
) -> IdentityResolution: ...

def classify_tmux(
    parsed_tmux:    ParsedTmuxEnv,             # parsed $TMUX + $TMUX_PANE
    list_panes:     tuple[PaneRow, ...],       # filtered by resolved container id when known
) -> TmuxIdentity: ...
```

`ContainerSummaryRow` and `PaneRow` are the existing FEAT-003 /
FEAT-004 socket-response shapes; FEAT-005 reads them as-is and does
not extend them (FR-026).

---

## 6. JSON serialization at the socket boundary

FEAT-005 introduces no new socket method (FR-022). Doctor's three
round-trips reuse existing methods:

| Round-trip | Method | Purpose |
| ---------- | ------ | ------- |
| 1 | FEAT-002 `status` | drives `socket_reachable` + `daemon_status` (R-009, R-010) |
| 2 | FEAT-003 `list_containers` | drives `container_identity` cross-check (R-004) |
| 3 | FEAT-004 `list_panes` | drives `tmux_pane_match` cross-check (R-005) |

Round-trips 2 and 3 are skipped when the prior check made them
moot (e.g., if `socket_reachable` fails, `list_containers` is not
called). The doctor still emits a `CheckResult` for the skipped
checks: `container_identity` becomes `info` with sub-code
`daemon_unavailable` and an actionable message; `tmux_pane_match`
becomes `info` with sub-code `daemon_unavailable` or
`not_in_tmux`. This preserves FR-027 ("every check runs every
invocation") in spirit — every check produces a row — while not
attempting impossible round-trips.

---

## 7. Migration & backward compatibility

| FEAT | Concern | Resolution |
| ---- | ------- | ---------- |
| FEAT-001 | `agenttower config init` byte-for-byte stable | Unchanged. FEAT-005 adds no new config block; the loader has no `[doctor]` or `[paths]` section in MVP. |
| FEAT-001 | `agenttower config paths` line shape | One additional trailing line `SOCKET_SOURCE=<env_override|mounted_default|host_default>` (FR-019). Existing `KEY=value` lines unchanged byte-for-byte; new line is last. |
| FEAT-002 | `agenttower status` schema | Unchanged. `schema_version` field still reports the FEAT-004 value (`3`); FEAT-005 reads it but does not bump it. |
| FEAT-002 | `ping` / `status` / `shutdown` envelopes | Unchanged. Doctor's `socket_reachable` and `daemon_status` checks reuse the FEAT-002 client and `status` method without modification. |
| FEAT-002 | `socket_api/client.py` exception messages | Unchanged byte-for-byte. The new `.kind` attribute on `DaemonUnavailable` is additive only (R-009); `str(exc)` returns the same text as before. |
| FEAT-003 | `containers` / `container_scans` schema | UNCHANGED (FR-026). FEAT-005 reads `list_containers` only, never opens the SQLite database directly. |
| FEAT-003 | `scan_containers` / `list_containers` socket methods | UNCHANGED. The doctor's cross-check is a single read-only `list_containers` call. |
| FEAT-004 | `panes` / `pane_scans` schema | UNCHANGED (FR-026). FEAT-005 reads `list_panes` only. |
| FEAT-004 | `scan_panes` / `list_panes` socket methods | UNCHANGED. The doctor's tmux cross-check is a single read-only `list_panes` call, optionally filtered by `--container <id>`. |
| FEAT-001..004 | Host CLI behavior with no container context | Bytewise unchanged for every subcommand the existing test suite covers (FR-005, SC-006, SC-007). The two additive surfaces (`config doctor` subcommand, one new line on `config paths`) do not modify any existing command's stdout, stderr, or exit code. |

A daemon running the FEAT-005 build against a v3 SQLite database
applies no migration. A daemon built before FEAT-005 against a v3
database opens cleanly; FEAT-005 adds no schema state. The CLI
build pins `MAX_SUPPORTED_SCHEMA_VERSION = 3`; bumping it is a
FEAT-006 concern and not a FEAT-005 concern.
