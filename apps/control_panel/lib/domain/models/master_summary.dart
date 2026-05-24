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

  /// Swarm-review H-G1 — FR-071 qualification gate. Use this instead
  /// of the raw freezed factory whenever constructing a MasterSummary
  /// from an [AdoptedAgent]-derived shape: returns `null` if the
  /// agent does NOT pass FR-071 (role + master-class capability),
  /// preventing accidental construction of "master" rows for plain
  /// agents.
  ///
  /// The full set of FR-030 fields (workflow phase, attention
  /// severity, sub-agent rollup, etc.) are not derivable from an
  /// AdoptedAgent alone — they come from the daemon's master-summary
  /// projection. This helper exists for the rare cases where the
  /// app must synthesize a minimal MasterSummary (e.g. the
  /// drift-repair launcher in `drift_repair_handoff_launch.dart`).
  /// Callers MUST supply the projection fields explicitly.
  static MasterSummary? tryFromAgent({
    required String agentId,
    required String label,
    required String capability,
    required AgentRole role,
    required Set<String> masterClassCapabilities,
    required String assignedProjectId,
    required ActiveInactiveBadge activeBadge,
    required MasterStatus currentStatus,
    required WorkflowPhase workflowPhase,
    required SubAgentRollup subAgentRollup,
    required AttentionSeverity attentionSeverity,
    required CompactValidationBadge validationBadge,
    required DateTime asOf,
    String? primaryAssignedFeatureChangeId,
    int primaryAssignedOverflowCount = 0,
    int openActionableCount = 0,
    DateTime? lastMeaningfulActivityAt,
  }) {
    if (role != AgentRole.master) return null;
    if (masterClassCapabilities.isEmpty) return null;
    if (!masterClassCapabilities.contains(capability)) return null;
    return MasterSummary(
      agentId: agentId,
      label: label,
      capability: capability,
      role: role,
      activeBadge: activeBadge,
      currentStatus: currentStatus,
      assignedProjectId: assignedProjectId,
      primaryAssignedFeatureChangeId: primaryAssignedFeatureChangeId,
      primaryAssignedOverflowCount: primaryAssignedOverflowCount,
      workflowPhase: workflowPhase,
      subAgentRollup: subAgentRollup,
      attentionSeverity: attentionSeverity,
      openActionableCount: openActionableCount,
      lastMeaningfulActivityAt: lastMeaningfulActivityAt,
      validationBadge: validationBadge,
      asOf: asOf,
    );
  }
}
