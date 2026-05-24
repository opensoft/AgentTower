import 'package:freezed_annotation/freezed_annotation.dart';

import 'common_enums.dart';
import 'drift_supporting.dart';

part 'drift_signal.freezed.dart';
part 'drift_signal.g.dart';

/// FR-033 + FR-034 + data-model §1.9 — Drift Signal. T113 (Phase 6 US4).
///
/// **Identity**: daemon-issued `findingId`, stable across lifecycle
/// transitions. A recurrence of a previously-resolved finding
/// receives a new id (per spec Key Entities).
///
/// **Lifecycle (FR-034)**: see [DriftStatus]. Allowed transitions:
/// `new → review_needed → confirmed → repair_planned → resolved`
/// canonical forward path; any non-terminal state may transition to
/// `accepted_as_built` or `dismissed`. Validated by
/// `lib/domain/lifecycles/drift_state_validator.dart` (T040, Phase 2).
///
/// **Scope rendering (FR-033)**: [scope] binds the finding to a
/// project / feature_change / branch / worktree / global surface.
/// The project card aggregates per-project counts; the Drift view
/// renders per-finding scope inline.
@freezed
class DriftSignal with _$DriftSignal {
  const factory DriftSignal({
    required String findingId,
    required DriftStatus status,
    required DriftSource source,
    required DriftSeverity severity,
    required DriftConfidence confidence,
    required DateTime ageStartedAt,
    required DriftScope scope,
    required String summary,
    required String recommendedAction,
    @Default(<DriftEvidence>[]) List<DriftEvidence> evidence,
    @Default(<String>[]) List<String> linkedFeatureIds,
    @Default(<String>[]) List<String> linkedChangeIds,
    String? linkedBranch,
    String? linkedWorktree,
    required DateTime asOf,
  }) = _DriftSignal;

  factory DriftSignal.fromJson(Map<String, dynamic> json) =>
      _$DriftSignalFromJson(json);
}
