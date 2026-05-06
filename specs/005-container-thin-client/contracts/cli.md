# CLI Contracts: Container-Local Thin Client Connectivity

**Branch**: `005-container-thin-client` | **Date**: 2026-05-06

This document is the authoritative contract for the two additive
CLI surfaces FEAT-005 introduces. It supplements `spec.md`
FR-013, FR-014, FR-015, FR-016, FR-017, FR-018, FR-019, and
FR-027. Anything here overrides informal CLI descriptions in
spec.md.

FEAT-001 / FEAT-002 / FEAT-003 / FEAT-004 CLI surfaces are
unchanged byte-for-byte (FR-005, SC-006, SC-007).

---

## C-CLI-501 — `agenttower config doctor`

### Synopsis

```text
agenttower config doctor [--json]
```

### Behavior

Runs the closed-set checks
`socket_resolved → socket_reachable → daemon_status →
container_identity → tmux_present → tmux_pane_match` in fixed order
(FR-012). Every check emits exactly one `CheckResult` row on every
invocation (FR-027) — the doctor never aborts early and never omits
a check from the output. When an upstream gate fails (e.g.,
`socket_reachable` fails before `daemon_status`), the dependent
check still emits its row but skips the actual socket round-trip;
the row carries `status=info` with sub-code `daemon_unavailable`
(see the `Per-check sub-codes` table below and Clarifications
2026-05-06 in spec.md). Writes nothing to disk (FR-029).

Doctor itself is a pure read-only diagnostic; the only side effect
is the existing FEAT-002 `status` round-trip the host daemon
already records in its lifecycle log when the round-trip succeeds
(no new lifecycle log token is introduced).

### Exit codes (FR-018)

| Pattern | Exit code |
| ------- | --------- |
| Every required check is `pass` or `info`                                                   | `0` |
| Pre-flight failure (FEAT-001 not initialized on host context; malformed `AGENTTOWER_SOCKET`) | `1` |
| `socket_reachable` is `fail` with sub-code `socket_missing` / `connection_refused` / `connect_timeout` | `2` |
| `socket_reachable` is `pass` but `daemon_status` is `fail` (sub-codes `daemon_error` — FEAT-002 `DaemonError` envelope — or `schema_version_newer` — daemon ahead of CLI per R-010) | `3` |
| Internal CLI error (uncaught exception in CLI dispatch)                                    | `4` (reserved per FEAT-002, never produced deliberately) |
| Round-trip ok and required checks pass, but at least one non-required check is `fail`      | `5` |

Required-for-non-degraded checks: `socket_resolved`,
`socket_reachable`, `daemon_status`. Non-required:
`container_identity`, `tmux_present`, `tmux_pane_match`.

### Default output (FR-013)

One TSV row per check, written to stdout, followed by a single
`summary` line:

```text
<check>\t<status>\t<one-line-detail>
[indented actionable_message line(s) for non-pass rows]
...
summary\t<exit_code>\t<n_pass>/<n_total> checks passed
```

Every line is sanitized of NUL bytes and C0 control bytes; embedded
`\t` and `\n` are replaced with single spaces; lines are bounded to
2048 chars and truncated with a trailing `…` when needed (FR-013,
FR-021, FR-028). No incidental stderr lines when running in default
mode either; all CLI output is on stdout, except for the standard
FEAT-002 daemon-unavailable stderr line that the doctor itself does
not produce.

`status ∈ {pass, warn, fail, info}`. The same canonical token set
appears in `--json` output (FR-014).

#### Worked example — healthy

```text
$ agenttower config doctor
socket_resolved      pass    /run/agenttower/agenttowerd.sock (env_override)
socket_reachable     pass    daemon_version=0.5.0 schema_version=3
daemon_status        pass    schema_version=3 (cli supports 3)
container_identity   pass    unique_match: 1234abcd5678... (py-bench)
tmux_present         pass    $TMUX=/tmp/tmux-1000/default,12345,$0
tmux_pane_match      pass    pane_match: %0 in py-bench:default:main:0.0
summary              0       6/6 checks passed
```

#### Worked example — daemon down

```text
$ agenttower config doctor
socket_resolved      pass    /run/agenttower/agenttowerd.sock (mounted_default)
socket_reachable     fail    socket_missing: /run/agenttower/agenttowerd.sock
    try `agenttower ensure-daemon` from the host
daemon_status        info    daemon_unavailable
container_identity   info    daemon_unavailable: candidate=1234abcd5678... (cgroup)
    run `agenttower scan --containers` from the host once the daemon is up
tmux_present         pass    $TMUX=/tmp/tmux-1000/default,12345,$0
tmux_pane_match      info    daemon_unavailable
summary              2       1/6 checks passed
```

### `--json` output (FR-014)

Exactly one canonical JSON object on stdout per invocation. No
incidental stderr lines (FR-014, edge case re. JSON purity). Schema:

```json
{
  "summary": {
    "exit_code": <int>,
    "total":     <int>,
    "passed":    <int>,
    "warned":    <int>,
    "failed":    <int>,
    "info":      <int>
  },
  "checks": {
    "<check_code>": {
      "status":             "<pass|warn|fail|info>",
      "source":             "<closed-set per check, optional>",
      "details":            "<sanitized + bounded to 2048 chars>",
      "sub_code":           "<closed-set per check, present when status != pass>",
      "actionable_message": "<sanitized + bounded to 2048 chars, present when status != pass>"
    }
  }
}
```

`checks` is keyed by closed-set check code (`socket_resolved`,
`socket_reachable`, `daemon_status`, `container_identity`,
`tmux_present`, `tmux_pane_match`); the keys and tokens are stable
across releases. New check codes or sub-codes MAY be added; renaming
or repurposing existing ones is a breaking change deferred to a
future major version.

### Per-check sub-codes

#### `socket_resolved`

| Source token | Status | Sub-code | When |
| ------------ | ------ | -------- | ---- |
| `env_override`     | `pass` | (none)            | `AGENTTOWER_SOCKET` set, valid, points at a Unix socket |
| `mounted_default`  | `pass` | (none)            | runtime context is container AND mounted-default exists as a Unix socket |
| `host_default`     | `pass` | (none)            | runtime context is host (or mounted-default missing) |
| (any)              | `fail` | `path_invalid`    | `AGENTTOWER_SOCKET` set but malformed (relative, NUL, empty); pre-flight exit `1` |
| (any)              | `fail` | `not_a_socket`    | resolved path exists but is not `S_ISSOCK` (regular file, dir, broken symlink) |

#### `socket_reachable` (FR-016)

| Sub-code | Underlying signal |
| -------- | ----------------- |
| `socket_missing`     | `FileNotFoundError` from `_connect_via_chdir` |
| `socket_not_unix`    | Pre-flight `S_ISSOCK` check fails |
| `connection_refused` | `ConnectionRefusedError` from `_connect_via_chdir` |
| `permission_denied`  | `OSError(EACCES)` |
| `connect_timeout`    | `TimeoutError` / `socket.timeout` |
| `protocol_error`     | `UnicodeDecodeError`, `json.JSONDecodeError`, malformed envelope, non-dict result |

Raw `socket(2)` / `connect(2)` errno text MUST NOT leak to stderr
or `--json` (FR-024). The CLI maps the underlying exception to a
sub-code and a one-line bounded actionable message; the wrapped
exception's `__cause__` is not formatted into output.

#### `daemon_status` (FR-017)

| Sub-code | Status | When |
| -------- | ------ | ---- |
| (none)                    | `pass` | `daemon.schema_version == cli.MAX_SUPPORTED_SCHEMA_VERSION` |
| `schema_version_older`    | `warn` | `daemon.schema_version < cli.MAX_SUPPORTED_SCHEMA_VERSION` (forward-compatible CLI keeps working) |
| `schema_version_newer`    | `fail` | `daemon.schema_version > cli.MAX_SUPPORTED_SCHEMA_VERSION` (CLI cannot serve safely; update CLI build) |
| `daemon_unavailable`      | `info` | `socket_reachable` failed (round-trip never happened) |
| `daemon_error`            | `fail` | round-trip succeeded but daemon returned a structured error (FEAT-002 `DaemonError`) |

#### `container_identity` (FR-006, FR-007)

The closed sub-code set is exactly **five** classification outcomes
plus two transversal states (`output_malformed`,
`daemon_unavailable`). The synonym `not_in_container` is **not** a
sub-code; only `host_context` is emitted (resolved by Clarifications
2026-05-06 in spec.md). The empty-`list_containers` case from
spec edge case 11 is **not** its own sub-code; it surfaces as a
structured `details.daemon_container_set_empty = true` qualifier
attached to the existing `no_candidate` / `no_match` outcome.

| Sub-code | Status | When |
| -------- | ------ | ---- |
| `unique_match`            | `pass` | exactly one `list_containers` row matches the candidate |
| `host_context`            | `info` | runtime context is host AND `AGENTTOWER_CONTAINER_ID` is unset |
| `multi_match`             | `fail` | more than one `list_containers` row matches the candidate prefix; OR `/proc/self/cgroup` has multiple matching lines yielding *distinct* container ids (per FR-006 cgroup multi-line rule); when the latter, the observed candidate ids surface in `details.cgroup_candidates` (array of strings) |
| `no_match`                | `fail` | candidate produced but no row matches; actionable message advises running `agenttower scan --containers` from the host. When `list_containers` returned an empty result, also set `details.daemon_container_set_empty = true` (spec edge case 11) |
| `no_candidate`            | `fail` | every detection signal returned empty inside a container context; actionable message lists tried signals. When `list_containers` returned an empty result, also set `details.daemon_container_set_empty = true` (spec edge case 11) |
| `output_malformed`        | `fail` | candidate value contains data that fails sanitization shape (e.g., NUL byte in `AGENTTOWER_CONTAINER_ID`) |
| `daemon_unavailable`      | `info` | `socket_reachable` failed; round-trip skipped (FR-027 + Clarifications 2026-05-06) |

#### `tmux_present` (FR-009)

| Sub-code | Status | When |
| -------- | ------ | ---- |
| (none)               | `pass` | `$TMUX` parsed cleanly into `(socket_path, server_pid, session_id)` and `$TMUX_PANE` matches `^%[0-9]+$` |
| `not_in_tmux`        | `info` | `$TMUX` is unset |
| `output_malformed`   | `fail` | `$TMUX` set but not parseable, OR `$TMUX_PANE` fails the `%N` regex |

#### `tmux_pane_match` (FR-010)

| Sub-code | Status | When |
| -------- | ------ | ---- |
| `pane_match`              | `pass` | exactly one `list_panes` row has matching `(tmux_socket_path, tmux_pane_id)` |
| `pane_unknown_to_daemon`  | `fail` | `$TMUX`/`$TMUX_PANE` parse cleanly but no `list_panes` row matches; actionable message advises `agenttower scan --panes` from the host |
| `pane_ambiguous`          | `fail` | more than one `list_panes` row matches |
| `not_in_tmux`             | `info` | propagated from `tmux_present` |
| `daemon_unavailable`      | `info` | `socket_reachable` failed; cross-check skipped |

### `AGENTTOWER_SOCKET` validation (FR-002)

When set, the value MUST be:

- non-empty (after `.strip()`),
- absolute (`os.path.isabs(value)` is true),
- free of NUL bytes,
- pointing at a path whose target (after **exactly one**
  `os.readlink` follow) satisfies `stat.S_ISSOCK(st_mode)`.

Invalid values cause the CLI to exit `1` with the literal stderr
message:

```text
error: AGENTTOWER_SOCKET must be an absolute path to a Unix socket: <reason>
```

`<reason>` is one of: `value is empty`, `value is not absolute`,
`value contains NUL byte`, `value does not exist`,
`value is not a Unix socket`. The CLI MUST NOT silently fall back
to a default when the override is set but invalid (FR-002).

The raw `AGENTTOWER_SOCKET` value is sanitized of control bytes and
bounded to 4096 chars before ever being printed in stderr or in the
doctor row's `details` field (FR-015, FR-021, FR-024).

### `--json` and stderr discipline

When `--json` is set, every check's output MUST stay inside the
JSON payload (FR-014, edge case re. JSON purity). The CLI MUST NOT
emit incidental stderr lines (e.g., warnings, deprecation notices).
Pre-flight failures (FR-002) before JSON parsing still print the
plaintext `error: ...` line on stderr and exit `1`; that pre-flight
predates `--json` parsing and is the single documented exception.

---

## C-CLI-502 — `agenttower config paths` (extended)

### Synopsis

```text
agenttower config paths
```

(Unchanged from FEAT-001.)

### Behavior

The existing `KEY=value` line shape is unchanged byte-for-byte
(FR-019, FR-026, SC-007). FEAT-005 adds **exactly one new line** at
the **end** of the output:

```text
SOCKET_SOURCE=<env_override|mounted_default|host_default>
```

The token comes from the `ResolvedSocket.source` of the current CLI
invocation (R-001). FEAT-005 MUST NOT alter any preceding line and
MUST NOT introduce a `--json` mode for `config paths` (FR-019).

#### Worked example — host context

```text
$ agenttower config paths
CONFIG_FILE=/home/brett/.config/opensoft/agenttower/config.toml
STATE_DB=/home/brett/.local/state/opensoft/agenttower/agenttower.sqlite3
EVENTS_FILE=/home/brett/.local/state/opensoft/agenttower/events.jsonl
LOGS_DIR=/home/brett/.local/state/opensoft/agenttower/logs
SOCKET=/home/brett/.local/state/opensoft/agenttower/agenttowerd.sock
CACHE_DIR=/home/brett/.cache/opensoft/agenttower
SOCKET_SOURCE=host_default
```

(The first six lines are byte-identical to the FEAT-001 build's
output for the same `$HOME` — same key order, same casing, same
trailing-newline behavior — only `SOCKET_SOURCE=...` is new and it
is always the last line.)

#### Worked example — container context with override

```text
$ AGENTTOWER_SOCKET=/run/agenttower/agenttowerd.sock agenttower config paths
CONFIG_FILE=/home/brett/.config/opensoft/agenttower/config.toml
STATE_DB=/home/brett/.local/state/opensoft/agenttower/agenttower.sqlite3
EVENTS_FILE=/home/brett/.local/state/opensoft/agenttower/events.jsonl
LOGS_DIR=/home/brett/.local/state/opensoft/agenttower/logs
SOCKET=/run/agenttower/agenttowerd.sock
CACHE_DIR=/home/brett/.cache/opensoft/agenttower
SOCKET_SOURCE=env_override
```

The `SOCKET=` line reflects the resolved value from R-001 (the
existing FEAT-001 line shape carries the `ResolvedSocket.path`);
the new `SOCKET_SOURCE=` line carries the `ResolvedSocket.source`
token. Both are produced by the same resolver invocation. The
six existing `KEY=value` lines are emitted in the order
`Paths` dataclass fields are declared in `src/agenttower/paths.py`
(`config_file`, `state_db`, `events_file`, `logs_dir`, `socket`,
`cache_dir`); FEAT-005 MUST NOT change this ordering or the
dataclass field count.

---

## CLI environment variables introduced or extended by FEAT-005

| Variable | When honored | Effect |
| -------- | ------------ | ------ |
| `AGENTTOWER_SOCKET` | every CLI invocation | overrides the resolved socket path; validated per FR-002 (R-001) |
| `AGENTTOWER_CONTAINER_ID` | container-context CLI invocations | overrides container identity detection; used verbatim as the candidate (R-004) |
| `AGENTTOWER_TEST_PROC_ROOT` | tests only; production binary asserts unset | substitutes a fake root for `/.dockerenv`, `/run/.containerenv`, `/proc/self/cgroup`, `/proc/1/cgroup`, `/etc/hostname` (R-011, FR-025) |

FEAT-005 introduces no other env var. The existing
`AGENTTOWER_TEST_DOCKER_FAKE` (FEAT-003) and
`AGENTTOWER_TEST_TMUX_FAKE` (FEAT-004) seams are unchanged and
honored verbatim by the daemon process FEAT-005's tests spawn.
