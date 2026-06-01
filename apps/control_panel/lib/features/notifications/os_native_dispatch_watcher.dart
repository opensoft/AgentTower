import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../domain/models/notification.dart';
import '../settings/providers.dart';
import 'os_native_integration.dart';
import 'providers.dart';

/// FR-058 dispatcher wiring — T171 (Phase 9).
///
/// Listens to the `incoming`-lifecycle slice of [notificationListProvider]
/// and dispatches every newly-arrived notification to the
/// [OsNativeIntegration]. The dispatcher's internal severity-gate +
/// de-dup window does the rest (per FR-058 + R-33).
///
/// **Polling-diff strategy** — the listener diffs the current snapshot
/// against the previous snapshot to identify *newly-arrived*
/// notifications. This is the production strategy until FEAT-011 v1.x
/// exposes a streaming subscription method (then T167 will replace the
/// producer; the consumer side here is unchanged). See tasks.md T171 +
/// /speckit-analyze Round 6 F6.
///
/// The watcher is `Provider<void>` — a side-effect provider whose
/// `build` callback registers `ref.listen` and returns. It must be
/// kept alive by at least one `ref.watch` from a long-lived widget
/// (wired in `app.dart`).
///
/// **Refresh producer** — `notificationListProvider` is a plain
/// `FutureProvider.autoDispose.family` that resolves once and never
/// re-fetches on its own, so `ref.listen` would only ever emit the
/// launch-time backlog (which the first-tick branch absorbs). To make
/// the polling-diff strategy actually observe *newly-arrived*
/// notifications, this provider drives its own periodic refresh: a
/// `Timer.periodic` invalidates the **exact** unscoped `incoming`
/// family key it subscribes to, forcing a re-fetch whose result the
/// `ref.listen` diff then compares against `seen`. The timer is torn
/// down via `ref.onDispose` when the watcher is no longer kept alive.
const _refreshInterval = Duration(seconds: 5);

final osNativeDispatchWatcherProvider = Provider<void>((ref) {
  final seen = <String>{};

  // The single family key this watcher subscribes to *and* refreshes.
  // Both the `ref.listen` below and the periodic invalidate must use
  // this identical (unscoped, `incoming`) key or the diff never runs.
  const query = NotificationListQuery(lifecycle: 'incoming');

  ref.listen(
    notificationListProvider(query),
    (previous, next) {
      final notifications = next.valueOrNull;
      if (notifications == null) return;
      _dispatchNewlyArrived(ref, notifications, seen);
    },
    // Fire on the first non-loading value too so the very first batch
    // of `incoming` notifications after app launch isn't skipped.
    fireImmediately: true,
  );

  // Periodically re-fetch the subscribed key so newly-arrived
  // notifications are detected. Without this producer the `ref.listen`
  // above only ever emits the launch-time backlog (FR-058 would never
  // dispatch). Replace with the streaming subscription once FEAT-011
  // v1.x exposes it (see T167).
  final timer = Timer.periodic(_refreshInterval, (_) {
    ref.invalidate(notificationListProvider(query));
  });
  ref.onDispose(timer.cancel);
});

/// Computes the diff against [seen], mutates [seen] to the current
/// snapshot, and forwards each newly-arrived notification to the
/// integration wrapper. Exposed for unit testing.
void _dispatchNewlyArrived(
  Ref ref,
  List<AppNotification> notifications,
  Set<String> seen,
) {
  // Snapshot the current id set so the diff is stable across
  // concurrent rebuilds.
  final currentIds = <String>{
    for (final n in notifications) n.notificationId,
  };

  // First-tick semantics: if `seen` is empty AND this is the very first
  // ever update, we treat the entire current list as "already-known"
  // backlog — the operator launched the app to *see* these, not to be
  // re-paged on every relaunch. Subsequent additions ARE newly-arrived.
  if (seen.isEmpty) {
    seen.addAll(currentIds);
    return;
  }

  final newlyArrived = [
    for (final n in notifications)
      if (!seen.contains(n.notificationId)) n,
  ];

  // Update `seen` BEFORE async dispatch so a re-entrant rebuild
  // mid-dispatch doesn't re-issue the same notifications.
  seen
    ..clear()
    ..addAll(currentIds);

  if (newlyArrived.isEmpty) return;

  final integration = ref.read(osNativeIntegrationProvider);
  final settings = ref.read(settingsProvider);
  final enabled = settings.osNativeNotifications;

  for (final n in newlyArrived) {
    // Fire-and-forget; the integration handles *permission/dispatch*
    // errors internally (per OsNativeIntegration doc-comment), but the
    // dispatcher's lazy `initialize()` runs UNGUARDED ahead of that
    // try/catch — a `local_notifier` setup failure (e.g. Windows
    // shortcut-creation) would otherwise escape into the zone as an
    // unhandled async error. Defensively swallow here so one bad
    // dispatch can't crash the watcher.
    unawaited(
      integration.consider(n, enabled: enabled).catchError((Object _) {}),
    );
  }
}

/// Test-only re-export of the diff routine. Production callers go
/// through the [osNativeDispatchWatcherProvider] above.
@visibleForTesting
void debugDispatchNewlyArrived(
  Ref ref,
  List<AppNotification> notifications,
  Set<String> seen,
) =>
    _dispatchNewlyArrived(ref, notifications, seen);
