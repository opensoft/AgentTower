import 'package:freezed_annotation/freezed_annotation.dart';

import 'badges.dart';
import 'common_enums.dart';

part 'master_summary.freezed.dart';
part 'master_summary.g.dart';

/// FR-030 / data-model §1.3 — Master Summary projection over an
/// [AdoptedAgent] that satisfies FR-071 (role=master AND master-class
/// capability). T083 (Phase 4 US2).
///
/// **Construction invariant (FR-071)**: callers MUST NOT instantiate
/// `MasterSummary` directly from an arbitrary `AdoptedAgent`. Use
/// [MasterSummary.tryFromAgent] (see `master_qualification.dart`)
/// which gates on the master-class capability lookup. Producing a
/// `MasterSummary` for an unqualified agent is a contract violation
/// per data-model.md §1.3 invariant.
///
/// **Status projection (FR-030)**: [currentStatus] is the master-
/// specific operational dimension (`active | waiting_for_input |
/// blocked | reviewing | idle | offline | degraded`). It is layered
/// on top of the underlying `AdoptedAgent.state == active` and is
/// **not** a parallel state machine — when the agent leaves `active`
/// the MasterSummary projection is no longer constructed and the
/// view layer falls back to the plain Agent row.
@freezed
class MasterSummary with _$MasterSummary {
  const factory MasterSummary({
    required String agentId,
    required String label,
    required String capability,
    required AgentRole role,
    required ActiveInactiveBadge activeBadge,
    required MasterStatus currentStatus,
    required String assignedProjectId,
    String? primaryAssignedFeatureChangeId,
    @Default(0) int primaryAssignedOverflowCount,
    required WorkflowPhase workflowPhase,
    required SubAgentRollup subAgentRollup,
    required AttentionSeverity attentionSeverity,
    @Default(0) int openActionableCount,
    DateTime? lastMeaningfulActivityAt,
    required CompactValidationBadge validationBadge,
    required DateTime asOf,
  }) = _MasterSummary;

  factory MasterSummary.fromJson(Map<String, dynamic> json) =>
      _$MasterSummaryFromJson(json);
}
