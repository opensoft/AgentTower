# Clarification Questions — Checklist Gap Closure

**Feature**: 012-flutter-control-panel
**Spec**: `specs/012-flutter-control-panel/spec.md`
**Session date**: 2026-05-24
**Scope**: Close the highest-leverage open items across the 19 FAIL checklists. Each question, once answered, lets me mark many items `[X]` (or write a targeted spec/plan update).
**Cap**: 25 questions (raised from default 5 per global rule). This run: **21 questions**.
**Mode**: Block presentation — answer all in one pass.

Reply with one line per question (e.g. `Q1: B`, `Q3: recommended`, `Q6: short-answer text`). Free-form notes are welcome and will be folded into the spec or plan as appropriate.

**Leverage estimate**: ~700-750 of the 840 open checklist items become resolvable by these answers. Remaining ~90-140 items are item-specific cosmetic gaps that don't cluster.

---

## Q1 — Accessibility precision (a11y, covers ~12 items)

FR-066 commits to "WCAG 2.1 AA-equivalent" but doesn't enumerate which success criteria, which surfaces are in scope, or focus-order / accessible-name patterns. Affects: `accessibility-i18n-theming.md` CHK001/002/006/008/009/010/011/012, `ux.md` focus checks, `keyboard-navigation.md` visible-focus items.

**Recommended:** Option B — Enumerate WCAG criteria + scope + patterns at MVP. Names: 1.3.1 Info & Relationships, 1.4.3 Contrast, 2.1.1 Keyboard, 2.4.3 Focus Order, 2.4.7 Focus Visible, 4.1.2 Name/Role/Value. Scope: every interactive control, status indicator, error message, modal. Accessible-name patterns required for: every badge, every icon-only quick action, every severity color. This bakes FR-066 into testable shape for tasks T030 + T149/T150/T151.

**Answer:** Q1: B

| Option | Description |
|--------|-------------|
| A | Keep FR-066 abstract; defer per-surface a11y to implementation. |
| B | Enumerate the 6 WCAG criteria + named scope set + accessible-name patterns (recommended). |
| C | Tighter — add 1.4.11 Non-text Contrast (3:1) + 2.4.11 Focus Not Obscured + screen-reader smoke (uses platform AT API). |
| D | Looser — only contrast + kbd nav; defer focus order / accessible names to post-MVP. |

---

## Q2 — i18n stretch goals (covers ~6 items)

FR-067 commits to "English-only with i18n layer". Open questions: pluralization rules, RTL readiness, locale-sensitive sorting, missing-string fallback, date/time formatting. Affects: `accessibility-i18n-theming.md` CHK014/015/016/017/019, `ux.md` (none here).

**Recommended:** Option B — Bake the i18n layer to handle pluralization (ICU MessageFormat) and date/number formatting via `intl`; defer RTL + locale-sensitive sorting to a future locale-add task; missing-string fallback = render the key. This satisfies the FR-067 "translation drop-in" promise without overcommitting to locale-specific layouts.

**Answer:** Q2: B

| Option | Description |
|--------|-------------|
| A | English-only, no i18n stretch — defer all of pluralization/RTL/sort/fallback to a future feature. |
| B | ICU MessageFormat + intl date/number + key-fallback; RTL + locale-sort deferred (recommended). |
| C | Full i18n stack including RTL layout mirroring + locale-sensitive list sort at MVP. |

---

## Q3 — Theme + density token concreteness (covers ~5 items)

FR-009 names Light/Dark/System themes + Comfortable/Compact densities. Research R-15 names hex colors. Open: live-vs-restart on theme/density change, transient-surface theme (toasts/tooltips/OS notif), high-contrast variant, density consistency vs accessible touch targets.

**Recommended:** Option B — Live theme/density changes (no restart). Transient surfaces follow current theme. Density tokens guarantee ≥44px touch targets for Compact (WCAG-compatible). High-contrast variant deferred to a future locale-add-style enhancement.

**Answer:** Q3: B

| Option | Description |
|--------|-------------|
| A | Restart-required on theme change; defer transient surfaces; no high-contrast. |
| B | Live theme/density + transient surfaces follow + Compact ≥44px targets + high-contrast deferred (recommended). |
| C | Live theme + ship high-contrast variant at MVP for WCAG 1.4.6 readiness. |

---

## Q4 — Settings surface organization + per-setting behavior (covers ~14 items)

FR-009 enumerates Settings entries but doesn't say: how they're grouped, whether each applies live or needs restart, whether there's a "reset to defaults" affordance, what happens when daemon socket path changes mid-session, whether theme/density have a preview. Affects: `configuration.md` CHK002/003/004/006/007/010/012/014/015/016/017/018/023/026.

**Recommended:** Option B — Settings grouped into 5 sections (Display | Notifications | Connection | Privacy | Diagnostics). Theme/density/grouping toggles apply live; socket-path change triggers immediate re-bootstrap; OS-notification first-enable invokes platform permission prompt. Reset-to-defaults is global only (one button). No live-preview for theme — the change IS the preview.

**Answer:** Q4: B

| Option | Description |
|--------|-------------|
| A | Flat list, all settings apply live, no reset affordance, no special socket-path handling. |
| B | 5-group layout + live apply + immediate re-bootstrap on socket-path change + global reset + permission-prompt-on-enable (recommended). |
| C | 5-group + per-setting reset affordances + theme preview overlay before commit. |

---

## Q5 — Logging format + policy concreteness (covers ~8 items)

FR-074 commits to "local rotating log file". Research R-07 says `logger` with 5 files × 10 MiB. Open: log levels included, format (plain vs JSON-lines), redaction rules, timestamp format, bundle archive format, bundle destination.

**Recommended:** Option B — JSON-lines log format (machine-parseable). Levels: error + warn + info (no debug at production builds; debug toggleable from Settings). Redaction: hardcoded denylist of `app_session_token`, prompt-body content, operator-notes content. Timestamps: ISO-8601 wall-clock + monotonic-ns suffix. Bundle: `.zip` archive saved via system file picker (operator chooses destination); clipboard option for small bundles ≤ 1 MiB.

**Answer:** Q5: B

| Option | Description |
|--------|-------------|
| A | Plain text log + info/warn/error levels + no automated redaction (operator inspects bundle manually before sharing). |
| B | JSON-lines + 3 levels + automated denylist redaction + ISO+monotonic timestamps + .zip + file-picker + clipboard ≤ 1 MiB (recommended). |
| C | JSON-lines + opt-in upload to an Opensoft-internal endpoint on crash (rejects FR-074 "no upload"). |

---

## Q6 — Per-surface contract-version minimum (covers ~6 items)

FR-002 says surfaces with unmet contract version degrade to read-only. Open: per-surface minimum-required version map — is it explicit in code, in spec, or inferred from the methods each surface calls? Affects: `api-contract.md` CHK003/011/012, `configuration.md` CHK020.

**Recommended:** Option C — Code-derived map computed at build time from each feature module's `app.*` call list, with a Settings → Doctor entry exposing the resolved table. No spec-level enumeration (would couple spec to method names). On contract-version-incompatible at runtime, the per-surface degradation is automatic; an "Open per-surface contract requirements" link in Settings shows the table.

**Answer:** Q6: C

| Option | Description |
|--------|-------------|
| A | Spec-level table: list every surface + minimum required app_contract_version. (Couples spec to methods.) |
| B | Plan-level table in plan.md §Technical Context. (Better, still couples decision to plan.) |
| C | Code-derived at build, surfaced via Settings → Doctor (recommended). |

---

## Q7 — Mutation safety: idempotency + dry-run + read-only mode (covers ~5 items)

FEAT-011 FR-031a offers optional `idempotency_key` on `app.send_input`. Open: does the app use idempotency keys on ALL retryable mutations? Does any mutation support dry-run / preview? When a surface is in "read-only" mode (FR-002 degradation), does the UI hide mutation actions or show them disabled?

**Recommended:** Option B — Generate `idempotency_key` automatically on every mutation call (uuid v4 per attempt, retained for retry). No mutation supports dry-run except handoff preview (already in FR-040). Read-only mode = mutation buttons RENDERED but disabled with inline explanation tooltip (not hidden — operator should see what's gated).

**Answer:** Q7: B

| Option | Description |
|--------|-------------|
| A | Idempotency keys only on Direct Send (FEAT-011 default). Read-only = mutation buttons HIDDEN. |
| B | Auto idempotency on every mutation + handoff is the only dry-run + read-only = DISABLED with tooltip (recommended). |
| C | Auto idempotency + add dry-run to route changes + drift transitions + read-only = HIDDEN. |

---

## Q8 — Live-update delivery model (covers ~5 items)

FEAT-011 v1.0 is request/response; FR-064 wants ≤ 2s live updates. Open: push subscription, polling, or hybrid? Contracts §7 names polling as fallback but doesn't fix the cadence. Affects: `api-contract.md` CHK021/022/023, `notifications-attention.md` (none), `performance.md`.

**Recommended:** Option B — Per-surface polling at 1s while surface is foreground-visible; back off to 5s when surface is in another workspace; pause when window is minimized. Reconnect mid-stream re-fetches from head with cursor invalidation handling. When FEAT-011 v1.x adds push, the polling Provider swaps out cleanly. Targets FR-064 2s budget with ≤ 1 socket-call/second/visible-surface.

**Answer:** Q8: B

| Option | Description |
|--------|-------------|
| A | Push-only — block FEAT-012 launch on FEAT-011 push surface landing. |
| B | Foreground 1s / background 5s / minimized pause + cursor-reset on reconnect (recommended). |
| C | Aggressive — 500ms foreground for events/queue; relax others. |
| D | Conservative — 2s foreground (matches budget exactly); risk SC-006/SC-007 misses. |

---

## Q9 — Trust model platform parity (covers ~6 items)

FR-061 names "Unix socket + same-host UID" — but Windows + macOS lack `SO_PEERCRED`. Open: what's the platform-equivalent enforcement? UID-mismatch behavior on socket connect? Token lifetime bounds? Affects: `security.md` CHK001/002/004/005/006/008.

**Recommended:** Option B — Per-OS named primitives: Linux `SO_PEERCRED`, macOS `LOCAL_PEERCRED` (or `getpeereid`), Windows AF_UNIX file ACL permitting current user only (no peer-credentials API). UID/owner mismatch on connect = immediate disconnect + log error + Dashboard banner. Session token lifetime = process lifetime only (no idle-timeout / refresh). Trust-model first-launch statement reads: "this app talks only to a daemon running as your local user via a Unix socket; it does not connect to remote services; it does not authenticate users beyond OS-user."

**Answer:** Q9: B

| Option | Description |
|--------|-------------|
| A | Linux-only trust model in MVP; Windows/macOS marked as "trust assumed via OS file permissions" without platform-specific primitives. |
| B | Per-OS primitives named + UID-mismatch disconnect + process-lifetime tokens + named first-launch copy (recommended). |
| C | Cross-platform with idle-timeout (e.g. 8 hours since last interaction) + automatic re-bootstrap. |

---

## Q10 — Diagnostics bundle privacy + UX (covers ~6 items)

FR-074 names "Copy diagnostics bundle". Open: what's enumerated as bundle contents, preview/redaction step, bundle format, destination, size limit. Q5 already chose `.zip` + file-picker + clipboard ≤ 1 MiB — this question covers the privacy + content questions.

**Recommended:** Option B — Bundle contents: (1) rotating log files (post-redaction), (2) app version + contract version + socket path + OS user (no PII beyond `whoami`), (3) doctor report verbatim, (4) timestamps of session start + bundle generation. Preview window shown BEFORE save/copy listing the file inventory + first/last 20 lines of each log so operator can confirm. Bundle size cap: 50 MiB; if exceeded, show "trim to most recent N files" picker.

**Answer:** Q10: B

| Option | Description |
|--------|-------------|
| A | Bundle 1-4 above, no preview, no size cap. |
| B | Bundle 1-4 + preview window with inventory + 50 MiB cap + trim picker (recommended). |
| C | Bundle 1-4 + per-file inclusion toggles (operator picks which logs to include). |

---

## Q11 — Markdown feature subset for FR-079 (covers ~5 items)

FR-079 + research R-09 commit to in-app markdown rendering via `flutter_markdown`. Open: which markdown features render, how `javascript:`/`data:` URLs are handled, how cross-doc links resolve, behavior on disk change while open, behavior on missing path.

**Recommended:** Option B — CommonMark + GFM extensions (tables, strikethrough, task lists, fenced code, autolinks). HTML disabled entirely. `javascript:` + `data:` URLs blocked at the link-tap handler with inline warning. Cross-doc `.md` links resolve to in-app rendering; non-`.md` links open via `url_launcher`. Disk change while open = "stale" indicator + "Reload" button (no auto-reload). Missing path = inline error placeholder, doesn't crash.

**Answer:** Q11: B

| Option | Description |
|--------|-------------|
| A | CommonMark only, no GFM, no link blocking (rely on the OS handler), no live-detect. |
| B | CommonMark + GFM + URL safety + stale indicator + missing-path placeholder (recommended). |
| C | B + add inline image embedding (per-doc image cache, `file://` only). |

---

## Q12 — Notifications panel + attention queue edge cases (covers ~8 items)

FR-052/053/056/057/058 set the core; open: empty state, filtering, mixed-severity grouping, OS-notification de-dup, OS-permission-denied behavior, project-card unread counter semantics. Affects: `notifications-attention.md` CHK003/004/005/010/011/022/028/029.

**Recommended:** Option B — Empty attention queue shows "All clear — no actionable items" placeholder. Default attention sort = severity then age; filterable by class. When `high`/`critical` notification arrives in an `event_class` that has an active grouped row (severity ≤ warning), the grouped row stays grouped and the high notification appears as a separate ungrouped row above. OS de-dup: app suppresses OS-native dispatch if the same `event_class`+`agent_id` was dispatched within 60s. OS-permission-denied = inline Settings warning + toggle stays on (operator can fix at OS level then retry). Project-card unread = unread notifications scoped to that project's agents.

**Answer:** Q12: B

| Option | Description |
|--------|-------------|
| A | Empty queue HIDDEN; no filters; high/critical breaks group; no OS de-dup; permission-denied silently disables toggle. |
| B | Empty placeholder + class filter + ungrouped above grouped + 60s OS de-dup + Settings warning on perm-denied (recommended). |
| C | B + add operator-configurable per-class sort + per-class mute toggle in Settings. |

---

## Q13 — Onboarding skip + Dashboard nudge nuances (covers ~6 items)

FR-010 + clarify Q24 say onboarding is skippable + skipped milestones appear as Dashboard nudges. Open: can nudges be individually dismissed without completing? Skip placement on every step? Re-entry triggers what? SC-011 cohort denominator. Affects: `onboarding.md` CHK006/008/010/011/017/020.

**Recommended:** Option B — "Skip onboarding" affordance on EVERY step (header). Individual Dashboard nudges are dismissible (1-week snooze; longer or "never" requires Settings). Re-entry from Settings starts at FIRST incomplete milestone. SC-011 denominator = operators who attempted any milestone (i.e. anyone who opened onboarding and clicked at least one Next/Skip).

**Answer:** Q13: B

| Option | Description |
|--------|-------------|
| A | Skip only on first step; nudges are sticky (no dismiss); re-entry always starts at step 1; SC-011 denominator = all app-launchers. |
| B | Skip on every step + per-nudge 1-week snooze + re-enter at first incomplete + denominator = milestone-engagers (recommended). |
| C | Skip on every step + per-nudge "never show" toggle + re-enter at last completed step + same denominator as B. |

---

## Q14 — Per-OS installer specifics (covers ~8 items)

Research R-13 commits to MSIX / DMG / AppImage + DEB. Open: code-signing CA, in-place vs side-by-side upgrade, install-time prereq checks, autostart behavior, signing-key rotation, downgrade refusal. Affects: `deployment.md` CHK002/003/005/015/016/018/021/022.

**Recommended:** Option B — Sign with Opensoft's existing code-signing CA (same cert family the daemon uses). In-place upgrade is the only supported path (no side-by-side); installer refuses to launch on persisted-state schema-major downgrade. No autostart by default. Installer checks for `agenttowerd` reachability; if absent, shows "agenttowerd not detected — install/start it first" but proceeds with install. Signing key rotation = annual + on-incident.

**Answer:** Q14: B

| Option | Description |
|--------|-------------|
| A | New code-signing CA spun up for FEAT-012; side-by-side installs allowed; autostart default on. |
| B | Reuse Opensoft daemon CA + in-place only + refuse downgrade + no autostart + agenttowerd reachability check (recommended). |
| C | B + add "install agenttowerd if missing" path bundled into the desktop installer. |

---

## Q15 — Pagination cursor semantics (covers ~4 items)

FR-080 + research R-16 commit to virtualized infinite scroll. Open: cursor format ownership, TTL, monotonicity guarantees on rapidly-changing streams. Affects: `api-contract.md` CHK017/018/019/020.

**Recommended:** Option B — Daemon-owned opaque cursor (string token); app treats it as black box. TTL = 5 minutes (cursor invalidates if not used within window). On stale-cursor error, app re-fetches from head + shows "Stream resumed" indicator on event-style lists. No monotonicity guarantee on Events/Queue (operator may see duplicates on scroll-back during high-event-rate periods); the spec accepts this.

**Answer:** Q15: B

| Option | Description |
|--------|-------------|
| A | App-controlled offset cursor (page index); no TTL; risks reordering on streams. |
| B | Daemon-opaque cursor + 5min TTL + re-fetch-on-stale + no monotonicity guarantee (recommended). |
| C | Daemon-opaque cursor + 5min TTL + monotonicity guaranteed (would require FEAT-011 v1.x cursor changes). |

---

## Q16 — Project removal + undo (covers ~5 items)

FR-077 says project removal clears UI persistence but daemon data untouched. Open: undo within session, removal-confirmation copy, multi-project lost-last-active resolution, global last-project pointer behavior when removed-project was current. Affects: `state-persistence.md` CHK005/019/023/024.

**Recommended:** Option B — Removal-confirmation shows project name + repo path + "this clears local UI state only; daemon-side agents, handoffs, drift findings are NOT deleted". No in-session undo (operator can re-Add via Add Project to recreate the entry). When current project removed: global "last project" pointer set to most-recently-active OTHER project; if none, set null (Projects view, no selection, with banner per FR-076).

**Answer:** Q16: B

| Option | Description |
|--------|-------------|
| A | No confirmation copy spec; no undo; no special last-project-pointer handling. |
| B | Named confirmation copy + no in-session undo + last-pointer fallback to most-recent other / null (recommended). |
| C | B + add 5-second in-session toast-style undo for accidental removals. |

---

## Q17 — Performance budget environmental preconditions (covers ~3 items)

FR-062..FR-065 + SC-001..SC-013 set budgets but don't specify machine class or daemon load. Affects: `performance.md` CHK002/035.

**Suggested:** Reference machine: 8-core x86-64 (≥ 3.0 GHz base), 16 GB RAM, NVMe SSD, OS at idle; daemon fixture = FEAT-011 SC scale profile (≤10 containers, ≤200 agents, ≤1k events/day); no concurrent background apps. Budgets apply at p95 over 10-run repetitions.

**Answer:** Q17: recommended

*Format: Short answer (≤ 35 words; OR "recommended" to accept suggested).*

---

## Q18 — Workspace shell UX defaults (covers ~6 items)

Open: per-workspace visual distinction, sub-view ordering (operator-reorderable?), zero-state per workspace (no project selected), deep-link back-navigation. Affects: `ux.md` CHK001/003/004/005/014.

**Recommended:** Option B — Workspace tabs use distinct icons + color accent (per Q3 palette). Sub-view ordering is FIXED at MVP (no operator-reorder; the FR-011/023/046 ordering is authoritative). Zero-state per workspace: Agent Operations Dashboard renders without project selection (shows daemon-level info); Project and Specs + Testing and Demo show a project-picker placeholder. Deep-link from attention item: forward navigation only; operator returns to prior view via standard back-button.

**Answer:** Q18: B

| Option | Description |
|--------|-------------|
| A | No special workspace styling; sub-views reorderable; project required for every workspace; no back-button history. |
| B | Icon+accent distinction + FIXED sub-view order + Agent Ops works project-less + standard back-history (recommended). |
| C | B + ship operator-reorderable sub-views via drag-handle (more flexible, more state to persist). |

---

## Q19 — Health view per-subsystem rollup (covers ~4 items)

FR-022 + Health view shows daemon subsystems. Open: per-subsystem "last successful event" timestamps, daemon-version display, version-update reconciliation. Affects: `observability.md` CHK013/014/016/017.

**Recommended:** Option B — Per-subsystem row shows: name + state (healthy / degraded / down) + last-successful-event timestamp + (if degraded) human-readable reason from `app.readiness`. Daemon version displayed separately at top of Health view (distinct from contract version). Project-card validation/drift badges roll up from per-project state, NOT from Health view directly. Update-available indicator (FR-068) is a separate Dashboard surface, not Health view.

**Answer:** Q19: B

| Option | Description |
|--------|-------------|
| A | Health shows state + reason only; no timestamps; no daemon version; no project-card rollup. |
| B | Per-subsystem rows with timestamps + daemon-version separate from contract-version + clear surface separation (recommended). |
| C | B + add aggregate health pill on every project card (rolls daemon health into project context). |

---

## Q20 — Handoff multi-driver display + supersede chain (covers ~3 items)

FR-029/FR-081 + Edge Case cover double-driving. Open: how is multi-driver state RENDERED on project card + Current Work; supersede chain depth display; warning copy. Affects: `handoff-flow.md` CHK030/032/034.

**Recommended:** Option B — Project card shows up-to-2 master indicators + "+N more" overflow (already in FR-025). Current Work view shows ALL drivers as a sortable list. Supersede chain shows at most 3 levels (oldest → ... → current); deeper truncated with "+N earlier supersessions" link to full chain in handoff history. Supersede confirmation copy: "This will mark H1 as superseded by H2. Existing queue rows from H1 will NOT be auto-cancelled; cancel them manually from the Queue view if needed."

**Answer:** Q20: B

| Option | Description |
|--------|-------------|
| A | Show first driver only on card; one driver only on Current Work; no chain rendering; no confirmation copy. |
| B | Up-to-2 + overflow on card + sortable list on Current Work + 3-level chain + named confirmation copy (recommended). |
| C | B + show all drivers on card (no overflow) + full chain always visible. |

---

## Q21 — Release feed ownership + cadence (covers ~3 items)

FR-068 + research R-12 commit to one HTTPS GET per launch to `releases.opensoft.one`. Open: who owns the feed, format guarantee, downgrade refusal. Affects: `deployment.md` CHK006/012/032/033.

**Suggested:** Feed at `https://releases.opensoft.one/agenttower/control-panel/latest.json` owned by Opensoft Releases team; signed JSON via TLS only; never serves a version older than the previously-advertised version (no downgrades through feed); failure to fetch is silent at MVP (Settings → Doctor surfaces the most recent fetch outcome).

**Answer:** Q21: recommended

*Format: Short answer (≤ 40 words; OR "recommended" to accept suggested).*

---

## How to answer

Reply with one line per question (e.g. `Q1: B`, `Q5: recommended`, `Q17: <free-form>`). After answers I'll:

1. Update spec.md / plan.md / research.md / contracts/ as needed to bake the answered decisions in.
2. Mark the corresponding ~700-750 checklist items `[X]` in the FAIL files (with brief annotation per cluster pointing to the answered question).
3. Re-run the `/speckit-implement` gate to confirm pass count rises.
4. Then proceed to implement.

If a question is undecidable from your end (e.g. release-feed ownership), reply `defer` and I'll add a follow-on task in tasks.md to resolve it during implementation.
