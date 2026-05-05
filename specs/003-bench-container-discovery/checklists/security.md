# Security Checklist: Bench Container Discovery

**Purpose**: Validate that FEAT-003's security and Docker-subprocess-safety requirements are written well — complete, unambiguous, consistent, measurable, and adequately covered — before `/speckit.tasks` consumes the spec.
**Created**: 2026-05-05
**Feature**: [spec.md](../spec.md) — see also [plan.md](../plan.md), [research.md](../research.md), [data-model.md](../data-model.md), [contracts/cli.md](../contracts/cli.md), [contracts/socket-api.md](../contracts/socket-api.md)

**Scope**: This checklist tests the *requirements* governing the new Docker subprocess surface, the new socket methods, the new SQLite/JSONL persistence paths, and the new config block — it does NOT verify the implementation. A `[ ]` here means a question about the *spec quality*, not a TODO for the coder.

## Docker Subprocess Argv Safety

- [x] CHK001 Are the exact Docker subprocesses FEAT-003 is allowed to spawn (`docker ps`, `docker inspect`) explicitly enumerated, and is any other Docker subcommand explicitly out of scope? [Completeness, Spec FR-001, FR-002, FR-003]
- [x] CHK002 Is the requirement that container names, ids, and other config-derived strings flow as `subprocess.run` argv items (never interpolated into a shell string) stated in the spec or plan? [Completeness, Plan Constraints]
- [x] CHK003 Is `shell=False` (or its equivalent) explicitly required for every Docker invocation, or is the rule expressed in another testable form? [Clarity, Gap]
- [x] CHK004 Are the `docker ps` flags (`--no-trunc`, `--format`) pinned in the requirements rather than left to implementation discretion? [Clarity, Research R-002]
- [x] CHK005 Does the spec define what happens when a configured `name_contains` substring contains shell metacharacters (e.g., `;`, `|`, `$(`), confirming they cannot reach a shell? [Edge Case, Gap]

## PATH and Binary Resolution

- [x] CHK006 Is the rule for locating the `docker` binary (e.g., `shutil.which("docker")` against the daemon's environment `PATH`) documented in requirements? [Completeness, Research R-001]
- [x] CHK007 Are the requirements explicit about what happens when `docker` is absent from PATH versus present-but-not-executable, and do both cases map to a defined error code? [Clarity, Spec FR-018, Research R-014]
- [x] CHK008 Is the daemon's effective `PATH` at startup documented (inherited from the launching shell, scrubbed, or pinned)? [Gap, Ambiguity]
- [x] CHK009 Does the spec address whether a malicious or shadowed `docker` earlier on PATH is in or out of the threat model for FEAT-003? [Coverage, Gap]

## Subprocess Timeout Enforcement

- [x] CHK010 Is the 5-second per-call timeout requirement stated unambiguously and applied to *every* `docker ps` and *every* `docker inspect` call (not aggregated)? [Clarity, Spec FR-024, Research R-004]
- [x] CHK011 Are the requirements clear that a timeout produces a structured degraded result rather than an uncaught exception or daemon crash? [Completeness, Spec FR-018, FR-024]
- [x] CHK012 Is it specified that a timed-out subprocess is terminated (e.g., killed) so it does not leak as a zombie? [Gap]
- [x] CHK013 Are the requirements clear about whether a hung Docker can hold the scan mutex past the timeout window, and is that bound documented? [Clarity, Plan Constraints, Spec FR-023]
- [x] CHK014 Is the worst-case mutex-hold time (per-call timeout × number of candidates) acknowledged in the requirements so reviewers can reason about denial-of-service surface? [Coverage, Plan Performance Goals]

## Concurrent Scan Serialization

- [x] CHK015 Are the serialization requirements (in-process mutex, blocking second caller) testable and measurable from outside the daemon? [Measurability, Spec FR-023]
- [x] CHK016 Does the spec define the read-side guarantee that `list_containers` MUST NOT block on the scan mutex? [Completeness, Plan Constraints, Research R-005]
- [x] CHK017 Is the behavior under N>2 parallel scan callers specified (FIFO, fairness, queueing depth)? [Gap]
- [x] CHK018 Are the requirements explicit about whether the mutex survives daemon restart or is reinitialized fresh, including the impact on in-flight scans during shutdown? [Coverage, Gap]

## Unix Socket and Process Boundary

- [x] CHK019 Is it stated that FEAT-003 adds no new network listener and reuses only the existing FEAT-002 `AF_UNIX` socket? [Completeness, Spec FR-021, Constitution I]
- [x] CHK020 Are the inherited file modes (`0700` directories, `0600` files including the new SQLite tables on disk) preserved and documented? [Consistency, Plan Constraints]
- [x] CHK021 Are the requirements explicit that the daemon does not gain any privilege, uid change, or sudo step in FEAT-003? [Coverage, Gap]
- [x] CHK022 Does the spec confirm that no test or production code path invokes Docker from the CLI process directly (only via the daemon), so the socket-permission boundary remains the only authorization point? [Completeness, Contracts cli.md]

## Configuration Validation

- [x] CHK023 Are the rejection criteria for `[containers] name_contains` enumerated (empty list, non-list, non-string element, blank-after-strip element)? [Completeness, Spec FR-006]
- [x] CHK024 Is "actionable error" for invalid config quantified (specific error code, message format) rather than left as an adjective? [Clarity, Spec FR-006, Research R-014]
- [x] CHK025 Does the spec specify whether the config is re-read per scan or cached, and if cached, when invalidation occurs? [Gap, Quickstart §6]
- [x] CHK026 Are upper bounds on `name_contains` (length per element, list size) defined to prevent pathological config from generating overlong subprocess argv? [Edge Case, Gap]
- [x] CHK027 Is the requirement clear that an invalid config never silently widens the matching scope to "all containers"? [Consistency, Spec FR-006]

## Persistence and Secret Exposure

- [x] CHK028 Are the inspect fields permitted into `containers.inspect_json` enumerated, and is everything else (e.g., raw env values, raw `HostConfig`) excluded? [Completeness, Research R-007, Data-Model §2.1]
- [x] CHK029 Is the env-key allowlist (`USER`, `HOME`, `WORKDIR`, `TMUX`) justified in the requirements (vs. an arbitrary list with no rationale)? [Clarity, Research R-007]
- [x] CHK030 Does the spec address whether label *values* and mount *source paths* may contain secrets, and explicitly defer redaction to FEAT-007? [Coverage, Spec Assumptions, Quickstart §0]
- [x] CHK031 Are requirements specified for what *cannot* appear in `error_message` / `error_details_json` (e.g., stderr is captured, but stripped of high-entropy strings)? [Gap, Coverage]
- [x] CHK032 Is the requirement explicit that `events.jsonl` records degraded scans only and never includes raw Docker stderr without bounding it (size cap, character class)? [Gap, Spec FR-019]
- [x] CHK033 Are the lifecycle log additions (`scan_started`, `scan_completed`) bounded so they cannot leak inspect output, env values, or secrets? [Coverage, Research R-015]

## Authorization and Method Boundaries

- [x] CHK034 Does the spec confirm that the new socket methods inherit FEAT-002's caller-authorization model (host user only via socket mode `0600`) and add no additional auth or roles? [Consistency, Contracts socket-api.md §1]
- [x] CHK035 Are the new closed error codes (`config_invalid`, `docker_unavailable`, `docker_permission_denied`, `docker_timeout`, `docker_failed`, `docker_malformed`) defined non-overlappingly? [Clarity, Research R-014]
- [x] CHK036 Is it specified whether `list_containers` exposes any field a host-user-but-non-developer caller should not see (e.g., mount sources for unrelated projects)? [Coverage, Gap]
- [x] CHK037 Are forward-compatibility guarantees stated for clients (unknown `result` keys tolerated; unknown error codes tolerated) so future extensions don't accidentally enlarge the security surface? [Consistency, Contracts socket-api.md §3.7]

## Backward-Compatibility with FEAT-001 / FEAT-002

- [x] CHK038 Are the exact pre-existing FEAT-002 envelope shapes (`ping`, `status`, `shutdown`) declared bytewise unchanged in the requirements? [Consistency, Spec FR-022, Plan Constraints]
- [x] CHK039 Is the requirement explicit that `agenttower config init` output remains byte-for-byte identical (no default `[containers]` block emitted)? [Consistency, Research R-009]
- [x] CHK040 Does the spec address forward/backward compatibility of the SQLite schema (FEAT-003 daemon refusing to start against v1 DB? FEAT-002 daemon refusing v2 DB?), and is downgrade scope explicitly excluded? [Coverage, Data-Model §7]
- [x] CHK041 Are the lifecycle log additions specified as additive (existing six event tokens unchanged) rather than reformatted? [Consistency, Research R-015]

## Threat Model and Attacker Capabilities

- [x] CHK042 Is the threat model for FEAT-003 articulated (host user is trusted; Docker daemon is trusted; container *contents* are untrusted; PATH may be partially attacker-controlled)? [Gap, Traceability]
- [x] CHK043 Are requirements aligned to that threat model — i.e., is there a line connecting each security-relevant FR (FR-006, FR-018, FR-021, FR-024) back to a documented threat? [Traceability, Gap]
- [x] CHK044 Is the requirement explicit about whether a malicious container *name* (e.g., names containing newlines, ANSI escapes, or argv-injection-shaped substrings) can affect the daemon, CLI output, or persisted JSON? [Edge Case, Gap]
- [x] CHK045 Is the requirement explicit about whether a malicious `docker inspect` JSON payload (e.g., a crafted label value) can break the parser, oversized-line the response, or poison `events.jsonl`? [Edge Case, Gap]
- [x] CHK046 Does the spec bound the maximum response size of `scan_containers` and `list_containers` against the FEAT-002 64 KiB socket-line cap, and define behavior when a single response would exceed it? [Coverage, Gap, Contracts socket-api.md §1]

## Test Coverage of Security-Relevant Paths

- [x] CHK047 Is the requirement that no real `docker` binary is invoked in the test suite stated as a testable assertion (not just an aspiration)? [Measurability, Spec FR-020, SC-007, Research R-016]
- [x] CHK048 Are unit-test coverage requirements for argv construction, error normalization, and timeout handling explicit (not just "tested")? [Coverage, Spec SC-006]
- [x] CHK049 Are integration-test requirements for every degraded path (command-not-found, permission-denied, timeout, non-zero exit, malformed inspect) stated independently? [Completeness, Spec SC-007, Quickstart §5]
- [x] CHK050 Is the requirement to assert the daemon stays alive after every degraded path testable end-to-end (e.g., a follow-up `agenttower status` succeeds)? [Measurability, Spec SC-004]
- [x] CHK051 Are concurrent-scan serialization tests required, with a measurable invariant (scan B's `started_at >= scan A's `completed_at`)? [Measurability, Quickstart §4]
- [x] CHK052 Is the no-network-listener invariant for FEAT-003 inherited from FEAT-002 testable via the same `lsof`/`ss`-style assertion that FEAT-002 already uses (`tests/integration/test_daemon_no_network.py` pattern)? [Consistency, Spec FR-021]

## Notes

- Check items off as completed: `[x]`
- Each item asks "Is the *requirement* clear/complete/consistent/measurable?" — not "Does the code do X?".
- `[Gap]` items are likely actionable: either add the missing requirement to spec.md / plan.md / research.md, or explicitly defer with rationale.
- `[Ambiguity]` and `[Conflict]` items should be resolved by another `/speckit.clarify` round before `/speckit.tasks`.
- This checklist is the security gate before tasks are generated; if every item passes, the spec is ready for `/speckit.tasks`.

## Closure Notes

- Closed after adding FR-027 through FR-036 and updating plan/research/data-model/contracts to cover Docker argv safety, daemon PATH trust boundary, timeout cleanup, scan mutex semantics, config bounds, sensitive-field bounds, inherited socket authorization, and FEAT-002 request-vs-response size behavior.
