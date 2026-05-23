# Contract Surface Requirements Quality Checklist: Local App Backend Contract (FEAT-011)

**Purpose**: Validate requirements quality for the `app.*` namespace surface, message framing, and façade-vs-service dispatch — completeness, clarity, consistency, measurability, coverage.
**Created**: 2026-05-19
**Feature**: [spec.md](../spec.md)

## Requirement Completeness

- [X] CHK001 Are all required `app.*` methods enumerated as a closed, named set anywhere in the spec, or only listed piecemeal across FRs and user stories? [Completeness, Spec §FR-001, §FR-029]
- [X] CHK002 Is the request framing format (NDJSON over Unix socket) specified down to delimiter byte, max line length, and character encoding? [Completeness, Spec §FR-001]
- [X] CHK003 Is the response framing format specified symmetrically with the request format? [Completeness, Spec §FR-001]
- [X] CHK004 Are MIME-style content rules (UTF-8, JSON only, no embedded NULs) explicitly required? [Gap]
- [X] CHK005 Is the maximum request payload size specified? [Gap]
- [X] CHK006 Is the maximum response payload size specified, especially for `app.dashboard` and max-limit list responses? [Gap]
- [X] CHK007 Is `app.scan.status` (referenced by FR-030 and FR-030b) declared anywhere as an exposed method, or only implied? [Gap, Spec §FR-030, §FR-030b]
- [X] CHK008 Are `app.routing.enable` / `app.routing.disable` methods explicitly part of the namespace per FR-042's negative restriction, or only implied by the prohibition? [Gap, Spec §FR-042]

## Requirement Clarity

- [X] CHK009 Is "additive, not a replacement" (FR-002) defined operationally — must the existing CLI surface remain bit-for-bit identical, or only semantically equivalent? [Clarity, Spec §FR-002]
- [X] CHK010 Is "dispatch into the same daemon-internal service layer" (FR-004) defined with enough specificity that an implementer can identify the shared functions? [Clarity, Spec §FR-004]
- [X] CHK011 Is the term "façade" (Summary §3) defined in the spec or assumed from context? [Clarity, Spec §Summary]
- [X] CHK012 Is "newline-delimited JSON" precisely specified (which line ending — `\n` only, or also `\r\n`)? [Clarity, Spec §FR-001]

## Requirement Consistency

- [X] CHK013 Are method names consistently dot-cased (`app.<entity>.<verb>`) across all FRs, user stories, acceptance scenarios, and Clarifications? [Consistency]
- [X] CHK014 Does FR-001's reference to FEAT-002 §19 framing match the framing actually used by existing methods in the spec? [Consistency, Spec §FR-001]
- [X] CHK015 Are the methods listed in FR-029 the complete mutation set, or do other FRs imply mutation methods not in FR-029 (e.g., `app.scan.containers`, `app.scan.panes`, `app.scan.status`)? [Consistency, Coverage, Spec §FR-029]
- [X] CHK016 Are `app.queue.approve` / `delay` / `cancel` enumerated by FR-029 consistent in spelling and case with FEAT-009's queue action names? [Consistency, Spec §FR-029]

## Scenario Coverage

- [X] CHK017 Is the behavior defined when an unknown method outside both legacy and `app.*` namespaces is called? [Gap]
- [X] CHK018 Is the behavior defined when a legacy method receives an `app_session_token`-bearing payload — must it ignore the field or error? [Gap, Spec §FR-002]
- [X] CHK019 Is the behavior defined when the same request line contains two JSON objects (framing violation)? [Gap, Spec §FR-001]
- [X] CHK020 Is the behavior defined when a request line exceeds any (yet-unspecified) max length? [Gap]

## Measurability

- [X] CHK021 Is the "no network listener" invariant (FR-003) phrased so it can be verified by a packet capture or `lsof` test? [Measurability, Spec §FR-003, §SC-006]
- [X] CHK022 Can FR-004's "dispatch into the same daemon-internal service layer" be objectively verified (e.g., shared-symbol import test in plan)? [Measurability, Spec §FR-004]

## Ambiguities, Conflicts, Gaps

- [X] CHK023 Is "host OR mounted into a bench container" (FR-040) consistent with FR-042 prohibiting bench-container callers from `routing.enable/disable` — under what code does a container caller of a non-host-only method fail? [Ambiguity, Spec §FR-040, §FR-042]
