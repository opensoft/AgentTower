# Configuration & Defaults Requirements Checklist: Event Ingestion, Classification, and Follow CLI

**Purpose**: Validate that FR-045 default-value coverage, override precedence, `agenttower config paths` exposure, and configurability requirements are complete, clear, consistent, and measurable. This checklist tests the **requirements writing**, not the implementation.
**Created**: 2026-05-10
**Feature**: [spec.md](../spec.md)
**Depth**: Formal release gate

## Requirement Completeness

- [ ] CHK001 Is every spec-named MVP default (reader cycle cap, debounce window, `pane_exited` grace, per-event excerpt cap, per-cycle byte cap, default page size) required to have a documented value somewhere in the spec or plan? [Completeness, Spec §FR-045]
- [ ] CHK002 Are the plan-only defaults (`long_running_grace_seconds`, `excerpt_truncation_marker`, `max_page_size`, `follow_long_poll_max_seconds`, `follow_session_idle_timeout_seconds`) required to be normative or are they implementation-specific? [Completeness, Plan §"Defaults locked"]
- [ ] CHK003 Are override-precedence requirements specified (env > config.toml > built-in, or some other order)? [Completeness, Gap]
- [ ] CHK004 Are requirements specified for `agenttower config paths` exposing the resolved values for every FR-045 setting? [Completeness, Spec §FR-045]
- [ ] CHK005 Are configuration-validation requirements specified (out-of-range values, malformed types, unknown keys)? [Completeness, Gap]
- [ ] CHK006 Are requirements specified for the boundary between "MVP cap" (≤ 5 s for debounce, ≤ 30 s for grace, ≤ 50 page size) and "default value" (the implementer-chosen specific value within the cap)? [Completeness, Spec §FR-014, FR-017, FR-030]
- [ ] CHK007 Are requirements specified for the configuration-reload behavior (does daemon need restart, or is hot-reload supported)? [Completeness, Gap]
- [ ] CHK008 Are requirements specified for the documentation surface where defaults are published (FR-045 says "documented in the FEAT-008 plan" — is that sufficient or should they also be in operator-facing docs)? [Completeness, Spec §FR-045]
- [ ] CHK009 Are requirements specified for what happens when `[events]` section is absent from `config.toml` (built-in defaults apply)? [Completeness, Gap]
- [ ] CHK010 Are requirements specified for what happens when an unknown key appears in `[events]` (warn, error, or ignore)? [Completeness, Gap]

## Requirement Clarity

- [ ] CHK011 Is "must have a documented MVP default" precise enough to be testable (e.g., "the value must be a literal in `events/__init__.py`")? [Clarity, Spec §FR-045]
- [ ] CHK012 Is "configurable through the FEAT-001 configuration surface" precise about the configuration mechanism (TOML key shape, type, units)? [Clarity, Spec §FR-045]
- [ ] CHK013 Is "must be observable in test (e.g., via configuration injection)" precise about the test seam path? [Clarity, Spec §FR-019]
- [ ] CHK014 Is "≤ 5 seconds at MVP scale" specifying a maximum cap or a default value (the spec leaves room for either)? [Ambiguity, Spec §FR-014]
- [ ] CHK015 Is "documented MVP default sufficient to drain typical interactive output without starving other attachments" measurable enough to derive a specific number? [Clarity, Spec §FR-019]

## Requirement Consistency

- [ ] CHK016 Are the spec's six FR-045-named defaults consistent with the plan's eleven-row defaults table (no missing, no contradicting values)? [Consistency, Spec §FR-045, Plan §"Defaults locked"]
- [ ] CHK017 Is the per-cycle byte cap consistent between the spec ("documented MVP default sufficient...") and the plan (64 KiB)? [Consistency, Spec §FR-019, Plan]
- [ ] CHK018 Are the debounce window default (5 s) and the `pane_exited` grace (30 s) consistent with the upper-bound caps stated in the spec (≤ 5 s, ≤ 30 s)? [Consistency, Spec §FR-014, FR-017]
- [ ] CHK019 Is `default_page_size = 50` consistent with `max_page_size = 50` (i.e., the cap and the default are deliberately equal in MVP)? [Consistency, Plan §"Defaults locked"]
- [ ] CHK020 Are the configuration units consistent across all settings (seconds for time, bytes for size; no millisecond/kilobyte mixing)? [Consistency, Plan §"Defaults locked"]

## Acceptance Criteria Quality

- [ ] CHK021 Is there an SC requiring `agenttower config paths` to surface every FR-045 default? [Measurability, Spec §FR-045]
- [ ] CHK022 Are acceptance criteria specified for the configuration-injection test seam (FR-019: "MUST be observable in test (e.g., via configuration injection)")? [Measurability, Spec §FR-019]
- [ ] CHK023 Are acceptance criteria specified for what `agenttower config paths` should output for an `[events]` section that has overrides applied? [Measurability, Gap]

## Scenario Coverage

- [ ] CHK024 Are requirements defined for the all-defaults scenario (no `[events]` overrides; built-in values apply)? [Coverage, Gap]
- [ ] CHK025 Are requirements defined for the partial-override scenario (some keys in `[events]`, others fall back to defaults)? [Coverage, Gap]
- [ ] CHK026 Are requirements defined for the all-overrides scenario (every key in `[events]` set explicitly)? [Coverage, Gap]
- [ ] CHK027 Are requirements defined for the env-var override scenario (if env vars are part of the precedence chain)? [Coverage, Gap]
- [ ] CHK028 Are requirements defined for the bad-value scenario (malformed type, out-of-range, negative number)? [Coverage, Gap]

## Edge Case Coverage

- [ ] CHK029 Is the case "configurable value at the absolute MVP cap (e.g., debounce = exactly 5 s)" addressed as still acceptable? [Edge Case, Spec §FR-014]
- [ ] CHK030 Is the case "configurable value above the MVP cap (e.g., debounce > 5 s)" addressed (rejected at startup, or accepted with warning)? [Edge Case, Gap]
- [ ] CHK031 Is the case "zero or negative value for a positive-duration setting" addressed? [Edge Case, Gap]
- [ ] CHK032 Is the case "config.toml file is unreadable or invalid TOML" addressed by FR-001 (FEAT-001 ownership) — is the FEAT-008 layering explicit about delegating? [Edge Case, Gap]
- [ ] CHK033 Is the case "`per_cycle_byte_cap_bytes` smaller than `per_event_excerpt_cap_bytes`" addressed (likely an invalid combination — lines longer than the byte cap can never be ingested)? [Edge Case, Gap]

## Non-Functional Requirements

- [ ] CHK034 Are requirements specified for the configuration's startup-time impact (single TOML parse vs lazy)? [NFR, Gap]
- [ ] CHK035 Are requirements specified for thread-safety of the configuration object during reader cycles (read-only after startup, or mutable)? [NFR, Gap]
- [ ] CHK036 Are requirements specified for backwards compatibility of the `[events]` section schema (adding a key in a future feature must not break a v6 daemon reading the v6 config)? [NFR, Gap]

## Dependencies & Assumptions

- [ ] CHK037 Is the dependency on FEAT-001's configuration surface version-pinned for stable `[events]` parsing? [Dependency, Spec §FR-045]
- [ ] CHK038 Is the assumption that operators understand the difference between MVP cap and default-value-within-cap documented? [Assumption, Gap]
- [ ] CHK039 Is the assumption that `agenttower config paths` is the operator's authoritative view of resolved values documented as a hard contract? [Assumption, Spec §FR-045]
