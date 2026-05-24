# Phase 0 Research — FEAT-012 Flutter Desktop Control Panel

**Status**: All technical-context decisions resolved. No remaining NEEDS CLARIFICATION.
**Date**: 2026-05-23
**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

This document records the technology-choice decisions that the spec deliberately deferred to planning and that the implementation will rely on. Each decision lists what was chosen, why, and what was considered and rejected. Decisions are grouped by tech-stack area.

## R-01 — Flutter / Dart version

**Decision**: Flutter 3.27 stable (Dart 3.5+), pinned via FVM (`apps/control_panel/.fvm/fvm_config.json`) and `pubspec.yaml` lower bounds.

**Rationale**:
- 3.27 is the current LTS-aligned stable as of 2026 Q2 with mature Windows/macOS/Linux desktop support (multi-window, OS notifications, Material 3, impeller for macOS).
- Pinning via FVM gives the dev team and CI a single source of truth without forcing system-level Flutter installs.

**Alternatives considered**:
- Latest beta — rejected: spec calls for "stable" desktop targets, not bleeding-edge.
- Flutter 3.16 (older LTS-ish) — rejected: missing several desktop a11y improvements needed for FR-066.

## R-02 — State management

**Decision**: `flutter_riverpod` 2.x.

**Rationale**:
- Provider-graph model fits the spec's data flow (one daemon connection → many derived projections per workspace).
- Strong DI story for the mock-daemon test harness (every Riverpod provider can be overridden in tests without singletons).
- `StreamProvider` and `AsyncNotifier` map cleanly to FEAT-011's request/response semantics and to the live-update surfaces (FR-064).

**Alternatives considered**:
- `flutter_bloc` — rejected: heavier boilerplate per surface; the app has many small surfaces (FR-011, FR-023, FR-046 sub-views) that don't benefit from BLoC's event/state ceremony.
- Built-in `ChangeNotifier` / `InheritedWidget` — rejected: scales poorly for the cross-workspace project switcher (FR-007) and global banners (FR-002 contract-version).
- `signals_flutter` — rejected: too new; spec values stability over ergonomic novelty.

## R-03 — Immutable models + JSON codegen

**Decision**: `freezed` + `freezed_annotation` for sealed/data classes; `json_serializable` + `json_annotation` for `fromJson`/`toJson`. `build_runner` for codegen.

**Rationale**:
- FEAT-011's response envelopes (`{ok, app_contract_version, result|error}`) and ~32 method response shapes need strict, exhaustive typing. Freezed gives copyWith, equality, and pattern matching with one annotation.
- The 27-entry FEAT-011 closed-set error vocabulary becomes a sealed class with one variant per code — exhaustive `switch` on errors is enforced by the compiler.

**Alternatives considered**:
- `built_value` — rejected: heavier, less idiomatic in modern Flutter.
- Hand-rolled `fromJson` — rejected: 32 methods × ≥7 entity types is a maintenance trap.
- `dart_mappable` — rejected: smaller community, less integration with Riverpod patterns in scope.

## R-04 — Unix-socket client implementation

**Decision**: Use the built-in `dart:io` `Socket.connect(InternetAddress(<socket-path>, type: InternetAddressType.unix), 0)`. Hand-roll newline-delimited JSON framing on top, enforcing FEAT-011 FR-003a (per-line 1 MiB request cap, 8 MiB response cap) and FR-003b (UTF-8, `\n`-terminated, no `\r` / `\x00`, no trailing content).

**Rationale**:
- Dart's `Socket` API has supported Unix-domain sockets on Linux and macOS since Dart 2.8 and Windows 10 1803+ (Windows added AF_UNIX support natively).
- Avoids any third-party RPC framework, keeping the dependency surface minimal and the wire contract explicit (FEAT-011 SC-006 — the daemon-side test asserts no non-local socket; the app side mirrors with FR-001 / SC-009).

**Alternatives considered**:
- gRPC over Unix socket — rejected: FEAT-011 is plain newline-delimited JSON; adopting gRPC would duplicate FEAT-011's contract surface.
- JSON-RPC 2.0 library — rejected: FEAT-011 uses its own envelope shape (`{ok, app_contract_version, result|error}`), not JSON-RPC 2.0's `{jsonrpc, id, result|error}`.
- `package:dart_io_socket` shim — rejected: built-in `dart:io` already handles AF_UNIX on every supported OS.

## R-05 — Local UX-state persistence

**Decision**: Single JSON file at `<app-data>/agenttower-control-panel/ux-state.json`, atomic-rename writes, schema-versioned (`{"schema_version": 1, "ux_state": {...}}`).

**Rationale**:
- FR-069 enumerates the persisted set; the data is small (geometry + theme + density + a handful of toggles + per-view sort/filter scoped per-project + onboarding milestones). A JSON file is the simplest store that meets the requirement.
- Schema-versioned envelope lets FR-070's "compatible app launch" check be a single major-comparison.
- Atomic-rename writes (`write → fsync → rename`) avoid corrupt partial writes if the OS kills the app mid-write (FR-082 immediate close case).

**Alternatives considered**:
- SQLite via `sqflite_common_ffi` or `drift` — rejected: no relational queries needed; persisted set is flat.
- `Hive` / `Isar` — rejected: heavier than required; reactive-DB features are unused.
- `shared_preferences` — rejected: cannot represent nested per-project per-view sort/filter cleanly; OS-specific backends complicate FR-061a per-OS-user isolation reasoning.

## R-06 — App data directory per OS

**Decision**: Resolve via `path_provider`'s `getApplicationSupportDirectory()` on each OS, with the application name `agenttower-control-panel` joined as a subdirectory.

| OS | Path pattern |
|---|---|
| Linux | `$XDG_DATA_HOME/agenttower-control-panel/` (typically `~/.local/share/agenttower-control-panel/`) |
| macOS | `~/Library/Application Support/agenttower-control-panel/` |
| Windows | `%LOCALAPPDATA%\agenttower-control-panel\` |

**Rationale**:
- Each path is the OS-blessed per-user application-data location, satisfying FR-061a per-OS-user isolation.
- Sub-paths inside: `ux-state.json` (FR-069), `logs/` (FR-074).

**Alternatives considered**:
- `getApplicationDocumentsDirectory()` — rejected: documents directories are operator-visible / iCloud-syncable, inappropriate for app state.
- Per-OS hand-rolled paths — rejected: `path_provider` already handles edge cases (portable mode on Windows, XDG fallbacks on Linux).

## R-07 — Logging

**Decision**: `logger` 2.x with a custom `RotatingFileOutput` writing to `<app-data>/agenttower-control-panel/logs/control-panel.log.<N>` with 5-file × 10 MiB rotation.

**Rationale**:
- `logger` is a thin Dart logging package with pluggable outputs.
- FR-074 requires a rotating local log; rotation policy is fixed in code, not user-configurable.
- Per FR-074 + FR-061a, the log path is per-OS-user. File permissions are inherited from the OS-user app-data directory; no app-side permission code is needed.

**Alternatives considered**:
- `package:logging` (Dart core) — rejected: no rotation; would require hand-rolling.
- `talker` — rejected: heavier than required; brings UI dependencies.
- Cloud telemetry (Sentry, etc.) — rejected outright by FR-074 ("MUST NOT upload any diagnostics, telemetry, or logs to any remote service").

## R-08 — Internationalization

**Decision**: `flutter_localizations` + `intl` + ARB source files under `apps/control_panel/assets/l10n/`. MVP ships `en.arb` only. Code generation via `flutter gen-l10n` driven by `l10n.yaml`.

**Rationale**:
- This is the Flutter-blessed i18n stack and satisfies FR-067's "single localization layer such that adding a locale is a translation drop-in".
- All user-facing strings are routed through generated `AppLocalizations.of(context).…` accessors; no hard-coded strings in widget code.

**Alternatives considered**:
- `easy_localization` — rejected: maintenance status less stable than the official Flutter pipeline.
- `slang` — rejected: type-safe but smaller community and more tooling complexity for the MVP locale count.

## R-09 — Markdown rendering (FR-079)

**Decision**: `flutter_markdown` 0.7.x with a custom CSS-like style sheet aligned to the FR-009 theme + density tokens.

**Rationale**:
- Mature, supports the markdown feature set the project uses (headings, fenced code, tables, links, images).
- Permits a custom link tap handler so internal links open in-app while external links go through `url_launcher` (FR-079).
- Renders safely: HTML is disabled by default; the app extends this restriction to forbid `javascript:` and `data:` URLs at the link-tap handler (per `security.md` checklist CHK017).

**Alternatives considered**:
- `markdown_widget` — rejected: smaller community; renders differently across Flutter versions.
- Embedded webview (via `webview_flutter`) — rejected: pulls in browser-trust-model surface explicitly avoided by spec (Out of Scope: web app); adds packaging weight.
- Plain-text rendering — rejected: FR-079 requires markdown rendering for `.md` files in-app.

## R-10 — OS-native notifications (FR-058)

**Decision**: `local_notifier` 0.1.x for Windows + macOS + Linux dispatch.

**Rationale**:
- Cross-platform, no Microsoft Store dependency for Windows (uses `notify` shell on Windows 10+, `NSUserNotification` on macOS, `notify-send` / freedesktop.org on Linux).
- Opt-in toggle drives whether dispatch happens; default off per FR-058.
- Severity ≥ `high` is the only level that triggers OS-native notifications when opted in (per FR-058 + US6 §5).

**Alternatives considered**:
- `flutter_local_notifications` — rejected: oriented toward mobile (Android/iOS); desktop support varies.
- Per-platform plugins — rejected: triples maintenance cost for marginal UX benefit at MVP.

## R-11 — Window geometry + single-window invariant

**Decision**: `window_manager` 0.4.x for window size/position capture, restore, and platform-uniform window-close handling (matching FR-082's immediate-close behavior).

**Rationale**:
- Persists window geometry to FR-069's UX state file on resize / close.
- Restores within FR-062's 2-second Dashboard-readable budget on cold start.
- Enforces single-window (FR-010 / Assumption) by refusing additional `WindowController` creation.

**Alternatives considered**:
- `bitsdojo_window` — rejected: focused on custom title bars (out of scope for MVP).
- Flutter's built-in window APIs — rejected: too low-level for the persistence-across-restart story.

## R-12 — Release-feed / update indicator (FR-068)

**Decision**: HTTPS GET to a single JSON feed at `https://releases.opensoft.one/agenttower/control-panel/latest.json`, fetched once per app launch via `dart:io`'s `HttpClient`. Result drives the in-app "update available" indicator and the link to the release page.

Feed format:

```json
{
  "version": "1.2.3",
  "channel": "stable",
  "released_at": "2026-05-19T12:00:00Z",
  "release_notes_url": "https://releases.opensoft.one/agenttower/control-panel/1.2.3",
  "min_supported_version": "1.0.0"
}
```

**Rationale**:
- Single GET, no SDK, no telemetry payload (the request is one-way: app fetches; daemon doesn't return identifying data).
- Schema is forward-compatible (unknown fields ignored per the same additive-evolution policy FEAT-011 follows).
- Failure to fetch is silent at MVP — the indicator simply does not appear. The Settings → "Doctor" check (FR-009) can include a feed-reachability probe.

**Alternatives considered**:
- Sparkle / Squirrel / electron-updater — rejected: implies auto-update, which Q3 / FR-068 explicitly disallows ("MUST NOT auto-download or auto-install updates").
- Per-OS app-store distribution — rejected: explicitly out of scope at MVP per Q3.
- GitHub Releases API — rejected: rate limits, ties product to a specific hosting provider.

## R-13 — Packaging per OS

**Decision**:

| OS | Format | Signing | Tool |
|---|---|---|---|
| Windows | MSIX (sideload) | EV code-signing certificate | `msix` package + signtool |
| macOS | `.dmg` | Apple Developer ID + notarization + hardened runtime | `flutter build macos` + `create-dmg` + `notarytool` |
| Linux | `.AppImage` (primary) + `.deb` (unofficial) | GPG signing of release artifacts | `appimagetool` + `dpkg-deb` |

Snap, Flatpak, Microsoft Store, and Mac App Store are explicitly deferred (Q3).

**Rationale**:
- Each format is the most operator-installable for its OS without store-account friction.
- All three formats support signed-installer integrity (CHK002 / CHK003 / CHK025 in `security.md`).
- Signing keys live in the Opensoft release infrastructure, not in the repo.

**Alternatives considered**:
- Single cross-platform installer (Tauri-style) — rejected: doesn't apply to Flutter.
- `zip` distribution — rejected: no signing chain → fails CHK002 / CHK003.

## R-14 — Operator-action latency-logging threshold (spec F15 deferred)

**Decision**: 200 ms p95 — actions that exceed this threshold log a single entry at INFO level with the action name, latency, and outcome.

**Rationale**:
- 200 ms is the perceptual boundary above which an action "feels delayed" in desktop UX literature.
- p95 (not mean) catches operationally-relevant tail latencies without flooding logs on warm/hot paths.
- The threshold is fixed in code at MVP; if Settings exposes a tuner later, it ships behind a flag.

**Alternatives considered**:
- No threshold (log every action) — rejected: log volume would obscure errors.
- 500 ms — rejected: too lax; misses the SC-006 (2 s) and FR-064 (2 s) class of regressions.

## R-15 — Severity color palette + a11y mapping

**Decision**: Four-stop palette aligned with the FR-052 attention queue and FR-025 project-card badges; every severity carries a unique icon + a unique text label in addition to color (so colorblind operators receive equivalent info per FR-066).

| Severity | Light theme color | Dark theme color | Icon | Text label |
|---|---|---|---|---|
| `info` | `#3478F6` (blue 60) | `#5B9DFF` | `info_outlined` | "Info" |
| `warning` | `#E68A00` (amber 60) | `#FFB54C` | `warning_amber_outlined` | "Warning" |
| `high` | `#D93D2A` (red 60) | `#FF7059` | `priority_high` | "High" |
| `critical` | `#7A1A18` (red 90) | `#B33A2B` | `error` | "Critical" |

All four colors meet WCAG AA 4.5:1 against the corresponding theme background.

**Rationale**:
- Aligns FR-033 drift severity, FR-052 attention queue severity, and FR-025 validation/drift badges into one palette so the operator builds one mental model.
- Icon + label redundancy means the color is a third signal, not the only signal — satisfies FR-066.

**Alternatives considered**:
- Material 3 default semantic colors only — rejected: Material's "error" container is the same for `high` and `critical`, collapsing two distinct severities.
- Per-workspace palette — rejected: explicitly inconsistent with the spec's cross-surface severity unification (`requirements.md` CHK021).

## R-16 — Pagination strategy + cursor handling

**Decision**: Virtualized infinite scroll (per FR-080) backed by FEAT-011 cursors. Page size = FEAT-011 default (50). On daemon restart between requests, a stale cursor returns the FEAT-011 `stale_cursor` (or equivalent closed-set error from the FEAT-011 27-code set); the app reacts by re-fetching from the head of the stream and showing a "stream resumed" indicator on event-style lists.

**Rationale**:
- Aligned with FEAT-011's stated default (50) and cap (200) per FR-020a. The app never asks for `limit > 50` at MVP.
- "Jump to most recent" affordance (FR-080) drops cursor state and re-fetches head — simpler than maintaining an absolute position.

**Alternatives considered**:
- Explicit page controls — rejected by FR-080.
- Server-side push subscriptions — rejected: not part of FEAT-011's request/response surface at v1.0.

## R-17 — Test harness: mock daemon

**Decision**: A Python script at `apps/control_panel/test_harness/mock_daemon/server.py` that listens on a temp Unix socket, speaks the FEAT-011 `app.*` envelope (per the FEAT-011 contract docs at `specs/011-app-backend-contract/contracts/`), and is parameterized by a JSON fixture file specifying which methods return which payloads (including error codes).

**Rationale**:
- Reusing Python keeps the harness aligned with the real daemon implementation language and lets the FEAT-011 fixture files (`tests/contract/test_app_*` in the daemon repo) be reused or referenced.
- The harness is per-test (each test spawns a fresh socket) so there is no cross-test state pollution.
- CI can run the harness on Linux, macOS, and Windows runners (Windows AF_UNIX support is needed; supported on Windows 10 1803+).

**Alternatives considered**:
- Pure-Dart in-process fake — rejected: would not exercise the wire-framing strictness (FR-003a/b) we want to test on every change.
- Live daemon as the harness — rejected: too heavy for unit + widget tests; live daemon is reserved for the manual QA pass and the integration-test smoke.

## R-18 — Crash recovery & error boundaries

**Decision**: Riverpod `AsyncValue` for every async surface; the surface renders explicit error UI on `AsyncValue.error` (per FR-004 runtime states); a top-level `runZonedGuarded` wraps `runApp()` and writes uncaught exceptions to the rotating log (FR-074). No `Sentry` or remote crash reporter is wired up.

**Rationale**:
- Spec rejects telemetry (FR-074); local-only crash capture is the available substitute.
- `AsyncValue` plus error UI matches the spec's per-surface "documented unavailable state" requirement.

**Alternatives considered**:
- Try/catch in every Future — rejected: misses uncaught zone errors.
- Global error toast — rejected: violates FR-004's per-surface state distinction.

## R-19 — Helper-policy contract sourcing (FR-038a)

**Decision**: The app calls `app.helper_policies.list` (or equivalent FEAT-011 method) at handoff-flow entry and `app.helper_policies.resolve` at submission. The app never reads helper-policy YAML or markdown files itself. Confirms Q1 (round 2) — daemon-side resource via `app.*`.

**Note on FEAT-011 coverage**: FEAT-011 v1.0 ships 32 methods. The exact helper-policy methods named in FR-038a (`app.helper_policies.list` / `app.helper_policies.resolve`) may need to be added in a minor (v1.x) bump if not already present. If the methods are absent at integration time, the app surfaces the handoff helper-policy section as `runtime-degraded` per FR-004 and disables policy override per FR-002 contract-version-incompatible behavior; the spec's existing degradation rules apply without change.

**Rationale**: keeps FR-001 / FR-005 invariants intact while honoring the round-2 clarification that policies are not file-scraped.

## R-20 — Doctor / preflight check implementation (FR-009)

**Decision**: The doctor action is a Riverpod `FutureProvider` that fans out the six checks enumerated in FR-009 in parallel where independent and serially where dependent (e.g. peer-UID match depends on socket reachability). Output is captured as a `DoctorReport` model with one entry per check (`name`, `status`, `latency_ms`, `details`), rendered in Settings, and bundled verbatim into the FR-074 diagnostics-bundle export.

**Rationale**:
- Parallel where independent keeps the doctor responsive even on slow filesystems.
- Capturing latency per check helps the operator distinguish "slow but working" from "broken".
- The doctor is also reachable from the FR-075 command palette so power users can run it without navigating to Settings.

## R-21 — Persisted-state schema migration (state-persistence.md F27 deferred)

**Decision**: Forward-only schema migrations encoded as an ordered list of `Migration { fromVersion, toVersion, transform }` functions. On launch, if the persisted state's `schema_version` is older than the app's current schema version, the migrations are applied in order; if newer, the state is treated as incompatible per FR-070 and dropped (operator lands on onboarding/Dashboard).

**Rationale**:
- Forward-only matches FR-070's "compatible app launch" rule.
- Migration functions are testable in unit tests (input → output) without touching disk.

**Alternatives considered**:
- Schema-less / best-effort merge — rejected: silent data loss on schema drift.
- Bidirectional migrations — rejected: doubles the migration code surface for an MVP that ships at `schema_version = 1`.

## Open items — none

All technical-context items in `plan.md` are resolved. No `NEEDS CLARIFICATION` markers remain. The two open-question items the spec explicitly flags for plan-time tuning (latency threshold per F15, interaction-stability window per FR-053) are both decided here (R-14 for latency threshold; FR-053 already concretized to 2 seconds during /speckit-clarify round 1).

---

## Round 3 decisions (2026-05-24) — checklist gap closure

These 21 decisions resolve the highest-leverage open items across the 19 FAIL checklists from `/speckit-checklist` Round 2. Decisions are recorded as the canonical record; the spec.md `## Clarifications → ### Session 2026-05-24 (round 3)` block carries the operator-facing Q→A summary.

Numbering continues from R-01..R-21.

### R-22 — Accessibility precision (closes Q1)

**Decision**: WCAG 2.1 AA-equivalent baseline (FR-066) enumerates: 1.3.1 Info & Relationships, 1.4.3 Contrast (Minimum), 2.1.1 Keyboard, 2.4.3 Focus Order, 2.4.7 Focus Visible, 4.1.2 Name/Role/Value. In-scope surfaces: every interactive control, every status indicator (badges, health pills), every error message, every modal. Accessible-name patterns REQUIRED for every badge, every icon-only quick action, and every severity color (icon + text + color redundancy). Certified screen-reader pass out of MVP.

**Rationale**: Operator decision (Q1, recommendation accepted). Bakes FR-066 into testable shape so T030 (focus utils), T149 (unit tests), T150 (widget tests), T151 (golden tests) have a concrete criterion to enforce.

**Alternatives**: A keep-abstract (rejected — leaves a11y to implementation); C extend with 1.4.11 + 2.4.11 + screen-reader smoke (deferred to post-MVP); D contrast + kbd-only (rejected — drops focus order which the spec already commits to).

### R-23 — i18n stretch goals (closes Q2)

**Decision**: i18n layer (FR-067) ships at MVP with: ICU MessageFormat (pluralization), `intl` package date + number formatting, key-fallback for missing strings (render the key). RTL layout mirroring + locale-sensitive list sorting deferred to a future locale-add task.

**Rationale**: Q2 recommendation accepted. ICU MessageFormat is the Flutter-standard pluralization API; deferring RTL keeps the layout layer simpler at MVP without locking out future expansion.

**Alternatives**: A no stretch (rejected — pluralization is needed for "N findings"-style strings even in English MVP); C full RTL + locale-sort (deferred for cost reasons).

### R-24 — Theme + density behavior (closes Q3, extends R-15)

**Decision**: Theme and density changes apply live (no app restart required). Transient surfaces (toasts, tooltips, OS-native notifications) follow current theme. Compact density tokens guarantee ≥ 44 px touch targets (WCAG-compatible). High-contrast variant deferred to a future enhancement.

**Rationale**: Q3 recommendation accepted. The 44 px floor reconciles Compact density with the FR-066 a11y baseline (CHK026 ambiguity in `accessibility-i18n-theming.md`).

**Alternatives**: A restart-required (rejected — too disruptive); C high-contrast at MVP (deferred for cost).

### R-25 — Settings surface organization + per-setting behavior (closes Q4)

**Decision**: Settings grouped into 5 sections: **Display | Notifications | Connection | Privacy | Diagnostics**. Theme/density/grouping toggles apply live. Socket-path change triggers immediate re-bootstrap (the runtime-state Provider re-fires). OS-notification first-enable invokes the platform permission prompt (Windows toast permission, macOS Notification Center permission, Linux freedesktop.org `org.freedesktop.Notifications` portal). Reset-to-defaults is a single global button at the bottom of Settings. No live-preview for theme — the change IS the preview.

**Rationale**: Q4 recommendation accepted. 5 groups are the natural taxonomy after FR-009 + F12 doctor + FR-074 diagnostics enumeration.

**Alternatives**: A flat (rejected — 14 items don't scan flat); C per-setting reset + theme preview overlay (rejected — extra UI weight for marginal value).

### R-26 — Logging format + redaction policy (closes Q5, extends R-07)

**Decision**: Log format JSON-lines (each line = one JSON object with `ts`, `level`, `logger`, `msg`, optional `fields`). Levels: error + warn + info at production builds; debug toggleable from Settings → Diagnostics. Redaction denylist enforced at log-write time: `app_session_token`, any field named `prompt` or `prompt_text`, any field named `operator_notes`. Timestamps: ISO-8601 wall-clock + nanosecond-precision monotonic suffix for correlation. Diagnostics bundle archive: `.zip` saved via OS file picker; clipboard option available when bundle ≤ 1 MiB.

**Rationale**: Q5 recommendation accepted. JSON-lines is machine-parseable (helps Opensoft support) while remaining grep-friendly.

**Alternatives**: A plain text (rejected — harder to parse); C opt-in remote upload (rejected — violates FR-074 "MUST NOT upload").

### R-27 — Per-surface contract-version minimum map (closes Q6)

**Decision**: The per-surface minimum required `app_contract_version` (FR-002 degradation gate) is **code-derived at build time**. Each feature module declares the `app.*` methods it calls; a build-time codegen step produces a manifest mapping (surface → minimum version). Settings → Doctor surfaces the resolved table. No spec-level or plan-level enumeration of the map.

**Rationale**: Q6 recommendation accepted. Code-derivation prevents drift between spec text and reality. Settings → Doctor exposure satisfies the auditability that an explicit table would have provided.

**Alternatives**: A spec-level table (rejected — couples spec to method names); B plan-level table (rejected for same reason).

### R-28 — Mutation safety: idempotency + dry-run + read-only-mode (closes Q7)

**Decision**: The app auto-generates `idempotency_key` (uuid v4) on every mutation call to the FEAT-011 `app.*` surface, retains the key for retry, and includes it in the daemon request. No mutation supports dry-run except the handoff preview already specified in FR-040. Read-only mode (per FR-002 contract-version-incompatible degradation): mutation buttons remain RENDERED but are disabled with an inline explanation tooltip — never hidden, so the operator can see what's gated.

**Rationale**: Q7 recommendation accepted. Auto-idempotency is cheap and safe; visible-but-disabled mutation buttons satisfy FR-066 (screen-reader semantic completeness).

**Alternatives**: A keys only on Direct Send + hide buttons (rejected — hidden buttons hurt a11y); C add dry-run to route/drift (rejected — extra coupling for marginal benefit).

### R-29 — Live-update delivery model (closes Q8, extends R-16)

**Decision**: Per-surface polling cadence: **1 s** while the surface is foreground-visible; **5 s** when the surface is in a non-active workspace; **paused** when the app window is minimized. Reconnect mid-stream re-fetches from head + invalidates cursor. The polling implementation lives behind a Riverpod `Provider` so when FEAT-011 v1.x adds a push surface, the Provider swaps cleanly with no surface-layer code change. Targets FR-064's 2 s budget at ≤ 1 socket call per second per visible surface.

**Rationale**: Q8 recommendation accepted. 1 s foreground polling stays under FR-064's 2 s budget with margin; backoff keeps daemon load under FEAT-011's 8-session cap.

**Alternatives**: A push-only (rejected — blocks FEAT-012 on FEAT-011 changes); C 500 ms aggressive (rejected — wasteful for sub-2s budgets); D 2 s (rejected — exactly at budget, risks SC-006/007 misses).

### R-30 — Trust model platform parity (closes Q9, extends R-04)

**Decision**: Per-OS trust primitives — Linux `SO_PEERCRED`, macOS `LOCAL_PEERCRED` (or `getpeereid`), Windows AF_UNIX file ACL permitting current user only (no peer-credentials API). On socket connect, UID/owner mismatch triggers immediate disconnect + ERROR log entry + Dashboard banner naming the violation. Session token lifetime = process lifetime only — no idle-timeout, no refresh. The trust-model first-launch statement (FR-061) reads exactly:

> "This app talks only to a daemon running as your local user via a Unix socket. It does not connect to remote services. It does not authenticate users beyond your operating-system user."

**Rationale**: Q9 recommendation accepted. Per-OS primitives are the standard cross-platform pattern for AF_UNIX trust on Windows.

**Alternatives**: A Linux-only (rejected — three OS targets need parity); C idle-timeout (rejected — adds session-management complexity without security benefit for a local-only app).

### R-31 — Diagnostics bundle privacy + UX (closes Q10, extends R-07/R-26)

**Decision**: Bundle contents: (1) rotating log files (post-redaction per R-26), (2) app version + `app_contract_version` + socket path + OS user (no PII beyond `whoami`), (3) doctor report verbatim, (4) session-start + bundle-generation timestamps. Preview window shown BEFORE save/copy with a file-inventory list + first/last 20 lines of each log. Bundle size cap 50 MiB; if exceeded the operator picks "trim to most recent N files".

**Rationale**: Q10 recommendation accepted. Preview gives operator final review before bundle leaves the machine.

**Alternatives**: A no preview + no cap (rejected — easy to share sensitive content unintentionally); C per-file toggles (rejected — extra UI complexity).

### R-32 — Markdown subset for FR-079 (closes Q11, extends R-09)

**Decision**: In-app markdown renderer supports CommonMark + GFM extensions (tables, strikethrough, task lists, fenced code, autolinks). Raw HTML disabled entirely. `javascript:` and `data:` URLs blocked at the link-tap handler with inline "blocked: untrusted URL scheme" warning. Cross-doc `.md` links resolve to in-app rendering; non-`.md` links open via `url_launcher`. Disk change while open → "stale" indicator + "Reload" button (no auto-reload). Missing path → inline error placeholder; does NOT crash the surface.

**Rationale**: Q11 recommendation accepted. GFM is the de facto standard for repo docs (PRD, architecture, roadmap files in this repo are GFM).

**Alternatives**: A CommonMark only (rejected — tables are widely used); C inline images (deferred — image lifecycle is its own design problem).

### R-33 — Notifications + attention queue edge cases (closes Q12)

**Decision**: Empty attention queue shows `All clear — no actionable items` placeholder. Default attention sort = severity-then-age; filterable by item class (single-select dropdown). When a `high` or `critical` notification arrives in an `event_class` with an active grouped row (severity ≤ warning), the grouped row remains grouped and the high-severity notification appears as a separate ungrouped row immediately above. OS-native dispatch suppresses duplicates: same `event_class` + `agent_id` within 60 s = OS notification skipped (in-app notification still rendered). OS-permission-denied = inline Settings warning + toggle stays on so operator can retry after fixing OS-level permission. Project-card unread count = unread notifications scoped to that project's agents (per agent's `project_path`).

**Rationale**: Q12 recommendation accepted.

**Alternatives**: A hide empty + no filter + break group on high (rejected — degrades UX coherence); C per-class mute (deferred — adds Settings complexity).

### R-34 — Onboarding skip + Dashboard-nudge nuances (closes Q13, extends FR-010)

**Decision**: "Skip onboarding" affordance is rendered in the header of EVERY onboarding step. Dashboard nudges for incomplete milestones support a 1-week snooze gesture per nudge; "never show again" or longer snooze requires opening Settings → Diagnostics. Re-entry from Settings starts at the first incomplete milestone. SC-011 cohort denominator = operators who attempted any milestone (= anyone who opened onboarding and clicked at least one Next/Skip — measured via onboarding-state-completion telemetry; per FR-074 this is local-only and surfaces in the diagnostics bundle).

**Rationale**: Q13 recommendation accepted.

**Alternatives**: A skip-on-first-step + sticky nudges (rejected — friction-heavy); C "never show" per-nudge (rejected — drift risk for SC-011 measurement).

### R-35 — Per-OS installer specifics (closes Q14, extends R-13)

**Decision**: Code-signing reuses Opensoft's existing daemon code-signing CA (same cert family). Per-OS installer formats stay as in R-13 (MSIX / DMG / AppImage + DEB). Upgrade policy: in-place only — no side-by-side installs. Persisted-state schema-major downgrade triggers installer-launch refusal with named error. Autostart disabled by default. Installer probes `agenttowerd` reachability during install; if absent, shows "agenttowerd not detected — install/start it first" non-fatal warning then proceeds with desktop-app install. Signing key rotation cadence: annual + on-incident.

**Rationale**: Q14 recommendation accepted. Reusing the daemon CA simplifies operator trust (same cert chain across the AgentTower product).

**Alternatives**: A new CA (rejected — fragments trust); C bundled `agenttowerd` install (deferred — daemon install lives in a separate distribution flow).

### R-36 — Pagination cursor semantics (closes Q15, extends R-16)

**Decision**: Cursor is daemon-owned and opaque to the app (string token). Cursor TTL = 5 minutes. On stale-cursor error (FEAT-011 error code), the app re-fetches from head + shows a `Stream resumed` indicator on event-style lists. No monotonicity guarantee on Events / Queue lists during high event rates — operator may see duplicates on scroll-back; the spec accepts this trade-off in exchange for simpler cursor semantics.

**Rationale**: Q15 recommendation accepted.

**Alternatives**: A app-controlled offset (rejected — reorders on streams); C monotonicity guarantee (rejected — requires FEAT-011 v1.x cursor changes).

### R-37 — Project removal + last-project-pointer behavior (closes Q16, extends FR-077)

**Decision**: Removal-confirmation modal copy:

> "Remove project `{label}` ({repo_path}) from the desktop control panel? This clears local UI state only — daemon-side agents, handoffs, drift findings are NOT deleted. The project will reappear if it's later inferred from any adopted agent's project_path."

No in-session undo (operator can re-Add via Add Project to recreate the entry). When the currently-selected project is removed, the global last-project pointer falls back to the most-recently-active OTHER project; if none exists, the pointer is set to `null` and the operator lands on the Projects view with the FR-076 non-blocking banner.

**Rationale**: Q16 recommendation accepted.

**Alternatives**: A no confirmation copy + no special pointer handling (rejected — accidental removal risk); C in-session toast undo (deferred — adds state-machine complexity for marginal value).

### R-38 — Performance budget environmental preconditions (closes Q17)

**Decision**: Reference machine for FR-062..FR-065 + SC-001..SC-013 budgets: 8-core x86-64 ≥ 3.0 GHz base, 16 GB RAM, NVMe SSD, OS at idle (≤ 5% baseline CPU). Daemon fixture matches the FEAT-011 SC scale profile: ≤ 10 containers, ≤ 200 agents across them, ≤ 1k events / day, ≤ 100 routes, ≤ 5 projects. No concurrent background apps consuming significant CPU/network. Budgets apply at p95 over 10-run repetitions.

**Rationale**: Q17 short answer (recommended) accepted. Reproducibility requires a baseline.

**Alternatives**: lower-spec reference (rejected — fragments perf assertions across hardware classes); higher-spec (rejected — would mask budget breaches that real operators will hit).

### R-39 — Workspace shell UX defaults (closes Q18)

**Decision**: Workspace tabs use distinct icons + a color accent (1 accent per workspace, drawn from the research R-15 palette mechanism but reserved separately so accents never collide with severity colors). Sub-view ordering FIXED at MVP — no operator-reorder; FR-011 / FR-023 / FR-046 orderings are authoritative. Zero-state per workspace: Agent Operations Dashboard renders without project selection (daemon-level info: container/pane/agent counts, health); Project and Specs + Testing and Demo show a project-picker placeholder when no project is selected. Deep-link from attention item is forward-only navigation; operator returns to prior view via the standard back-button history.

**Rationale**: Q18 recommendation accepted.

**Alternatives**: A no styling + reorderable + project-required everywhere (rejected — Agent Ops needs to work without project selection); C drag-handle reorder (rejected — extra persisted state).

### R-40 — Health view per-subsystem rollup (closes Q19, extends FR-022)

**Decision**: Per-subsystem row content: `name` + `state` (`healthy | degraded | down`) + `last_successful_event_at` timestamp + (if degraded) human-readable reason sourced from `app.readiness` response. Daemon version displayed at top of Health view as a separate field, distinct from `app_contract_version`. Project-card validation and drift badges roll up from per-project state — they do NOT pull from the Health view directly. FR-068 update-available indicator stays on the Dashboard, not on Health view.

**Rationale**: Q19 recommendation accepted.

**Alternatives**: A state + reason only (rejected — operators want timestamps); C aggregate health pill on every project card (rejected — couples daemon-state to project-state surface).

### R-41 — Handoff multi-driver display + supersede chain (closes Q20, extends FR-029/FR-081)

**Decision**: Project card shows up-to-2 master indicators + "+N more" overflow (already in FR-025). Current Work view shows ALL drivers as a sortable list (sort columns: master label, current status, last activity). Supersede chain renders at most 3 levels (oldest → ... → current); deeper chains truncated with "+N earlier supersessions" link to full chain in handoff history view. Supersede confirmation copy reads exactly:

> "This will mark H1 as superseded by H2. Existing queue rows from H1 will NOT be auto-cancelled; cancel them manually from the Queue view if needed."

**Rationale**: Q20 recommendation accepted.

**Alternatives**: A first driver only (rejected — hides conflict); C full chain always (rejected — UI weight).

### R-42 — Release feed ownership + downgrade refusal (closes Q21, extends R-12)

**Decision**: Release feed URL: `https://releases.opensoft.one/agenttower/control-panel/latest.json`. Owner: Opensoft Releases team. Transport: signed JSON over TLS only (TLS 1.2+). Contract: the feed MUST never serve a version older than the previously-advertised version (no downgrades through the feed). Failure to fetch is silent at MVP — no banner, no error — but Settings → Doctor surfaces the most recent fetch outcome (timestamp + success/failure + latest-advertised version if successful).

**Rationale**: Q21 short answer (recommended) accepted.

**Alternatives**: third-party hosting (rejected — couples feature to non-Opensoft infrastructure); allowed downgrades through feed (rejected — security risk).
