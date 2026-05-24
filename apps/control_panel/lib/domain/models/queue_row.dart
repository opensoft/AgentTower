import 'package:freezed_annotation/freezed_annotation.dart';

import 'common_enums.dart';

part 'queue_row.freezed.dart';
part 'queue_row.g.dart';

/// FEAT-011 `app.queue` mirror. T060 (Phase 3 US1) + data-model §1.16.
///
/// 5-state vocabulary per FR-020: `queued | blocked | delivered |
/// canceled | failed`. The Queue view (T073) renders per-row actions
/// based on [QueueRowState.isTerminal] — only `queued` and `blocked`
/// accept mutations. Allowed mutation matrix per FEAT-011
/// `app.queue.*` state transitions (Round-5):
///   - approve: blocked → queued                    (blocked only)
///   - delay:   queued → blocked (operator_delayed) (queued only)
///   - cancel:  queued | blocked → canceled         (both non-terminal)
///
/// `messageId` is the daemon-issued identifier. Earlier drafts of this
/// model called it `queueRowId`; renamed to match the wire field name
/// (`message_id`) used by `app.queue.{detail,approve,delay,cancel}`
/// per contract lines 225 + 346 (review fix C3 / spec-code lane).
///
/// `payload` is the structured object accepted by `app.send_input`
/// (contract line 319). The Queue view extracts `payload['text']` for
/// preview, falling back to JSON-encoded form if `text` is absent.
@freezed
class QueueRow with _$QueueRow {
  const factory QueueRow({
    required String messageId,
    required QueueRowState state,
    required Map<String, dynamic> payload,
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
