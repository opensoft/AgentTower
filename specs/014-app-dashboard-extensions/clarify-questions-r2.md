# Clarification Questions — FEAT-014 App Dashboard Extensions — Round 2 (post-impl-design)

**Path (canonical, top)**: `/workspace/projects/AgentTower-worktrees/014-app-dashboard-extensions/specs/014-app-dashboard-extensions/clarify-questions-r2.md`

**Session date**: 2026-05-24
**Spec under clarification**: `specs/014-app-dashboard-extensions/spec.md`
**Mode**: post-implementation-design Round 2 — lower-risk refinements (config tunability, future-version criteria, consumer scope, operator-guidance prose)
**Source**: NEEDS-CLARIFY-R2 items tagged across the 13 checklist files in `checklists/`
**Question count**: 7 (one per R2 item)
**Cap**: ≤ 25 per user-global rule (well under)

Reply with one of:
- The option letter for the recommended (or any) choice (e.g., `Q1: A`)
- `yes` / `recommended` to accept the recommendation
- A short free-form answer (≤ 5 words) where allowed

Answers should be written **into this same file** under the `## Answers` section below
(per the user-global "Shared File Path Coordination" rule — answers inline,
not in a separate file, not only in chat).

You can answer all 7 in one reply, e.g.:

```
Q1: A
Q2: recommended
Q3: <short answer>
...
```

## Answers

Q1: A
Q2: A
Q3: A
Q4: A
Q5: A
Q6: A
Q7: A

Notes:

- Keep `recently_skipped_window_ms` as a pure internal v1.1 constant with no daemon config, env var, CLI flag, or client request override.
- Future v1.x minors may raise `title` / `detail` caps additively but must not shrink them.
- Establish symmetric forward compatibility now: v1.1 daemon ignores unknown future request fields.
- Capability flags are for non-additive runtime behavior or cases where clients need pre-adaptation knowledge; plain additive read-side fields do not need flags.
- Treat v1.1 dashboard fields as a public read surface for all callers that pass the host-only gate, with FEAT-012 as primary but not sole consumer.
- Fixed templates plus T026 documentation are sufficient operator guidance for v1.1.
- The existing telemetry-not-audit assumption is enough for `recently_skipped_count`; no extra trend-analysis prohibition is needed.

---

## Q1. Daemon-config-file tunability of `recently_skipped_window_ms`  *(closes configuration CHK004)*

Clarifications R1 Q6 chose "not client-tunable in v1.1" for `recently_skipped_window_ms` but did not explicitly close daemon-config-file or env-var tunability. Is `300_000` ms a hard internal constant in v1.1, or can operators override it without bumping the contract version?

**Recommended:** Option A — Pure internal compile-time constant in v1.1. Not configurable via daemon config file, env var, CLI flag, or any other surface. Whether it becomes operator-tunable in a future minor is out of scope for FEAT-014. (Matches FR-022's "no new operator-facing configuration" posture and is the simplest implementation.)

| Option | Description |
|--------|-------------|
| A | Pure internal constant in v1.1; no operator-facing override of any kind. Future-minor tunability is deferred. |
| B | Operator-tunable via daemon config file (`~/.config/opensoft/agenttower/…`); not exposed on the wire. |
| C | Operator-tunable via env var override at daemon start. |
| D | Mixed — `recently_skipped_window_ms` is config-tunable; size caps and ring-buffer maxlen remain pure constants. |
| Short | Provide a different rule (≤ 5 words). |

---

## Q2. Future-raise of `title ≤ 128` / `detail ≤ 512` size caps  *(closes configuration CHK011)*

May a future v1.x minor (v1.2, v1.3, …) raise the `title` / `detail` size caps additively (clients tolerate larger values up to the new cap), or are these caps a permanent contract pin?

**Recommended:** Option A — Future v1.x minors MAY raise these caps additively. The v1.1 cap is a minimum-guaranteed maximum (clients of every v1.x version safely render strings within v1.1 caps); future clients may need to handle larger values. Caps MUST NOT be shrunk in any v1.x minor.

| Option | Description |
|--------|-------------|
| A | Future v1.x MAY raise caps additively; MUST NOT shrink. Clients tolerate larger values. |
| B | Caps are permanent v1 contract pins — no future v1.x may change them; only v2 major could. |
| C | Caps may only shrink (rejecting future additions); permanent floor at v1.1 values. |
| D | Defer — capping rules for future minors are out of scope for FEAT-014. |
| Short | Provide a different rule (≤ 5 words). |

---

## Q3. Symmetric forward compat — v1.1 daemon ignoring unknown future client-side request fields  *(closes versioning CHK009)*

Must a v1.1 daemon gracefully ignore unknown client-side request fields (symmetric forward compat), or is this out of scope since `app.dashboard` currently takes no request parameters?

**Recommended:** Option A — Yes. v1.1 daemon MUST gracefully ignore unknown request fields the client sends, mirroring the additive-minor model from the daemon → client direction. Establishes the convention before a future minor introduces request params.

| Option | Description |
|--------|-------------|
| A | Symmetric forward compat: daemon ignores unknown client request fields without error. Convention established now. |
| B | Reject unknown request fields with `validation_failed.unknown_field` (stricter; catches client bugs early). |
| C | Undefined in v1.1 — `app.dashboard` currently takes no params, so the rule isn't testable; defer until a v1.x minor adds a request field. |
| Short | Provide a different rule (≤ 5 words). |

---

## Q4. Future capability-flag criterion  *(closes versioning CHK011)*

FR-015 confirms v1.1 needs no capability flag because every v1.1 field is additive. What criterion would cause a future v1.x field to REQUIRE a capability flag?

**Recommended:** Option A — A capability flag is required when (a) the field gates on a non-additive runtime behavior change (e.g., the daemon optionally enables a new mutation surface), OR (b) clients need to know whether the daemon supports the field *before adapting their UI* (vs. ignoring-unknown after the fact). Plain additive read-side fields continue the v1.1 always-emit-and-clients-ignore-unknown pattern (no flag).

| Option | Description |
|--------|-------------|
| A | Flag required iff (a) non-additive runtime behavior change OR (b) clients need pre-adaptation knowledge. |
| B | Flag required for every new field in any future v1.x (strictest — overrides the additive-minor model). |
| C | Defer entirely — the future minor that introduces the first non-additive change defines its own criterion. |
| D | Flag required only when adding fields touches the queue / send-input / mutation surfaces (read-side never needs flags). |
| Short | Provide a different criterion (≤ 5 words). |

---

## Q5. Other v1.1 consumers beyond FEAT-012  *(closes integration CHK007)*

FEAT-012 is named as the primary consumer of the v1.1 dashboard fields. May other consumers (CLI `agenttower dashboard`, monitoring scripts, any future app) also rely on the same fields without additional contract changes?

**Recommended:** Option A — Yes, the v1.1 fields are public read surface for *anyone* who passes the host-only gate. FEAT-012 is the *primary* consumer but not the *sole* consumer. CLI / monitoring / future-app consumers receive the same contract guarantees. This matches FR-023 (auth inherited; uniform shape) and avoids creating a hidden "FEAT-012-only" carve-out.

| Option | Description |
|--------|-------------|
| A | Public read surface; FEAT-012 is primary but other consumers (CLI, monitoring, future apps) get the same contract guarantees. |
| B | FEAT-012 is the *sole* declared consumer in v1.1; other consumers MAY use the fields but get no explicit contract guarantee. |
| C | CLI `agenttower dashboard` is also explicitly in scope as a v1.1 consumer (add it to the spec); other consumers fall under A or B. |
| D | No other consumers in v1.1; explicitly scope to FEAT-012 only. |
| Short | Provide a different rule (≤ 5 words). |

---

## Q6. Per-code operator guidance prose  *(closes observability CHK009)*

The fixed `title` / `detail` templates in `contracts/closed-sets-v1_1.md` §Per-code title/detail Templates pin the prose the daemon emits per recommendation code. Does the SPEC need to mandate any additional operator-facing "next-step" documentation per code (separate from the templates), or are the templates plus T026 docs work sufficient?

**Recommended:** Option A — Templates + T026 docs are sufficient. The fixed `title` / `detail` templates already convey actionable guidance (e.g., `"{N} pane(s) are discovered but not yet registered with an agent. Adopt them to enable routing."`). T026 will produce the FEAT-011 cross-reference + per-code documentation block; that's editorial work, not a spec gate.

| Option | Description |
|--------|-------------|
| A | Templates + T026 docs are sufficient. No additional spec mandate. |
| B | Spec must mandate a per-code "next-step" entry in a separate operator handbook (e.g., `docs/dashboard-runbook.md`). |
| C | Per-code prose should be free-form per-deployment (override-able by operators); current template-pinning relaxes. |
| D | Defer to FEAT-012's operator-UX layer — FEAT-014 stops at template prose; FEAT-012 owns rendering + handbook integration. |
| Short | Provide a different rule (≤ 5 words). |

---

## Q7. Trend-inference prohibition on `recently_skipped_count`  *(closes observability CHK012)*

The spec already says `recently_skipped_count` is "telemetry, not durable audit history" (Assumptions). Should the spec add an explicit prohibition that operators MUST NOT use the count for trend / longitudinal analysis (given restart-reset + ring-buffer drop-oldest), or is the existing Assumption sufficient?

**Recommended:** Option A — Existing Assumption is sufficient. "Telemetry, not durable audit history" already communicates the constraint to operators reading the spec; adding an explicit "MUST NOT" doesn't add testable behavior. Belt-and-suspenders documentation is fine but not necessary at v1.1.

| Option | Description |
|--------|-------------|
| A | Existing "telemetry, not durable audit history" Assumption is sufficient. No additional explicit prohibition. |
| B | Add an explicit Assumption / Constraint: "operators MUST NOT use `recently_skipped_count` for trend / longitudinal analysis"; belt-and-suspenders for clarity. |
| C | Add a documentation MUST for the dashboard render to include a "since-restart" qualifier when displaying the count (UI-side render rule). |
| D | Out of scope for the spec; documentation concern only (T026 handles it). |
| Short | Provide a different rule (≤ 5 words). |

---

**Path (canonical, bottom)**: `/workspace/projects/AgentTower-worktrees/014-app-dashboard-extensions/specs/014-app-dashboard-extensions/clarify-questions-r2.md`

**Awaiting answers above under `## Answers`.** Once filled in, ping me (or re-invoke `/speckit-clarify`) and I'll fold these into `spec.md` as a new `### Session 2026-05-24-r2` block under the existing `## Clarifications` section, then update the affected FRs / contracts / data-model accordingly, and tick off the 7 R2 items in the checklists.
