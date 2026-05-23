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
