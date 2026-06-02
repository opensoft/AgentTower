import 'package:local_notifier/local_notifier.dart';

import '../../domain/models/common_enums.dart';
import 'grouping_rule.dart';

/// OS-native notification dispatcher. T033 + research R-10 + Round-3 R-33.
///
/// Dispatches OS-native notifications when:
///   - Settings toggle [enabled] is true (FR-058 opt-in)
///   - Severity is `high` or `critical` (low/warning → in-app only per US6 §5)
///
/// Per R-33: suppresses dispatch if the same `event_class` + `agent_id` was
/// dispatched within 60 s (de-dup window).
///
/// Per R-33: when OS reports permission denied, the dispatcher logs +
/// continues — the in-app notification is always rendered regardless.
class OsNativeNotificationDispatcher {
  OsNativeNotificationDispatcher({this.dedupWindow = const Duration(seconds: 60)});

  static const String _appName = 'AgentTower Control Panel';

  final Duration dedupWindow;
  final Map<String, DateTime> _recentDispatches = {};
  bool _initialized = false;

  Future<void> initialize() async {
    if (_initialized) return;
    await localNotifier.setup(
      appName: _appName,
      shortcutPolicy: ShortcutPolicy.requireCreate,
    );
    _initialized = true;
  }

  /// Dispatches [n] as an OS notification iff enabled, severity warrants,
  /// and the de-dup window has elapsed for this (event_class, agent_id).
  Future<void> dispatch(
    NotificationCandidate n, {
    required bool enabled,
  }) async {
    if (!enabled) return;
    if (n.severity != NotificationSeverity.high &&
        n.severity != NotificationSeverity.critical) {
      return;
    }
    final key = '${n.eventClass}|${n.agentId}';
    final last = _recentDispatches[key];
    final now = DateTime.now();
    if (last != null && now.difference(last) < dedupWindow) {
      return; // suppressed by de-dup window per R-33
    }
    _recentDispatches[key] = now;

    if (!_initialized) {
      await initialize();
    }

    try {
      final notif = LocalNotification(
        identifier: n.notificationId,
        title: _titleFor(n),
        subtitle: 'AgentTower',
        body: n.summary,
        silent: false,
      );
      await notif.show();
    } catch (_) {
      // OS-permission-denied or platform error — swallow per R-33; the
      // in-app notification is the authoritative surface.
    }
  }

  String _titleFor(NotificationCandidate n) {
    switch (n.severity) {
      case NotificationSeverity.critical:
        return 'Critical: ${n.eventClass}';
      case NotificationSeverity.high:
        return 'High: ${n.eventClass}';
      case NotificationSeverity.warning:
      case NotificationSeverity.info:
        return n.eventClass; // never reached due to guard above
    }
  }
}
