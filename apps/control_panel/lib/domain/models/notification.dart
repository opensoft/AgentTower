import 'package:freezed_annotation/freezed_annotation.dart';

import 'common_enums.dart';

part 'notification.freezed.dart';
part 'notification.g.dart';

/// FR-056 + data-model §1.14 — Notification. T132 (Phase 8 US6).
///
/// Named `AppNotification` (not `Notification`) to avoid the
/// collision with Flutter's `Notification` widget-tree class — the
/// model would otherwise shadow it in any file that imports both
/// `material.dart` and this file.
///
/// **FR-057 grouping** is a VIEW-LAYER projection applied by
/// `core/notifications/grouping_rule.dart`; the underlying
/// `AppNotification` records are immutable and never mutated by the
/// projection.
@freezed
class AppNotification with _$AppNotification {
  const factory AppNotification({
    required String notificationId,
    required String eventClass,
    required String agentId,
    required NotificationSeverity severity,
    required DateTime emittedAt,
    required String summary,
    String? sourceEventId,
    required NotificationLifecycle lifecycle,
    required DateTime asOf,
  }) = _AppNotification;

  factory AppNotification.fromJson(Map<String, dynamic> json) =>
      _$AppNotificationFromJson(json);
}
