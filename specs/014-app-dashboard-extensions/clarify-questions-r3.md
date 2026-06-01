# Clarification Questions — FEAT-014 App Dashboard Extensions — Round 3 (post-MVP-impl)

**Path (canonical, top)**: `specs/014-app-dashboard-extensions/clarify-questions-r3.md`

**Session date**: 2026-05-25
**Spec under clarification**: `specs/014-app-dashboard-extensions/spec.md`
**Mode**: post-implementation-design Round 3 — resolves the spec self-inconsistency surfaced during MVP implementation
**Source**: GitHub issue [#28](https://github.com/opensoft/AgentTower/issues/28) (FR-019 vs Research §PB inconsistency) + analyze finding **F-019-PB-1** (HIGH)
**Question count**: 1
**Cap**: ≤ 25 per user-global rule (well under)

Reply with one of:
- The option letter for the recommended (or any) choice (e.g., `Q1: A`)
- `yes` / `recommended` to accept the recommendation
- A short free-form answer (≤ 5 words) where allowed

Answers should be written **into this same file** under the `## Answers` section below.

## Answers

Q1: B

---

## Q1. FR-019 vs Research §PB priority for registered-pane-on-inactive-container  *(closes issue #28 / analyze F-019-PB-1)*

### The inconsistency

A pane with an active agent on an inactive container:

- **FR-019** says `discovered-and-registered == v1.0 counts.panes.registered`. The v1.0 query (`_pane_counts` in `dashboard.py`) counts ALL panes with active agents, regardless of container state. So this pane is in v1.0 `registered`.
- **Research §PB** says bucket priority is `discovery-degraded > inactive-or-stale > discovered-and-registered > discovered-and-unmanaged`. This pane goes to `inactive-or-stale` because its container is inactive.

Result: under the priority rule, `dar` is LESS than v1.0 `registered`. FR-019's strict equality invariant fails.

The MVP fixture (US1 acceptance — only active containers) avoids exercising the contradiction, but any general fixture with one or more registered-pane-on-inactive-container rows would surface it.

### What the MVP currently does

The MVP implementation (commit `dbd1f3e`) follows Research §PB priority — a registered pane on an inactive container goes to `inactive-or-stale`. The docstring documents this as a known gap. Tests pass because the test fixture only has active containers.

### Resolution options

**Recommended: Option B** — Loosen FR-019 from strict `==` to `≤` with a documented gap rule. The current MVP impl is correct under this resolution and needs no code change. Operationally meaningful: an operator looking at the dashboard during a container shutdown sees the pane flagged "stale" rather than "registered," which matches operator intent.

| Option | Description |
|--------|-------------|
| A | **Revise Research §PB priority** so `discovered-and-registered` outranks `inactive-or-stale`. Registered panes always show in `dar` regardless of container state. v1.1 implementation needs an SQL change in `_compute_pane_state_buckets`: drop the `c.active = 0` leg from the `inactive-or-stale` query AND the `c.active = 1` condition from the `dar` query (and relax the `dar` `p.active = 1` filter) so both predicates move together — changing only `dar` would double-count inactive registered panes and underflow the `dau = total - ios - dar` remainder. FR-019 strict `==` invariant holds. |
| B | **Loosen FR-019** from strict `==` to `dar ≤ v1.0 counts.panes.registered`, with the gap equal to the registered panes §PB routes to `inactive-or-stale`/`discovery-degraded` — i.e. container `inactive`/`degraded_scan`, the pane's own `active` flag unset (FEAT-004 reconciliation, even on an active container), or stale `last_seen_at`. Document the gap rule explicitly in FR-019. MVP impl is correct as-is; no code change. (matches current behavior) |
| C | **Introduce a new 5th bucket** `registered-but-stale` for registered-pane-on-inactive-container. Preserves both FR-019 strict equality AND priority distinction. Requires v1.2 minor (new closed-set value) and refactoring the existing 4-key vocabulary. Most disruptive. |
| Short | Different rule (≤ 5 words). |

### Affected artifacts if Option A chosen

- `research.md` §PB priority list reordered
- `data-model.md` §PaneState priority section reordered
- `spec.md` FR-002 priority chain reordered (the FR-002 sentence currently lists `discovery-degraded > inactive-or-stale > discovered-and-registered > discovered-and-unmanaged`)
- `src/agenttower/app_contract/dashboard.py::_compute_pane_state_buckets` SQL change: drop the `c.active = 0` leg from the `inactive-or-stale` query AND the `c.active = 1` condition from the `dar` query (both predicates must move together, else the two buckets overlap and `dau = total - ios - dar` double-counts / underflows). Note `c.active` is a WHERE condition, not a JOIN condition.
- Existing US1 acceptance test still passes (only active containers)

### Affected artifacts if Option B chosen (recommended)

- `spec.md` FR-019 wording loosened to `≤` plus the gap rule
- `data-model.md` §PaneState invariants section similarly loosened
- `research.md` §PB unchanged (it's the canonical priority rule)
- `_compute_pane_state_buckets` docstring tightened (drop the "Tracked in #28" caveat once spec is updated)
- No code change

### Affected artifacts if Option C chosen

- Major: spec.md FR-002 closed-set expanded from 4 to 5 keys
- contracts/closed-sets-v1_1.md §PaneState expanded
- data-model.md §PaneState expanded
- New bucket needs a name, priority position, and test coverage
- Likely a v1.2 minor, not appropriate for v1.1 anymore

---

**Path (canonical, bottom)**: `specs/014-app-dashboard-extensions/clarify-questions-r3.md`

**Awaiting answer above under `## Answers`.** Once filled in, I'll fold R3 into `spec.md` as `### Session 2026-05-25-r3` under `## Clarifications`, apply the affected-artifact edits, bundle with the 3 MEDIUM remediation fixes (D-DRIFT-1 + D-DRIFT-2 + PROCESS-1) into one commit, push, and re-run `/speckit-analyze` to verify back to 0/0/0/0.
