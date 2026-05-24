import 'package:freezed_annotation/freezed_annotation.dart';

import 'common_enums.dart';

part 'queue_row.freezed.dart';
part 'queue_row.g.dart';

/// FEAT-011 `app.queue` mirror. T060 (Phase 3 US1) + data-model §1.16.
///
/// 5-state vocabulary per FR-020: `queued | blocked | delivered |
/// canceled | failed`. The Queue view (T073) renders per-row actions
/// based on [QueueRowState.isTerminal] — only `queued` and `blocked`
/// accept approve/delay/cancel mutations.
///
/// `payload` is the safe-prompt-queue body. The Queue view shows a
/// preview only; the full body lands behind a per-row drill-down.
@freezed
class QueueRow with _$QueueRow {
  const factory QueueRow({
    required String queueRowId,
    required QueueRowState state,
    required String payload,
    required String sourceAgentId,
    required String targetAgentId,
    String? routeId,
    required DateTime createdAt,
    DateTime? terminalAt,
    required DateTime asOf,
  }) = _QueueRow;

  factory QueueRow.fromJson(Map<String, dynamic> json) =>
      _$QueueRowFromJson(json);
}
