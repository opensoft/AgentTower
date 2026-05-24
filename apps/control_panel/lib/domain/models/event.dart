import 'package:freezed_annotation/freezed_annotation.dart';

part 'event.freezed.dart';
part 'event.g.dart';

/// FEAT-011 `app.event` mirror. T062 (Phase 3 US1) + data-model §1.16.
///
/// Events stream in observed-at order per FR-019. The Events view
/// (T072) is virtualized per FR-080 with "Jump to most recent" because
/// the stream is unbounded.
///
/// `eventType` is an open vocabulary owned by the daemon (FEAT-006
/// event classifier). The app treats it as a string and renders it
/// verbatim; per-type styling is a Phase 9 polish item, not blocking
/// for US1.
///
/// `linkedQueueRowId` lets the per-event drill-down jump to the
/// corresponding row in the Queue view (FR-019 cross-link).
@freezed
class Event with _$Event {
  const factory Event({
    required String eventId,
    required DateTime observedAt,
    required String eventType,
    required String agentId,
    required String excerpt,
    String? linkedQueueRowId,
    required DateTime asOf,
  }) = _Event;

  factory Event.fromJson(Map<String, dynamic> json) => _$EventFromJson(json);
}
