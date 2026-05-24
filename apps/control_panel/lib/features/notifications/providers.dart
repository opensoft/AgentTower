import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/json_utils.dart';
import '../../core/providers.dart';
import '../../domain/models/notification.dart';

/// Riverpod providers for the notifications panel + history. T139+
/// (Phase 8 US6).

class NotificationListQuery {
  const NotificationListQuery({this.projectId, this.severity, this.lifecycle});
  final String? projectId;
  final String? severity;
  final String? lifecycle;

  @override
  bool operator ==(Object other) =>
      other is NotificationListQuery &&
      other.projectId == projectId &&
      other.severity == severity &&
      other.lifecycle == lifecycle;

  @override
  int get hashCode => Object.hash(projectId, severity, lifecycle);
}

final notificationListProvider = FutureProvider.autoDispose
    .family<List<AppNotification>, NotificationListQuery>((ref, query) async {
  final page = await ref.watch(appClientProvider).notificationList(
        projectId: query.projectId,
        severity: query.severity,
        lifecycle: query.lifecycle,
      );
  final asOf = DateTime.now().toUtc();
  return page.items
      .map((m) => AppNotification.fromJson(withAsOfDefault(m, asOf)))
      .toList(growable: false);
});

final notificationHistoryProvider = FutureProvider.autoDispose
    .family<List<AppNotification>, String?>((ref, projectId) async {
  final page = await ref
      .watch(appClientProvider)
      .notificationHistory(projectId: projectId);
  final asOf = DateTime.now().toUtc();
  return page.items
      .map((m) => AppNotification.fromJson(withAsOfDefault(m, asOf)))
      .toList(growable: false);
});

/// Per-project unread counts for the project card badge (FR-025 /
/// FR-056). Returns the count of `incoming`-lifecycle notifications
/// for the project.
final unreadNotificationCountProvider =
    FutureProvider.autoDispose.family<int, String?>((ref, projectId) async {
  final notifications = await ref.watch(
    notificationListProvider(
      NotificationListQuery(projectId: projectId, lifecycle: 'incoming'),
    ).future,
  );
  return notifications.length;
});
