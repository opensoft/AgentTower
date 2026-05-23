# Clarification Questions — F4 (helper-agent policy) + F7 (deferred stage)

**Feature**: 012-flutter-control-panel
**Spec**: `specs/012-flutter-control-panel/spec.md`
**Session date**: 2026-05-23 (round 2)
**Scope**: Resolve the two Tier-1 findings that Codex would otherwise have to guess at when running the spec-quality-pass change.
**Mode**: Block presentation — answer all in one pass.

Reply with one line per question (e.g. `Q1: B`, `Q3: recommended`, `Q6: A; note: ...`). Free-form notes per question are welcome and will be folded into the spec under `## Clarifications → ### Session 2026-05-23 (round 2)`.

---

## F4 — Helper-agent policy contract (referenced by FR-037, FR-038, FR-042)

### Q1 — Where do the baked helper-agent policy defaults live?

The handoff flow needs to auto-fill "allowed helper-agent defaults" (FR-038) and snapshot the resolved policy on submission (FR-042). The defaults have to come from somewhere the app can read; the architectural choice affects whether the app integrates via `app.*` (FR-001) or by reading a repo file.

**Recommended:** Option B — daemon-side resource exposed via `app.*` (e.g. `app.helper_policies.list` / `app.helper_policies.resolve`). Keeps the app a pure FEAT-011 client (FR-001, FR-005), avoids the app having to parse repo files, and lets the daemon decide whether to source defaults from a baked manifest or a per-project repo file under the hood.

**Answer:** Q1: B

| Option | Description |
|--------|-------------|
| A | A markdown file in the repo at `docs/helper-agent-policy-defaults.md`; app reads file directly. |
| B | Daemon-side resource exposed via `app.*`; app never reads policy files itself. |
| C | A YAML/JSON config file in the daemon's own config dir; app reads via an `app.*` indirection. |
| D | Hybrid: daemon-served defaults sourced from a manifest in `agenttower/config/`; the manifest is the source of truth and the daemon caches it. |

---

### Q2 — Minimum field set for a helper-agent policy

What fields MUST a helper-agent policy carry for the first release?

**Recommended:** Option A — the minimal set: `policy_id`, `allowed_helper_capabilities` (set of capability tokens), `default_helper_capability` (single token), `policy_source` (`baked_default` | `operator_override` | `repo_override`). Enough to satisfy FR-038 + FR-042 without overcommitting to quota/rate-limit semantics that may belong to FEAT-009 or later.

**Answer:** Q2: A

| Option | Description |
|--------|-------------|
| A | Minimal: `policy_id`, `allowed_helper_capabilities`, `default_helper_capability`, `policy_source`. |
| B | A + per-capability quotas (max invocations per handoff or per hour). |
| C | A + per-capability tool/permission whitelist (filesystem, network, daemon mutation surfaces). |
| D | Defer the field set to plan phase; spec commits only that a policy contract exists. |

---

### Q3 — Scope of operator override (FR-037 "helper-agent policy override")

When the operator overrides the helper-agent policy in the handoff flow, what does the override apply to?

**Recommended:** Option A — per-handoff only. Each handoff is an atomic unit with its own snapshot (FR-042's `helper_policy_snapshot`). Wider scopes (per-master, per-project, global) create hidden state that surprises operators and conflicts with the handoff snapshot's reproducibility property.

**Answer:** Q3: A

| Option | Description |
|--------|-------------|
| A | Per-handoff only — override applies to this submission, then resets to defaults. |
| B | Per-master — override sticks on the target master and applies to every subsequent handoff to it. |
| C | Per-project — override applies to every handoff in the project. |
| D | Global — operator-level default for all their handoffs across all projects. |

---

### Q4 — Repo-level (per-project) override allowed?

Independent of operator override, can a single project tighten or loosen the baked defaults via a repo-level setting (e.g. a project that uses helper agents heavily wants broader defaults than another)?

**Recommended:** Option A — yes, via a conventional path the daemon discovers (so the app still queries via `app.*` per Q1). Real projects vary in tool exposure; a repo override is the cleanest place to encode that variation and it composes cleanly with `policy_source = repo_override` in the snapshot.

**Answer:** Q4: A

| Option | Description |
|--------|-------------|
| A | Yes — repo-level override at a conventional path (e.g. `agenttower/helper-policy.yaml`); daemon discovers and surfaces it via `app.*`. |
| B | No — only baked defaults + per-handoff operator override (Q3). Project-specific differences happen by operator override every time. |
| C | Yes, but stored in daemon project-state (no repo file) and editable only via daemon CLI. |

---

## F7 — "Deferred" feature/change stage (referenced by FR-039, SC-004)

### Q5 — Is `deferred` a separate stage or a separate dimension?

FR-039 and SC-004 refer to "deferred" features, but FR-028's stage enum (`definition`, `spec_ready`, `engineering`, `review`, `validation`, `merge_ready`, `merged`, `drift_repair`) does not include it.

**Recommended:** Option A — add `deferred` as a new value to FR-028's stage enum. Matches the operator mental model ("FEAT-N is deferred, FEAT-M is merged" — both feel like stages, not flags) and minimizes downstream UI logic (badges, drift, project-card current-stage rendering all already handle stage values).

**Answer:** Q5: A

| Option | Description |
|--------|-------------|
| A | Separate stage in FR-028; add `deferred` to the enum. |
| B | Separate execution_status value in FR-028; reuse `not_started` or add a new status. |
| C | A new boolean attribute on Feature/Change (`is_deferred: bool`) orthogonal to stage. |
| D | Not a feature attribute at all; deferred features are simply absent from the active feature list and surface only in roadmap docs. |

---

### Q6 — Is `deferred` terminal, or can a feature be un-deferred?

If Q5 = A or B, this question applies. If Q5 = C or D, mark as "n/a".

**Recommended:** Option B — non-terminal. The word "deferred" connotes "for now, not forever". An un-defer transition (back to `definition` or `spec_ready`) preserves operator flexibility and avoids forcing operators to "recreate" a feature they had only paused.

**Answer:** Q6: B

| Option | Description |
|--------|-------------|
| A | Terminal — like `merged`. Un-deferring requires a new feature id. |
| B | Non-terminal — `deferred` can transition back to `definition` or `spec_ready` via an explicit un-defer action; no other transitions allowed from `deferred`. |
| C | Terminal with an explicit "revive" transition that resets stage but reuses the feature id. |
| n/a | If Q5 = C or D, this question does not apply. |

---

### Q7 — How does feature-range resolution (FR-039) treat `deferred` items?

The spec already says deferred and merged items are "called out as excluded". This question pins the rendering.

**Recommended:** Option A — excluded from the resolved list and explicitly annotated. Matches FR-039's existing language ("naming deferred and merged items separately"), supports SC-004 ("explicitly call out the excluded items"), and makes the rule symmetric with how `merged` is already handled.

**Answer:** Q7: A

| Option | Description |
|--------|-------------|
| A | Excluded from the resolved list with an explicit annotation (e.g. `FEAT-N (excluded: deferred)`); the master receives only the resolved list. |
| B | Included in the resolved list with a "deferred" warning; the master decides whether to act. |
| C | Excluded silently; deferred items do not appear in any list shown to operator or master. |

---

## After you answer

I will:
1. Append a `### Session 2026-05-23 (round 2)` block under the spec's existing `## Clarifications` section with each Q→A.
2. Apply the answers to the spec FRs directly (FR-028 for Q5/Q6, FR-039 for Q7, new FR-038a or revision for Q1–Q4).
3. Update the Codex prompt's F4 and F7 sections so the change Codex generates carries no guessed defaults.
