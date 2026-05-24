import 'package:freezed_annotation/freezed_annotation.dart';

import 'common_enums.dart';

part 'badges.freezed.dart';
part 'badges.g.dart';

/// Compact display badges used by [Project] (data-model §1.1) and other
/// Phase 4 surfaces. T082 (Phase 4 US2).
///
/// Each badge is a small, JSON-codeable value class — the daemon returns
/// the badge content already shaped (badges are derived server-side from
/// the underlying entity state per FEAT-011 v1.0); the app never invents
/// or recomputes them locally (FR-005).

// ---------------------------------------------------------------- repo state

enum RepoStateKind {
  clean('clean'),
  dirty('dirty'),
  ahead('ahead'),
  behind('behind'),
  diverged('diverged'),
  detachedHead('detached_head'),
  unknown('unknown');

  const RepoStateKind(this.wireValue);
  final String wireValue;
  static RepoStateKind fromWire(String v) => values.firstWhere(
        (e) => e.wireValue == v,
        orElse: () => RepoStateKind.unknown,
      );
}

@freezed
class RepoStateBadge with _$RepoStateBadge {
  const factory RepoStateBadge({
    required RepoStateKind kind,
    int? aheadCount,
    int? behindCount,
    int? dirtyFileCount,
  }) = _RepoStateBadge;

  factory RepoStateBadge.fromJson(Map<String, dynamic> json) =>
      _$RepoStateBadgeFromJson(json);
}

// ------------------------------------------------------ branch + worktree

@freezed
class BranchWorktreeBadge with _$BranchWorktreeBadge {
  const factory BranchWorktreeBadge({
    required String branchName,
    String? worktreePath,
    @Default(false) bool detached,
  }) = _BranchWorktreeBadge;

  factory BranchWorktreeBadge.fromJson(Map<String, dynamic> json) =>
      _$BranchWorktreeBadgeFromJson(json);
}

// --------------------------------------------------------------- validation

enum ValidationBadgeKind {
  unknown('unknown'),
  pending('pending'),
  pass('pass'),
  partial('partial'),
  fail('fail');

  const ValidationBadgeKind(this.wireValue);
  final String wireValue;
  static ValidationBadgeKind fromWire(String v) => values.firstWhere(
        (e) => e.wireValue == v,
        orElse: () => ValidationBadgeKind.unknown,
      );
}

@freezed
class ValidationBadge with _$ValidationBadge {
  const factory ValidationBadge({
    required ValidationBadgeKind kind,
    int? recentRunCount,
    DateTime? lastRunAt,
  }) = _ValidationBadge;

  factory ValidationBadge.fromJson(Map<String, dynamic> json) =>
      _$ValidationBadgeFromJson(json);
}

/// Master-summary compact validation roll-up (data-model §1.3).
@freezed
class CompactValidationBadge with _$CompactValidationBadge {
  const factory CompactValidationBadge({
    required ValidationBadgeKind kind,
    int? openFailureCount,
  }) = _CompactValidationBadge;

  factory CompactValidationBadge.fromJson(Map<String, dynamic> json) =>
      _$CompactValidationBadgeFromJson(json);
}

// -------------------------------------------------------------------- drift

@freezed
class DriftBadge with _$DriftBadge {
  const factory DriftBadge({
    required DriftSeverity highestSeverity,
    @Default(0) int openCount,
  }) = _DriftBadge;

  factory DriftBadge.fromJson(Map<String, dynamic> json) =>
      _$DriftBadgeFromJson(json);
}

// ----------------------------------------------------- attention summary

/// Per-project attention summary (FR-025). The card shows the highest
/// severity icon + total open count; expansion (FR-052) lives in the
/// Attention queue view.
@freezed
class AttentionSummary with _$AttentionSummary {
  const factory AttentionSummary({
    required AttentionSeverity highestSeverity,
    @Default(0) int openCount,
  }) = _AttentionSummary;

  factory AttentionSummary.fromJson(Map<String, dynamic> json) =>
      _$AttentionSummaryFromJson(json);
}

// --------------------------------------------- master summary support types

/// Active/inactive badge (data-model §1.3 — every master is active per
/// FR-071, but the activity recency is surfaced as a separate dimension).
@freezed
class ActiveInactiveBadge with _$ActiveInactiveBadge {
  const factory ActiveInactiveBadge({
    @Default(true) bool active,
    DateTime? lastActiveAt,
  }) = _ActiveInactiveBadge;

  factory ActiveInactiveBadge.fromJson(Map<String, dynamic> json) =>
      _$ActiveInactiveBadgeFromJson(json);
}

/// Workflow-phase descriptor (FR-030). Human label is required; the
/// underlying token (e.g. `engineering.active`) is surfaced as supporting
/// context only.
@freezed
class WorkflowPhase with _$WorkflowPhase {
  const factory WorkflowPhase({
    required String humanLabel,
    String? underlyingToken,
  }) = _WorkflowPhase;

  factory WorkflowPhase.fromJson(Map<String, dynamic> json) =>
      _$WorkflowPhaseFromJson(json);
}

/// Sub-agent rollup (data-model §1.3 — count + state summary). The
/// state summary is a histogram over the underlying [AgentState] of
/// the master's direct children (FR-015 sub-agent tree).
@freezed
class SubAgentRollup with _$SubAgentRollup {
  const factory SubAgentRollup({
    @Default(0) int count,
    @Default(<String, int>{}) Map<String, int> stateHistogram,
  }) = _SubAgentRollup;

  factory SubAgentRollup.fromJson(Map<String, dynamic> json) =>
      _$SubAgentRollupFromJson(json);
}
