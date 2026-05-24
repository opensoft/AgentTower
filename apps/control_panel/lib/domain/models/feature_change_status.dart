import 'package:freezed_annotation/freezed_annotation.dart';

import 'common_enums.dart';

part 'feature_change_status.freezed.dart';
part 'feature_change_status.g.dart';

/// FR-028 + data-model §1.5 — Feature/Change status composite. T084
/// (Phase 4 US2).
///
/// **Three-layer model (FR-028)**: a feature/change is described by
/// the tuple (stage, executionStatus, optional subphaseToken). The
/// human-readable label combines them in operator-friendly form
/// ("Engineering / Active"); the underlying token is surfaced as
/// supporting context only.
///
/// **`deferred` stage (F7-a, F7-b)**: `deferred` is a first-class
/// stage value; it is non-terminal and may transition back only to
/// [Stage.definition] or [Stage.specReady] via an explicit un-defer
/// action. The `featureChangeId` is preserved across un-defer.
/// Validator lives in `lib/domain/lifecycles/feature_change_stage_validator.dart`.
@freezed
class FeatureChangeStatus with _$FeatureChangeStatus {
  const factory FeatureChangeStatus({
    required String featureChangeId,
    required String displayId,
    required Stage stage,
    required ExecutionStatus executionStatus,
    String? subphaseToken,
    required String humanReadableLabel,
    required String projectId,
    String? drivingMasterAgentId,
    String? drivingHandoffId,
    required DateTime asOf,
  }) = _FeatureChangeStatus;

  factory FeatureChangeStatus.fromJson(Map<String, dynamic> json) =>
      _$FeatureChangeStatusFromJson(json);
}
