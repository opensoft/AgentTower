import 'package:freezed_annotation/freezed_annotation.dart';

import 'common_enums.dart';

part 'operator_history_entry.freezed.dart';
part 'operator_history_entry.g.dart';

/// FR-055 + data-model §1.15 — Operator History Entry. T133 (Phase 8
/// US6).
///
/// **Rollup convention (FR-055 + FR-015)**: entries are rolled up by
/// `parentAgentId`; `subAgentId` (when non-null) nests under the
/// parent. The 2-level visible-depth cap from FR-015 applies — deeper
/// descendants are flattened to the nearest displayed parent and
/// surfaced as a "+N descendants" affordance.
///
/// **Persistence**: durable + reviewable across sessions per FR-055.
/// Daemon-owned; the app never writes history entries locally.
@freezed
class OperatorHistoryEntry with _$OperatorHistoryEntry {
  const factory OperatorHistoryEntry({
    required String entryId,
    required HistoryEntryKind kind,
    required DateTime occurredAt,
    required String parentAgentId,
    String? subAgentId,
    required String summary,
    Map<String, dynamic>? details,
    required DateTime asOf,
  }) = _OperatorHistoryEntry;

  factory OperatorHistoryEntry.fromJson(Map<String, dynamic> json) =>
      _$OperatorHistoryEntryFromJson(json);
}
