import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'daemon/app_client.dart';
import 'daemon/preflight_client.dart';
import 'daemon/session.dart';
import 'daemon/socket_client.dart';
import 'logging/rotating_file_logger.dart';
import 'notifications/os_native_dispatcher.dart';
import 'persistence/sort_filter_repository.dart';
import 'persistence/ux_state_repository.dart';
import 'persistence/paths.dart';

/// Cross-cutting Riverpod provider declarations. T044 (Phase 2 Foundational).
///
/// These providers do NOT carry default implementations — they are
/// overridden in `main.dart` (and in tests) with concrete instances built
/// from the resolved `AppPaths`, daemon socket, logger, etc. Reading any
/// of them before the overrides land throws [UnimplementedError] so
/// missing-override bugs surface loudly during early development.
///
/// The throw-by-default pattern is intentional: Riverpod doesn't enforce
/// "must override at root" by itself, and silent fallback to a default
/// instance would mask a misconfigured ProviderScope.

Never _unwired(String label) =>
    throw UnimplementedError('$label provider must be overridden in main()');

/// Per-OS app data directory + log dir. Built in `main.dart` from
/// `AppPaths.initialize()`.
final appPathsProvider = Provider<AppPaths>((ref) => _unwired('appPaths'));

/// Rotating JSON-lines file logger. Built in `main.dart` from
/// `RotatingFileLogger(paths: ...)`.
final loggerProvider =
    Provider<RotatingFileLogger>((ref) => _unwired('logger'));

/// Single owner of `ux-state.json`. Built in `main.dart`.
final uxStateRepositoryProvider =
    Provider<UxStateRepository>((ref) => _unwired('uxStateRepository'));

/// FR-078 — per-view sort/filter persistence (T179 / Phase 9). Reads/writes
/// the `list_sort_filter_*` slices of the shared UX-state file via the
/// [uxStateRepositoryProvider].
///
/// Degrades gracefully: when the UX-state repository isn't wired (e.g. a
/// perf/security harness that pumps a single list view with a minimal
/// override set), it falls back to an ephemeral in-memory store so the view
/// still renders. Sort/filter persistence is a non-critical enhancement —
/// unlike the socket/session/appClient providers, its absence must never
/// throw out of a view's build.
final sortFilterRepositoryProvider = Provider<SortFilterRepository>((ref) {
  UxStateStore store;
  try {
    store = ref.watch(uxStateRepositoryProvider);
  } on UnimplementedError {
    store = _EphemeralUxStateStore();
  }
  return SortFilterRepository(uxState: store);
});

/// In-memory [UxStateStore] used only when [uxStateRepositoryProvider] is
/// unwired. Reads start empty; writes are kept for the lifetime of the
/// provider but never reach disk.
class _EphemeralUxStateStore implements UxStateStore {
  Map<String, dynamic>? _state = <String, dynamic>{};
  @override
  Map<String, dynamic>? get current => _state;
  @override
  void update(Map<String, dynamic> newState) => _state = newState;
}

/// Unix-socket client for the FEAT-011 daemon. Built per-session lifecycle
/// in `main.dart` from the configured socket path.
final socketClientProvider =
    Provider<SocketClient>((ref) => _unwired('socketClient'));

/// Daemon session lifecycle (holds the in-memory `app_session_token`).
final daemonSessionProvider =
    Provider<DaemonSession>((ref) => _unwired('daemonSession'));

/// Typed wrappers around bootstrap-level `app.*` methods. The preflight
/// surface uses [preflightClientProvider] instead — it does not require a
/// session token and runs BEFORE `app.hello`.
final appClientProvider = Provider<AppClient>((ref) => _unwired('appClient'));

/// Session-free client used by the Doctor / preflight surface. Owns its
/// own short-lived `SocketClient`, so it can run before — or after a
/// failure of — the main `DaemonSession.bootstrap()`.
final preflightClientProvider =
    Provider<PreflightClient>((ref) => _unwired('preflightClient'));

/// FR-058 — OS-native notification dispatcher (T033 / Phase 2).
/// Phase 8 wires this into the notification fan-out via
/// `features/notifications/os_native_integration.dart`. The
/// dispatcher's `initialize()` is idempotent.
final osNativeNotificationDispatcherProvider =
    Provider<OsNativeNotificationDispatcher>(
  (ref) => OsNativeNotificationDispatcher(),
);

// The command-palette registry provider (`commandRegistryProvider`) lives
// in `shortcuts/command_palette.dart` next to the Notifier it wraps so
// this file doesn't import from `shortcuts/` and risk a circular import
// when palette widgets pull in core providers.
