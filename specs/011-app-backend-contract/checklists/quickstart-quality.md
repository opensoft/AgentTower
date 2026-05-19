# Quickstart Quality Checklist: Local App Backend Contract (FEAT-011)

**Purpose**: Validate requirements quality of `quickstart.md` — story coverage, walkthrough completeness, fixture clarity.
**Created**: 2026-05-19
**Feature**: [quickstart.md](../quickstart.md), [spec.md](../spec.md)

## Walkthrough Completeness

- [X] CHK001 Does the quickstart cover **all four Story 1 calls** (preflight, hello, readiness, dashboard)? [Completeness, Quickstart §steps]
- [X] CHK002 Is each step documented with **request, expected success response, and key failure paths**? [Completeness, Quickstart §steps]
- [X] CHK003 Are **prerequisites enumerated** concretely (≥1 container, ≥1 pane, ≥1 registered agent) rather than vague? [Clarity, Quickstart §Prerequisites]
- [X] CHK004 Is the **socket path** stated with a concrete default (`~/.local/state/opensoft/agenttower/agenttowerd.sock`)? [Clarity, Quickstart §Step 0]
- [X] CHK005 Is **SC-002 (≤500ms)** stated as a budget the walkthrough must meet? [Traceability, Quickstart §Step 4]

## Verification Steps

- [X] CHK006 Is **"no subprocess invocation"** stated as a verification invariant (SC-001)? [Completeness, Quickstart §Step 5]
- [X] CHK007 Is **"no CLI parsing"** stated as a verification invariant (SC-001)? [Completeness, Quickstart §Step 5]
- [X] CHK008 Is **token redaction in JSONL** stated as a verification invariant (SC-008)? [Completeness, Quickstart §Step 5]
- [X] CHK009 Is the **JSONL audit path** stated concretely (`~/.local/state/opensoft/agenttower/audit.jsonl`)? [Clarity, Quickstart §Step 5]

## Story Coverage Forward Pointer

- [X] CHK010 Does **"Beyond Story 1"** section enumerate the **5 user stories** with named integration test files? [Completeness, Quickstart §Beyond Story 1]
- [X] CHK011 Does the forward-pointer cover **Stories 2, 3, 4, 5** with their distinct concerns (adopt, operator actions, degraded states, version drift)? [Coverage, Quickstart §Beyond Story 1]
- [X] CHK012 Is **SC-004 (≤2s adopt round-trip)** referenced in the Story 2 mention? [Traceability, Quickstart §Beyond Story 1]

## Sample Payload Quality

- [X] CHK013 Are the **sample `app.hello` response fields** all the required ones from FR-010 (token, id, daemon_version, schema_version, app_contract_version, supported_minor_range, host_user_id, capability_flags, state)? [Completeness, Quickstart §Step 2]
- [X] CHK014 Is **`capability_flags = {}`** at v1.0 shown in the sample? [Consistency, Quickstart §Step 2, Spec §FR-039]
- [X] CHK015 Is the **sample `app.readiness` response** showing all 6 subsystems from FR-013? [Completeness, Quickstart §Step 3]
- [X] CHK016 Is the **sample `app.readiness` response** showing the `hints[]` array (always present)? [Consistency, Quickstart §Step 3, Spec §FR-014a]
- [X] CHK017 Is the **sample `app.dashboard` response** showing all 7 count surfaces (containers, panes, agents, log_attachments, events, queue, routes)? [Completeness, Quickstart §Step 4]
- [X] CHK018 Is the **sample `app.dashboard` response** showing the `hints[]` array? [Consistency, Quickstart §Step 4, Spec §FR-014a]

## Failure-Path Documentation

- [X] CHK019 Is the **major-mismatch failure path** documented in Step 2 (sample `app_contract_major_unsupported` envelope)? [Completeness, Quickstart §Step 2]
- [X] CHK020 Is the **host-only failure path** referenced anywhere in the quickstart (a bench-container caller scenario)? [Coverage, Spec §FR-042]
- [X] CHK021 Is the **degraded readiness path** documented in Step 3 (sample with Docker stopped)? [Completeness, Quickstart §Step 3]
- [X] CHK022 Are **socket-level error mappings** documented (socket missing, permission denied) as client-library responsibilities? [Clarity, Quickstart §Step 1]

## Ambiguities & Gaps

- [X] CHK023 Is the **wire format framing** (NDJSON, `\n` delimiter, UTF-8) stated in the quickstart, or assumed? [Gap, Quickstart §global]
- [X] CHK024 Is **how the client passes the session token** on subsequent calls specified (top-level `app_session_token` field on every request line)? [Clarity, Quickstart §Step 3]
- [X] CHK025 Is the **`recent_limit` default value** mentioned in the dashboard step (default 10 from FR-017)? [Clarity, Quickstart §Step 4]
- [X] CHK026 Are the **walking steps annotated with FR/SC references** so a reader can trace each invariant back to the spec? [Traceability, Quickstart §all]
- [X] CHK027 Is there a sample for the **`payload_too_large` failure path** (oversized request)? [Gap, Spec §FR-003a]

## Test Plan Mapping

- [X] CHK028 Is the **mapping from quickstart steps to integration test files** explicit (e.g., Step 1–4 ↔ `tests/integration/test_story1_dashboard_bootstrap.py`)? [Traceability, Quickstart §Beyond Story 1]
- [X] CHK029 Are the **5 story → test file mappings 1:1** with the User Stories in spec.md? [Consistency, Quickstart §Beyond Story 1, Spec §User Stories]
