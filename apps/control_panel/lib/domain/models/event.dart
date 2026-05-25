// `@JsonKey(...)` on freezed constructor parameters trips
// `invalid_annotation_target` even though json_serializable consumes
// the annotation correctly (it is the canonical freezed pattern for
// renaming wire fields). Suppress file-wide to keep T176 zero-warning.
// ignore_for_file: invalid_annotation_target
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
///
/// Wire-field naming: FEAT-011's canonical `app.event` shape uses
/// `event_class` / `emitted_at` / `summary`. The Dart side keeps the
/// more domain-readable `eventType` / `observedAt` / `excerpt` and
/// maps to/from the wire via `@JsonKey(name: ...)` (T176).
@freezed
class Event with _$Event {
  const factory Event({
    required String eventId,
    @JsonKey(name: 'emitted_at') required DateTime observedAt,
    @JsonKey(name: 'event_class') required String eventType,
    required String agentId,
    @JsonKey(name: 'summary') required String excerpt,
    String? linkedQueueRowId,
    required DateTime asOf,
  }) = _Event;

  factory Event.fromJson(Map<String, dynamic> json) => _$EventFromJson(json);
}
