# Clarify Questions — FEAT-013 Pre-Implement Walk (Round 4)

**Session:** 2026-05-24 (pre-implement walk)
**Spec:** [spec.md](./spec.md)
**Walk artifact:** [checklists/CHECKLIST_WALK.md](./checklists/CHECKLIST_WALK.md) — 503 incomplete items bucketed into 383 RESOLVED / 66 DEFERRED / 54 OPEN; the 54 opens collapse to 8 distinct clarify topics.
**Reply format:** `1: A, 2: recommended, 3: ...` / `all recommended` / `recommended except N: X` / short free-form answer (≤5 words) for any item.

---

## Q1. Per-step timeouts + retry policy (Topic A)

The create-layout pipeline has four stages (pane_create / launch_command / registration / log_attach). FR-013 enumerates `failed_stage` values but the spec is silent on (i) how long the daemon waits at each stage before transitioning to `failed`, and (ii) whether transient failures retry. Tests can't be deterministic without this.

**Recommended:** Option A — single 30s per-stage timeout + 2x retry on transient failures keeps tests deterministic, gives operators predictable failure latency, and fits comfortably inside SC-001's 2-minute budget.

| Option | Description |
|--------|-------------|
| A | Per-stage timeout = 30s; transient failures retry 2x with 1s / 2s exponential back-off; non-recoverable failures transition immediately to `failed`. |
| B | No per-stage timeouts; rely on FR-022's 5-minute TTL sweep as the only deadline; no retries (operator-driven recreate). |
| C | Per-stage timeouts vary (10s `pane_create`, 30s `registration`, 5s `log_attach`); retry 1x with 2s back-off on transient failures. |

---

## Q2. Partial-layout-failure rollback (Topic B)

When one pane fails mid-create-layout (e.g., `launch_command` exits immediately), what happens to the **other** in-flight panes in the same layout?

**Recommended:** Option A — each pane completes to its natural lifecycle state; the layout's aggregate state (per data-model.md "ManagedLayout lifecycle") reflects the worst child. Matches the "leaves a recoverable lifecycle state" wording in FR-013 / US1 AS-3 and avoids destroying working panes.

| Option | Description |
|--------|-------------|
| A | Other in-flight panes continue to natural completion; layout state is derived per data-model.md aggregation rules; no cascade-kill. |
| B | First failure triggers cascade-kill of all in-flight panes in the layout; layout lands in `failed`; operator recreates the whole layout. |
| C | Operator-configurable per template (strict / lenient flag in the template YAML). |

---

## Q3. Event redaction policy (Topic C)

Lifecycle event payloads (FR-015 + R11 catalog) include launch-command argv, env vars, working_dir. These ride the indefinite-retention JSONL audit (FR-021). What should be redacted?

**Recommended:** Option A — redact env vars by key-match against a documented closed set (`*TOKEN*`, `*SECRET*`, `*KEY*`, `*PASSWORD*`, case-insensitive); leave argv + working_dir unredacted. Minimal + defensible; operator-visible failure diagnostics stay intact.

| Option | Description |
|--------|-------------|
| A | Redact env vars whose key matches `*TOKEN*` / `*SECRET*` / `*KEY*` / `*PASSWORD*` (case-insensitive); command argv + working_dir unredacted. Redaction list documented as a closed set in spec. |
| B | Redact all env vars (no exposure regardless of name) AND redact working_dir paths; command argv unredacted. |
| C | No redaction in MVP; record an Assumption that operator is trusted; defer redaction to a later security-hardening feature. |

---

## Q4. Operator-input validation (Topic D)

Operator supplies `tmux_session_name` (M1), `label_pattern` (template YAML), and `launch_command_overrides` map keys. Spec is silent on allowed characters / length. tmux can break or display strangely with control chars; rejection at the API boundary is cleaner.

**Recommended:** Option A — practical character set covering all real-world session/label names without being draconian; length cap 64 fits within tmux's display surface.

| Option | Description |
|--------|-------------|
| A | Allow `[A-Za-z0-9_.-]` (POSIX-portable, plus dots/hyphens), length ≤ 64; reject control chars (\x00–\x1f, \x7f); otherwise `validation_failed`. |
| B | Reject only control chars (\x00–\x1f, \x7f); otherwise unrestricted (operator's problem if tmux breaks). |
| C | Strict allow-list `[A-Za-z0-9_]` only, length ≤ 32 — defensive / smallest attack surface. |

---

## Q5. Event stream ordering guarantees (Topic E)

FR-015 says "emit observable lifecycle events" but no ordering guarantee. Consumers (FEAT-008 ingestion, FEAT-013 detail surfaces, the M3 detail polling path) need a documented order to design correctly.

**Recommended:** Option A — per-pane FIFO + per-layout FIFO matches the natural state-transition ordering and is achievable with FEAT-008's JSONL serialized audit + the per-container serializer. Cross-pane / cross-layout strict ordering is impractical and not needed by any current consumer.

| Option | Description |
|--------|-------------|
| A | Per-pane FIFO + per-layout FIFO (events for the same pane / same layout appear in transition order); cross-pane / cross-layout is best-effort timestamp. |
| B | Strict global FIFO across all events (single serialized stream). |
| C | Best-effort only; consumers MUST sort by timestamp + sequence number. |

---

## Q6. Concurrent recreates of same predecessor (Topic F)

Two `recreate_pane(predecessor_pane_id=X)` calls in flight. R10 covers create-layout idempotency-key replay, but `recreate_pane` doesn't have an equivalent rule. Branch (both create successors with `predecessor_id=X`) or block (one wins)?

**Recommended:** Option A — explicit error code is easier to handle on the operator surface than a hidden branch; matches the "no chain forking" intent in research §R3 (predecessor_id is a self-FK, not a graph).

| Option | Description |
|--------|-------------|
| A | First call wins; second receives `managed_pane_concurrent_recreate` with the in-flight successor's `pane_id` in `details`. Operator can poll. |
| B | Both replay if `idempotency_key` matches; otherwise both create separate successors with `predecessor_id=X` — chain branches into a tree. |
| C | Second call blocks on a per-predecessor lock until the first completes; then returns the first's result (transparent merge). |

---

## Q7. Spec-level scale limits (Topic G)

Plan §Scale informally says "≤10 bench containers, ≤4 managed layouts per container, ≤4 panes per layout". Should this be promoted to a spec FR with a quantified cap and a closed-set error code, or stay plan-informational?

**Recommended:** Option A — testable system property; explicit operator-facing error at the cap; matches the FR-019 / FR-022 / FR-023 style of "MVP bounded with specific actionable error".

| Option | Description |
|--------|-------------|
| A | Add **FR-025**: System MUST support up to 40 concurrent managed layouts per daemon (≤4 per bench container × ≤10 bench containers); the 41st returns `managed_layout_capacity_exceeded`. |
| B | Add to §Assumptions only ("MVP supports ≤40 concurrent managed layouts; behavior beyond that is undefined"); no FR, no error code. |
| C | Keep informal in plan §Scale; spec stays silent. |

---

## Q8. First-run operator-config experience (Topic H)

Operator overrides under `~/.config/opensoft/agenttower/managed_templates/*.yaml` and `…/launch_commands/*.yaml` (FR-024). On first daemon install: what does the operator see?

**Recommended:** Option A — least-surprise + matches Principle I "no writes to user's home unprompted". `examples/` in the repo (T003 already creates it) serves as the discoverable reference set; operators copy into their override dirs when they want overrides.

| Option | Description |
|--------|-------------|
| A | Daemon does NOT auto-create files. Built-in templates / profiles ship in code; override dirs created empty if missing. `examples/` directory under the repo ships sample YAMLs as documentation references (per T003). |
| B | Daemon auto-creates override dirs AND seeds one example YAML each (`managed_templates/1m+2s.example.yaml`, `launch_commands/example.yaml`) so the operator has a starting point. |
| C | Document override paths in `docs/managed-sessions.md` but do NOT auto-create directories or files; rely on operator to create both. |

---

## Answers

1: A

2: A

3: A

4: A

5: A

6: A

7: A

8: A

Notes:

- Use 30 seconds per create-layout stage with two transient retries at 1s / 2s backoff; non-recoverable failures fail immediately.
- Do not cascade-kill other panes when one pane fails; each pane reaches its natural lifecycle state and layout state derives from the worst child.
- Redact sensitive environment variables in retained lifecycle events using the documented key-match closed set; leave argv and working_dir unredacted for operator diagnostics.
- Validate operator-provided session names, label patterns, and launch-command override keys with `[A-Za-z0-9_.-]`, length <= 64, and no control characters.
- Guarantee per-pane FIFO and per-layout FIFO lifecycle-event ordering; cross-pane and cross-layout ordering is best-effort by timestamp.
- Prevent recreate-chain forking: concurrent recreate on the same predecessor returns `managed_pane_concurrent_recreate` with the in-flight successor id.
- Promote the MVP managed-layout scale envelope into a testable FR: up to 40 concurrent managed layouts per daemon, with `managed_layout_capacity_exceeded` for the next create.
- On first run, do not auto-seed user config files. Built-ins live in code, override dirs may be empty, and repo examples document optional YAML overrides.

## Items deferred without clarification

The walk identified ~12 additional items that are operator-of-implementation-level decisions or post-MVP polish. They are NOT in this clarify round; reasonable implementer defaults are documented inline below for the record:

- **Circuit-breaker / back-off** (error-handling.md CHK024) — post-MVP polish; FR-022 TTL sweep is the effective ceiling.
- **Metrics / SLIs / trace IDs** (observability.md CHK006/007/010) — deferred to a later observability feature; tasks T054/T055/T056 verify SC-001/008/009 via timed integration tests.
- **Cascading failure sequences** (error-handling.md CHK018) — pane-local; FR-013 + FR-019 cover the atomic failure surface.
- **Max retries cap** (idempotency.md CHK012) — FR-022 5-minute TTL is the effective cap.
- **Layout-level remove cascade** (idempotency.md CHK005) — no `app.managed_layout_remove` in MVP; operator removes panes one by one.
- **Config reload semantics** (configuration.md CHK010) — restart-only for MVP; document as Assumption.
- **Tmux server selection** (configuration.md CHK017) — default `~/.tmux-shared` socket via FEAT-004's existing channel; no FEAT-013 override.
- **Lock release on operator disconnect** (concurrency.md CHK006) — Python `asyncio.Lock` releases naturally on task cancellation; implementer concern.
- **Per-stage SC-001 decomposition** (performance.md CHK001) — Q1's per-stage timeout (Option A) implicitly decomposes; no separate SC.
- **Tmux async ordering** (concurrency.md CHK013) — implementer-side; `tmux_create` waits for command return before recording state.
- **Daemon upgrades with in-flight layouts** (deployment.md CHK008) — covered by FR-020 reconcile; same logic as restart.
- **Post-deploy verification** (deployment.md CHK010) — SC-008 + SC-009 + the recovery events themselves are the verification.

---

## How to reply

- `1: A, 2: recommended, 3: B, ...`
- `all recommended` to accept every recommendation
- `recommended except 3: B, 6: C` to accept recommendations with overrides
- For any question, supply a short free-form answer (≤5 words) instead of an option letter

After your replies I will:

1. Apply each accepted answer to spec.md as a new `### Session 2026-05-24 (pre-implement walk)` Clarifications sub-session.
2. Add the implied new FRs (e.g., FR-025 scale limit if Q7=A), wording amendments (Q1 timeouts, Q2 rollback, Q3 redaction, Q4 validation, Q5 ordering, Q6 concurrent-recreate, Q8 first-run), and the corresponding closed-set error codes / `failed_stage` annotations / Assumptions.
3. Update the downstream artifacts (research, data-model, contracts, tasks) that need to reflect the new decisions.
4. Re-run a quick `/speckit.analyze` consistency check.
5. Then it's safe to launch `/speckit.implement` (the deferred-items list above will be inlined into the spec as Assumptions or out-of-scope notes so implementers know defaults are intended).
