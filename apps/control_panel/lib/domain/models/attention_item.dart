import 'package:freezed_annotation/freezed_annotation.dart';

import 'common_enums.dart';

part 'attention_item.freezed.dart';
part 'attention_item.g.dart';

/// FR-052 + data-model §1.13 — Attention Item. T131 (Phase 8 US6).
///
/// **Identity**: daemon-issued `attentionId`. An attention item that
/// is resolved and re-emerges (e.g. a re-blocked queue row) receives
/// a new id.
///
/// **Class + severity (FR-052)**: every item carries [attentionClass]
/// (icon driver) + [severity] (color driver, R-15 palette). Default
/// sort in the queue is severity-then-age (most severe first, oldest
/// within severity first).
///
/// **Resolution target (FR-054)**: every item carries a typed pointer
/// to its resolution surface so the click handler can dispatch
/// directly without inspecting the class. See [ResolutionTarget]
/// below.
@freezed
class AttentionItem with _$AttentionItem {
  const factory AttentionItem({
    required String attentionId,
    required AttentionClass attentionClass,
    required AttentionSeverity severity,
    required DateTime ageStartedAt,
    required String oneLineSummary,
    required ResolutionTarget resolutionTarget,
    required DateTime asOf,
  }) = _AttentionItem;

  factory AttentionItem.fromJson(Map<String, dynamic> json) =>
      _$AttentionItemFromJson(json);
}

/// FR-054 — typed pointer to the resolution surface for an attention
/// item. Sealed so the dispatcher in `resolution_navigation.dart` can
/// pattern-match exhaustively at compile time.
///
/// Wire shape (per data-model.md §1.13): `{kind: "queue_row|health_subsystem
/// |drift_finding|validation_run", id: "<id>"}`.
@freezed
sealed class ResolutionTarget with _$ResolutionTarget {
  const factory ResolutionTarget.queueRow(String queueRowId) =
      ResolutionTargetQueueRow;
  const factory ResolutionTarget.healthSubsystem(String subsystemId) =
      ResolutionTargetHealthSubsystem;
  const factory ResolutionTarget.driftFinding(String findingId) =
      ResolutionTargetDriftFinding;
  const factory ResolutionTarget.validationRun(String runId) =
      ResolutionTargetValidationRun;

  factory ResolutionTarget.fromJson(Map<String, dynamic> json) =>
      _$ResolutionTargetFromJson(json);
}
