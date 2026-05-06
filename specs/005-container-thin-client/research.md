# Phase 0 Research: Container-Local Thin Client Connectivity

**Branch**: `005-container-thin-client` | **Date**: 2026-05-06

This document records the design decisions made during Phase 0 of
the plan. Each decision answers a `NEEDS CLARIFICATION` (none
survived spec writing — the spec is unusually concrete) or pins a
downstream-affecting choice that the plan summary references.
FEAT-005 inherits FEAT-002's socket-client behavior, FEAT-003's
container threat model, and FEAT-004's sanitization policy; this
document only records what is *added* by FEAT-005.

---

## R-001 — Socket-path resolution precedence and validator shape

**Decision**: A pure function
`resolve_socket_path(env, host_paths) -> ResolvedSocket(path,
source)` runs at every CLI invocation. Priority:

1. `AGENTTOWER_SOCKET`, when set and valid → `source = "env_override"`.
2. Mounted-default `/run/agenttower/agenttowerd.sock`, only when
   container-runtime detection (R-003) fires AND the path resolves
   to a Unix socket → `source = "mounted_default"`.
3. FEAT-001 host default (`Paths.socket`) → `source = "host_default"`.

Every CLI command that opens the socket calls this resolver before
constructing the FEAT-002 client; the resolved `(path, source)` is
also surfaced by `agenttower config paths` (FR-019) and by the
doctor's `socket_resolved` check (FR-015).

**Validator (FR-002, edge cases 1 and 2)**: when `AGENTTOWER_SOCKET`
is set, the value MUST be:

- non-empty (after `.strip()`),
- absolute (`os.path.isabs(value)` is true),
- free of NUL bytes,
- pointing at a path whose target (after **exactly one**
  `os.readlink` follow) satisfies `stat.S_ISSOCK(st_mode)`.

Invalid values exit `1` with the literal message
`error: AGENTTOWER_SOCKET must be an absolute path to a Unix
socket: <reason>` and the CLI MUST NOT silently fall back to a
default. Pre-flight rejection runs entirely in-process before any
socket syscall, so the SC-002 50 ms budget is comfortable.

**Rationale**:
- Pinned by FR-001 / FR-002. The `(path, source)` pair lets
  `config paths` and `config doctor` print the resolution provenance
  without re-running detection.
- Single symlink follow keeps the validator predictable on
  bind-mount targets (some Docker setups mount via a symlinked
  parent) without inviting symlink-loop attacks. A second-level
  `os.path.realpath` is rejected as YAGNI.

**Alternatives considered**:
- Resolve in `cli.py` only: scattered logic, hard to unit-test.
  Rejected.
- Always check for the mounted-default first: would change FEAT-001
  / FEAT-002 / FEAT-003 / FEAT-004 host behavior because the path
  exists on some Docker-host workstations. Rejected (FR-003).

---

## R-002 — Mounted-default path is `/run/agenttower/agenttowerd.sock`

**Decision**: The MVP in-container default mounted socket path is
`/run/agenttower/agenttowerd.sock`. Bench containers that mount the
socket elsewhere set `AGENTTOWER_SOCKET` explicitly. The path is a
bind-mount target only; FEAT-005 introduces no in-container disk
write to it. The mounted path is *only* consulted when
container-runtime detection fires (R-003); on the host the path is
ignored even if it happens to exist.

**Rationale**:
- Resolves the architecture.md §25 open question for MVP without
  amending the doc.
- `/run/` is the canonical tmpfs mount point on Linux and matches
  systemd / FHS conventions; bench images already write to it.
- Mode bits (`0600`, host user only) are inherited from the host
  socket file the bind-mount targets — FEAT-005 adds no new
  permission tier (FR-022, FR-023).

**Alternatives considered**:
- `/var/run/agenttower/agenttowerd.sock`: equivalent on glibc but
  `/var/run` is a compatibility symlink; using `/run` directly
  avoids a redundant readlink.
- `/tmp/agenttowerd.sock`: rejected — `/tmp` is multi-user and the
  socket would be visible to other tenants if a bench image ever
  multiplexed users.

---

## R-003 — Container-runtime detection signal pipeline

**Decision**: Closed-set OR-pipeline over three signals; if any
fires, the runtime context is `container_context(detection_signals)`,
otherwise it is `host_context`:

1. `os.path.exists("/.dockerenv")` (Docker classic marker).
2. `os.path.exists("/run/.containerenv")` (Podman marker).
3. Any line in `/proc/self/cgroup` whose final segment matches the
   regex `(docker|containerd|kubepods|lxc)/`.

None of the three signals requires root or a subprocess. The
pipeline is rooted at `os.environ.get("AGENTTOWER_TEST_PROC_ROOT",
"/")` so test fixtures can substitute a fake `/proc` and `/etc`
without touching the real filesystem.

**Edge case handling (spec edge cases 4, 5, 8)**:
- Privileged container with empty `/proc/self/cgroup` (cgroup
  namespace not isolated): treated as `no_signal` for cgroup; the
  fallback proceeds to `/.dockerenv` / `/run/.containerenv`. If
  none of the three fires, the runtime context is `host_context`
  and the in-container default mounted path is ignored entirely.
- `--network host` with `/etc/hostname` equal to the host
  hostname: detection still fires correctly because `/.dockerenv`
  is independent of network mode; identity (R-004) handles the
  hostname-collision case by failing the cross-check rather than
  relying on detection.
- Unparseable cgroup file (binary garbage, permission denied):
  treated as `no_signal`; the `IOError` is swallowed, never
  propagated.

**Rationale**:
- Conservative-on-unknown-sandbox by design. A developer who runs
  the CLI under Firejail, Bubblewrap, or systemd-nspawn is treated
  as host context unless they set `AGENTTOWER_SOCKET` explicitly.
- Three signals over four common runtimes (Docker, containerd,
  Kubernetes, LXC) covers the bench-image fleet documented in
  architecture.md §6 without expanding the closed set.

**Alternatives considered**:
- Read `/proc/1/cgroup` instead of `/proc/self/cgroup`: pid 1's
  cgroup is more stable across `unshare(2)` games but matches the
  same patterns in practice; sticking with `self` matches what every
  other runtime detector does (e.g., `is-docker`, `runc`'s
  detection). Rejected as YAGNI.
- Parse `/proc/1/sched` for `init` vs container-pid: rejected;
  fragile across kernel versions.

---

## R-004 — Container identity detection precedence + cross-check classifier

**Decision**: Resolution order (first non-empty wins):

| Step | Signal | Token reported |
| ---- | ------ | --------------- |
| 1 | `AGENTTOWER_CONTAINER_ID` env override (used verbatim as the candidate id) | `env` |
| 2 | All `/proc/self/cgroup` lines whose last segment matches R-003's pattern set are scanned (this includes the cgroup v2 unified-hierarchy `0::/...` line and any per-subsystem cgroup v1 lines); each line's trailing identifier is collected as a candidate. If every matching line yields the same identifier, that identifier is the candidate. If two or more matching lines yield *distinct* identifiers, the cross-check classification is `multi_match` (per FR-007) with every observed identifier surfaced in a structured `details.cgroup_candidates` array, and the doctor MUST NOT pick one arbitrarily (per Clarifications 2026-05-06 in spec.md). | `cgroup` |
| 3 | Contents of `/etc/hostname` (stripped) | `hostname` |
| 4 | Value of `$HOSTNAME` env var | `hostname_env` |

The candidate is then cross-checked against the daemon's
`list_containers` response:

- **Full-id equality** is checked first.
- If no full-id match, **12-character short-id prefix** match is
  attempted.
- If two `containers` rows share the candidate's short prefix,
  classification is `multi_match` and is reported with both
  candidate ids — the CLI MUST NOT auto-pick.

Closed-set outcomes (FR-007):

| Outcome | Meaning |
| ------- | ------- |
| `unique_match` | exactly one `containers` row matches the candidate |
| `multi_match` | more than one row matches the candidate prefix |
| `no_match` | a candidate was produced but no row matches |
| `no_candidate` | every signal returned empty |
| `host_context` | runtime detection (R-003) reported `host_context` AND `AGENTTOWER_CONTAINER_ID` is unset |

`host_context` only fires when *every* signal returned empty AND
runtime detection said host. An empty cgroup with a hostname value
still produces `no_match` or `unique_match`, never `host_context`.

**Edge case handling (spec edge cases 4, 6)**:
- `--network host`: the in-container `/etc/hostname` is the host
  hostname; cross-check returns `no_match` (no FEAT-003 row), not
  a false positive reporting the host as a container.
- Two FEAT-003 rows share the same 12-char short-id prefix:
  classification is `multi_match`, both candidate ids surface in
  the `actionable_message`.

**Rationale**:
- Pinned by FR-006 / FR-007 / FR-008. The cgroup signal is most
  reliable in standard Docker / Podman; hostname is a defensible
  fallback because bench images conventionally set hostname to the
  short-id; `$HOSTNAME` is a final fallback for setups that override
  `/etc/hostname` but leave the env var alone.
- The env override (`AGENTTOWER_CONTAINER_ID`) wins over all of
  them so a developer can pin the answer in unusual setups
  (Firejail, etc.).

---

## R-005 — Tmux self-identity parsing

**Decision**: `$TMUX` is split on the first two commas into
`(socket_path, server_pid, session_id)`. Only `socket_path` is used
in the daemon cross-check (the parsed `server_pid` and `session_id`
are exposed in the doctor row but not used for matching, since
session id can be symbolic and pid is unstable across server
restarts).

`$TMUX_PANE` is matched against the regex `^%[0-9]+$`. Values that
fail the regex (truncated, contain whitespace, contain other chars)
produce `output_malformed` on the `tmux_pane_match` check, with the
parsed values echoed in the row detail.

Cross-check against FEAT-004 `list_panes` filtered by the resolved
container id when known. Closed-set outcomes:

| Outcome | Meaning |
| ------- | ------- |
| `pane_match` | exactly one `panes` row has matching `tmux_socket_path` AND `tmux_pane_id` |
| `pane_unknown_to_daemon` | `$TMUX`/`$TMUX_PANE` parse cleanly but no `panes` row matches |
| `pane_ambiguous` | more than one `panes` row matches |
| `not_in_tmux` | `$TMUX` is unset |
| `output_malformed` | `$TMUX` is set but unparseable, or `$TMUX_PANE` fails the `^%[0-9]+$` regex (propagates from FR-009 / FR-021 parsing failure; surfaced on both `tmux_present` and `tmux_pane_match` without performing the daemon round-trip) |

When `$TMUX` is set but its `socket_path` is unreadable from inside
the container (e.g., the host tmux socket is not bind-mounted), the
doctor reports the parsed values and skips the daemon cross-check;
the cross-check status becomes `pane_unknown_to_daemon` with a
"tmux socket not visible from container" actionable message rather
than crashing (spec edge case 7).

**Rationale**:
- Pinned by FR-009 / FR-010 / FR-011 / FR-021. Pane id only is
  insufficient (`%N` reuses across server restarts; FEAT-004 R-008);
  pairing with `tmux_socket_path` matches the same composite-key
  shape FEAT-004 uses to reconcile panes.
- Parsing `$TMUX_PANE` against a strict regex prevents
  output_malformed from becoming a silent crash path.

**Alternatives considered**:
- Spawn `tmux display-message -p '#S:#W.#P'` to get authoritative
  pane id: rejected — FR-011 forbids any `tmux` subprocess.
- Use only `$TMUX_PANE` for the cross-check: rejected — pane-id
  collisions across sockets break the match.

---

## R-006 — Doctor check order and exit-code mapping

**Decision**: Six checks in fixed order:
`socket_resolved → socket_reachable → daemon_status →
container_identity → tmux_present → tmux_pane_match` (FR-012).
Every check emits exactly one `CheckResult` row on every invocation
(FR-027); the doctor never aborts early and never omits a check
from the output. When an upstream gate has already failed, the
dependent check still emits a row but skips the actual socket
round-trip; the row carries `status=info` with sub-code
`daemon_unavailable` (per Clarifications 2026-05-06 in spec.md).
This honours FR-014's "every closed-set check appears in the JSON
contract" promise without burning the SC-003 500 ms wall-clock
budget on round-trips that cannot succeed.

Exit-code mapping mirrors FEAT-002 / FEAT-003 exactly:

| Pattern | Exit code |
| ------- | --------- |
| Every required check is `pass` or `info` | `0` |
| Pre-flight failure (FEAT-001 not initialized on host context; malformed `AGENTTOWER_SOCKET`) | `1` |
| `socket_reachable` is `fail` with sub-code `socket_missing` / `connection_refused` / `connect_timeout` | `2` |
| `socket_reachable` is `pass` but `daemon_status` is `fail` with closed-set semantic sub-code `daemon_error` (FEAT-002 `DaemonError` envelope) or `schema_version_newer` (R-010, daemon ahead of CLI). `socket_reachable` is **transport-only**: it reports `pass` whenever the daemon returns any well-formed frame, including a structured `DaemonError`; payload semantics are owned by `daemon_status`. | `3` |
| Round-trip ok and required checks pass, but at least one non-required check is `fail` (e.g., `pane_unknown_to_daemon` after a successful socket+daemon path) | `5` |
| Internal CLI error (uncaught exception in CLI dispatch) | `4` (reserved per FEAT-002, never produced deliberately) |

`info` outcomes (`host_context`, `not_in_tmux` on the host) never
push the exit code above `0` on their own. `pass`/`info` mix with
`warn` produces `0`; only `fail` on a required check changes the
exit class.

**Required vs non-required**:

- **Required** for non-degraded exit: `socket_resolved`,
  `socket_reachable`, `daemon_status`.
- **Non-required** (their `fail` produces exit `5` rather than
  `2`/`3`): `container_identity`, `tmux_present`,
  `tmux_pane_match`.

**Rationale**:
- Pinned by FR-018. Mirroring FEAT-002 / FEAT-003 exit codes lets
  shell scripts treat doctor's exit code with the same logic they
  already use for `agenttower status`.
- The required vs non-required split matches the spec's
  US2 AS1 vs US2 AS2 narrative: a failed identity or pane match
  should not mask a successful daemon round-trip in scripts that
  only check exit codes.

---

## R-007 — Doctor JSON contract shape

**Decision**: One canonical JSON object per invocation, on stdout,
with no incidental stderr lines when `--json` is set:

```json
{
  "summary": {
    "exit_code": 0,
    "total": 6,
    "passed": 6,
    "warned": 0,
    "failed": 0,
    "info": 0
  },
  "checks": {
    "socket_resolved":   {"status": "pass", "source": "env_override",   "details": "/run/agenttower/agenttowerd.sock"},
    "socket_reachable":  {"status": "pass", "source": "round_trip",     "details": "daemon_version=0.5.0 schema_version=3"},
    "daemon_status":     {"status": "pass", "source": "schema_check",   "details": "schema_version=3 (cli supports 3)"},
    "container_identity":{"status": "pass", "source": "cgroup",         "details": "unique_match: <container-id> (<name>)"},
    "tmux_present":      {"status": "pass", "source": "env",            "details": "$TMUX=/tmp/tmux-1000/default,12345,$0"},
    "tmux_pane_match":   {"status": "pass", "source": "list_panes",     "details": "pane_match: %0 in <container-id>:default:main:0.0"}
  }
}
```

`status ∈ {pass, warn, fail, info}`. Non-pass rows include an
additional `actionable_message` field. Per-check sub-codes (FR-007,
FR-010, FR-016, FR-017) are stable across releases; new check codes
or sub-codes MAY be added but never renamed (breaking-change rule).

**Rationale**:
- Pinned by FR-014. Closed-set keys + closed-set status tokens make
  the JSON forward-compatible without versioning the schema.
- Embedding `summary.exit_code` keeps `--json` self-contained for
  scripts that pipe the output without checking `$?`.
- Adding `source` to every row (rather than only on non-pass)
  matches the architecture doc's preference for self-documenting
  output.

**Alternatives considered**:
- Array of `{check, status, ...}` objects: rejected because keyed
  access on `checks.socket_resolved` is friendlier for `jq`.
- Embed full `--json` payload from the daemon's `status` reply:
  rejected — duplicates information already on `daemon_status` row
  and inflates the response.

---

## R-008 — Sanitization and truncation policy

**Decision**: A single `sanitize_text(value, max_length)` helper in
`config_doctor/sanitize.py`:

1. Drops NUL bytes (`\x00`) entirely.
2. Drops every byte in the C0 control range
   (`\x01`–`\x08`, `\x0b`–`\x1f`, `\x7f`).
3. Replaces every `\t` and `\n` in doctor row text with a single
   space (so the TSV output stays one row per check).
4. Truncates the result to `max_length` *characters* (Python `str`
   slicing is character-aware, not byte-aware, so multi-byte UTF-8
   never splits).
5. If truncation occurred, appends a single `…` (U+2026).

Per-field caps:

| Field | Cap |
| ----- | --- |
| Untrusted env values (`AGENTTOWER_SOCKET`, `AGENTTOWER_CONTAINER_ID`, `$TMUX`, `$TMUX_PANE`, `$HOSTNAME`) | 4096 |
| Untrusted file contents (`/etc/hostname`, single `/proc/self/cgroup` line) | 4096 |
| Doctor row `details` | 2048 |
| Doctor row `actionable_message` | 2048 |

**Rationale**:
- Mirrors FEAT-004 R-009 verbatim. Stripping C0 control bytes
  prevents terminal-control-byte injection through pane titles,
  cgroup contents, or env values into the operator's terminal when
  they read doctor output.
- Character-based truncation (vs byte-based) keeps the multi-byte
  UTF-8 invariant without a `unicodedata` round-trip.

**Alternatives considered**:
- Reject the value on truncation: rejected; FR-021 / FR-028 require
  truncation, not rejection.
- No sanitization, rely on JSON encoder: rejected — JSON does not
  strip C0 control bytes.

---

## R-009 — Closed-set sub-codes for `socket_reachable` (no leak policy)

**Decision**: `socket_reachable` is **transport-only** per
Clarifications 2026-05-06: it reports `pass` whenever the daemon
returns *any* well-formed frame, including a structured
`DaemonError` envelope. Semantic payload inspection (including
`DaemonError` recognition and the `schema_version` comparison) is
owned by `daemon_status` (FR-017, R-010). The closed sub-code set
below is therefore strictly transport-level and is never extended
to cover daemon-side semantic failures. Doctor's `socket_reachable`
failure modes are mapped from `socket_api/client.py`'s exception
types onto a closed sub-code set:

| Sub-code | Underlying signal in `client.py` |
| -------- | -------------------------------- |
| `socket_missing` | `FileNotFoundError` from `_connect_via_chdir` (path's parent missing or basename absent) |
| `socket_not_unix` | Pre-flight `S_ISSOCK` check on the resolved path fails (file exists but is regular file / dir / symlink-to-non-socket) |
| `connection_refused` | `ConnectionRefusedError` from `_connect_via_chdir` |
| `permission_denied` | `OSError` with `errno == EACCES` from `_connect_via_chdir` |
| `connect_timeout` | `TimeoutError` / `socket.timeout` on connect or read |
| `protocol_error` | `UnicodeDecodeError`, `json.JSONDecodeError`, malformed envelope, or non-dict result |

**Implementation seam**: `socket_api/client.py` is extended (additive
only) with a `.kind` attribute on `DaemonUnavailable`. The doctor
catches `DaemonUnavailable` once and dispatches on `.kind` instead
of parsing the message string. Existing message text is unchanged
byte-for-byte so FEAT-002 / FEAT-003 / FEAT-004 callers keep their
exact stderr output.

**No-leak policy (FR-024)**: Raw `socket(2)` / `connect(2)` errno
text MUST NOT appear in stderr or `--json`. The CLI translates the
`.kind` into one of the sub-codes above plus a one-line
`actionable_message` bounded by R-008. The wrapped exception's
`__cause__` is not formatted into output. The doctor's stderr in
the daemon-down case prints only `socket_reachable\tfail\t<sub-code>`
and the indented actionable line; no `[Errno 111] Connection
refused` text leaks.

**Rationale**:
- Pinned by FR-016 / FR-024. Mirrors FEAT-003 R-014 / FEAT-004 R-011
  (closed error-code asymmetry).
- A `.kind` attribute on the existing exception type is the smallest
  change that lets the doctor avoid string-matching `client.py`'s
  message format.

**Alternatives considered**:
- Subclass `DaemonUnavailable` per sub-code: rejected — too many
  classes for a closed-set; introspection on `.kind` is cleaner.
- Parse the message string: rejected — fragile and the message text
  is part of FEAT-002's stderr contract.

---

## R-010 — Schema-version comparison policy

**Decision**: Doctor's `daemon_status` check echoes the daemon's
`schema_version` (returned by FEAT-002 `status`). The CLI build pins
a `MAX_SUPPORTED_SCHEMA_VERSION` constant (currently `3`; bumped
each schema migration).

| Comparison | Status | Sub-code | Exit class |
| ---------- | ------ | -------- | ---------- |
| `daemon == cli`                                | `pass` | (none)                     | `0` |
| `daemon < cli`                                 | `warn` | `schema_version_older`     | `0` (forward-compatible CLI keeps working) |
| `daemon > cli`                                 | `fail` | `schema_version_newer`     | `3` (daemon round-trip succeeded but CLI cannot serve safely; per FR-018 layering rule, this is a `daemon_status` semantic fail) |
| payload is a structured `DaemonError` envelope | `fail` | `daemon_error`             | `3` (transport ok, daemon-side semantic problem; per Clarifications 2026-05-06 in spec.md) |
| `socket_reachable` was not `pass`              | `info` | `daemon_unavailable`       | (no exit-class contribution; round-trip skipped per FR-027 clarification) |

The `schema_version_newer` actionable message names the build the
operator should upgrade to. The `daemon_error` row's
`actionable_message` echoes the daemon-supplied error message after
FR-028 sanitization. Both `daemon_error` and `schema_version_newer`
are required-check fails and therefore both produce exit `3`; this
preserves the layering principle that `socket_reachable` is
transport-only and `daemon_status` owns every daemon-side semantic
outcome.

**Rationale**:
- Pinned by FR-017. Inherits FEAT-003 R-012 forward-compat policy.
- `schema_version_newer` as `fail` rather than `warn` is the
  explicit choice because a CLI that does not understand the schema
  cannot guarantee its `list_containers` / `list_panes` parsing is
  correct.

---

## R-011 — Test seam: `AGENTTOWER_TEST_PROC_ROOT`

**Decision**: A new namespaced env var
`AGENTTOWER_TEST_PROC_ROOT`, when set, is interpreted as a directory
that stands in for `/` for the closed set of read paths used by
FR-020:

- `/.dockerenv`
- `/run/.containerenv`
- `/proc/self/cgroup`
- `/proc/1/cgroup` (defensive; some detection libs read this)
- `/etc/hostname`

All other reads (the resolved socket path, FEAT-001 host paths)
ignore the override. Mirrors FEAT-003's `AGENTTOWER_TEST_DOCKER_FAKE`
and FEAT-004's `AGENTTOWER_TEST_TMUX_FAKE`.

A `tests/integration/test_feat005_proc_root_unset_in_prod.py`
integration test asserts `AGENTTOWER_TEST_PROC_ROOT` is *not* set
when the production binary entry point is invoked outside the test
suite (FR-025), preventing accidental fake-proc activation in
production. A second harness-level test
(`test_feat005_no_real_container.py`) parallels FEAT-004's
`test_feat004_no_network.py` and asserts no `docker`, `tmux`,
container-runtime, or unexpected subprocess is spawned during the
FEAT-005 test session and no AF_INET/AF_INET6 socket is opened.

**Rationale**:
- Integration tests already spawn the daemon as a subprocess
  (FEAT-002 / FEAT-003 / FEAT-004 pattern). Passing the fake `/proc`
  through `os.environ` avoids any import-time monkeypatching across
  process boundaries.
- The hook is `AGENTTOWER_TEST_*`-namespaced so a production
  environment cannot enable it accidentally.

**Alternatives considered**:
- CLI flag (`agenttower --test-proc-root <path>`): rejected — leaks
  a test surface into the production CLI.
- Patch `os.path.exists` / `open` globally: rejected — doesn't work
  across the spawned daemon process.
- One env var that drives all three fakes: rejected — the fixture
  shapes are unrelated; one var per seam keeps each orthogonal.

---

## R-012 — No new socket methods (explicit non-decision)

**Decision**: FEAT-005 reuses the existing socket methods
exclusively:

- FEAT-002 `ping`, `status`, `shutdown`
- FEAT-003 `list_containers`
- FEAT-004 `list_panes`

Doctor cross-checks call `list_containers` once and `list_panes`
once (filtered by resolved container id when known); both are
read-only and acquire no scan mutex on the daemon side. The daemon
dispatch table (`socket_api/methods.py`) is unchanged.

**Rationale**:
- Pinned by FR-022 / FR-026 / FR-029. Recorded as an explicit
  non-decision so a later reviewer cannot reopen it without
  amending the spec.
- Reusing read-only methods means the doctor never contends with a
  running scan; SC-003's 500 ms wall-clock budget is comfortable.

**Alternatives considered**:
- A new `doctor` socket method that bundles `status` +
  `list_containers` + `list_panes` filtered by container id: would
  reduce three round-trips to one, but FR-022 forbids new methods
  in this slice and the latency saving (≤ 100 ms) does not justify
  the API surface. Deferred to a future feature if the cost ever
  matters.
