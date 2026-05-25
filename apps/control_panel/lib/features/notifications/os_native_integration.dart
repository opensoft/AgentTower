import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/notifications/grouping_rule.dart';
import '../../core/notifications/os_native_dispatcher.dart';
import '../../core/providers.dart';
import '../../domain/models/common_enums.dart';
import '../../domain/models/notification.dart';

/// FR-058 — OS-native notification integration wrapper. T142 (Phase 8
/// US6).
///
/// Bridges incoming `AppNotification` records to the T033
/// `OsNativeNotificationDispatcher`. Dispatch fires only when:
///   - The FR-058 Settings toggle is `true` (caller passes
///     [enabled]).
///   - Severity is `high` or `critical` (low/warning → in-app only,
///     per Round-3 R-33).
///   - The de-dup window in the dispatcher hasn't seen the same
///     `event_class` + `agent_id` recently.
///
/// **Permission-denied handling**: the dispatcher logs and continues;
/// the in-app notification is always rendered regardless of OS
/// permission state.
class OsNativeIntegration {
  OsNativeIntegration({required this.dispatcher});

  final OsNativeNotificationDispatcher dispatcher;

  Future<void> initialize() => dispatcher.initialize();

  Future<void> consider(
    AppNotification notification, {
    required bool enabled,
  }) async {
    // Bridge to the dispatcher's NotificationCandidate; the
    // dispatcher applies severity + de-dup gating internally.
    await dispatcher.dispatch(
      NotificationCandidate(
        notificationId: notification.notificationId,
        eventClass: notification.eventClass,
        agentId: notification.agentId,
        severity: notification.severity,
        emittedAt: notification.emittedAt,
        summary: notification.summary,
      ),
      enabled: enabled,
    );
  }

  bool shouldFire(NotificationSeverity severity, {required bool enabled}) {
    if (!enabled) return false;
    return severity == NotificationSeverity.high ||
        severity == NotificationSeverity.critical;
  }
}

/// Riverpod provider that wires the dispatcher singleton.
final osNativeIntegrationProvider =
    Provider<OsNativeIntegration>((ref) {
  // The dispatcher itself is shared via core/providers.dart; this
  // wrapper is feature-side. We construct on demand because the
  // dispatcher's local_notifier setup is idempotent.
  return OsNativeIntegration(
    dispatcher: ref.read(osNativeNotificationDispatcherProvider),
  );
});
