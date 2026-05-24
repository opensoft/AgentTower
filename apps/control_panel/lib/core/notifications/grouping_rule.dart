import '../../domain/models/common_enums.dart';

/// FR-057 grouping rule applied as a view-layer projection. T032.
///
/// Concrete rule (per spec clarify Q19 + Round-3 R-33):
///   Collapse N ≥ 3 consecutive notifications that share
///     `event_class` AND `agent_id` AND severity ≤ `warning`
///   within a rolling 60-second window into a single grouped row showing
///   the count and the most recent timestamp.
///
/// `high` and `critical` are NEVER grouped (FR-057 last sentence).
///
/// Per Round-3 R-33: when a `high`/`critical` arrives in an event_class
/// with an active grouped row (warning), the grouped row stays grouped
/// and the high notification appears as a separate ungrouped row above.
class NotificationGroupingRule {
  const NotificationGroupingRule({
    this.windowDuration = const Duration(seconds: 60),
    this.minGroupSize = 3,
  });

  final Duration windowDuration;
  final int minGroupSize;

  /// Projects a flat [notifications] list (newest-first) into a list of
  /// [GroupedNotificationView] rows. Each row is either a single notification
  /// or a grouped representation of N ≥ [minGroupSize] consecutive notifications
  /// sharing event_class + agent_id + severity ≤ warning within [windowDuration].
  ///
  /// Pass [enabled] = false to disable grouping globally (per Settings toggle).
  List<GroupedNotificationView> project(
    List<NotificationCandidate> notifications, {
    bool enabled = true,
  }) {
    if (!enabled) {
      return notifications.map(GroupedNotificationView.single).toList();
    }
    final result = <GroupedNotificationView>[];
    var i = 0;
    while (i < notifications.length) {
      final head = notifications[i];
      if (!head.severity.groupable) {
        result.add(GroupedNotificationView.single(head));
        i++;
        continue;
      }

      // Look ahead while events share key + remain within window
      final group = <NotificationCandidate>[head];
      var j = i + 1;
      while (j < notifications.length) {
        final candidate = notifications[j];
        if (candidate.eventClass != head.eventClass ||
            candidate.agentId != head.agentId ||
            !candidate.severity.groupable ||
            head.emittedAt.difference(candidate.emittedAt) > windowDuration) {
          break;
        }
        group.add(candidate);
        j++;
      }

      if (group.length >= minGroupSize) {
        result.add(GroupedNotificationView.grouped(group));
      } else {
        for (final n in group) {
          result.add(GroupedNotificationView.single(n));
        }
      }
      i = j;
    }
    return result;
  }
}

/// Input candidate — just the fields the rule keys on.
class NotificationCandidate {
  const NotificationCandidate({
    required this.notificationId,
    required this.eventClass,
    required this.agentId,
    required this.severity,
    required this.emittedAt,
    required this.summary,
  });

  final String notificationId;
  final String eventClass;
  final String agentId;
  final NotificationSeverity severity;
  final DateTime emittedAt;
  final String summary;
}

/// Output: either a single notification or a grouped row (count + most recent).
class GroupedNotificationView {
  const GroupedNotificationView._({
    required this.isGrouped,
    required this.items,
    required this.mostRecentAt,
  });

  factory GroupedNotificationView.single(NotificationCandidate n) =>
      GroupedNotificationView._(
        isGrouped: false,
        items: [n],
        mostRecentAt: n.emittedAt,
      );

  factory GroupedNotificationView.grouped(List<NotificationCandidate> group) =>
      GroupedNotificationView._(
        isGrouped: true,
        items: group,
        mostRecentAt: group.first.emittedAt, // newest-first ordering
      );

  final bool isGrouped;
  final List<NotificationCandidate> items;
  final DateTime mostRecentAt;

  int get count => items.length;
  NotificationCandidate get head => items.first;
}
