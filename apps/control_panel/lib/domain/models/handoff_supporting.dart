import 'package:freezed_annotation/freezed_annotation.dart';

import 'common_enums.dart';

part 'handoff_supporting.freezed.dart';
part 'handoff_supporting.g.dart';

/// Supporting types for the Handoff aggregate (data-model §1.6). T098
/// (Phase 5 US3).
///
/// These types are referenced from `handoff.dart` but defined separately
/// to keep that file focused on the Handoff freezed class itself.

/// Reference to a work item the operator selected for a handoff. The
/// resolution into a per-item entry (with FR-039 inclusion/exclusion
/// annotation) happens in [ResolvedWorkItem].
@freezed
class WorkItemRef with _$WorkItemRef {
  const factory WorkItemRef({
    required String displayId,
    required WorkItemKind kind,
    String? featureChangeId,
  }) = _WorkItemRef;

  factory WorkItemRef.fromJson(Map<String, dynamic> json) =>
      _$WorkItemRefFromJson(json);
}

/// FR-038 auto-filled context bundle — every input the prompt skeleton
/// composes into the Project Context section. The daemon resolves the
/// document paths per R-28; the app does not invent them.
@freezed
class HandoffContextBundle with _$HandoffContextBundle {
  const factory HandoffContextBundle({
    required String repositoryPath,
    String? activeBranch,
    String? worktreePath,
    String? prdPath,
    String? architecturePath,
    String? roadmapPath,
    List<String>? featureSpecPaths,
    List<String>? openspecChangePaths,
    String? currentStage,
    String? currentExecutionStatus,
    String? currentSubphaseToken,
    String? driftStateSummary,
    String? validationStateSummary,
    String? repoWorkflowRulesText,
  }) = _HandoffContextBundle;

  factory HandoffContextBundle.fromJson(Map<String, dynamic> json) =>
      _$HandoffContextBundleFromJson(json);
}

/// FR-072(b) — delivery-failure indicator surfaced on the handoff
/// detail view. Null on happy path.
enum HandoffDeliveryStatusKind {
  pending('pending'),
  delivered('delivered'),
  failed('failed'),
  retrying('retrying');

  const HandoffDeliveryStatusKind(this.wireValue);
  final String wireValue;
  static HandoffDeliveryStatusKind fromWire(String v) =>
      values.firstWhere((e) => e.wireValue == v);
}

@freezed
class HandoffDeliveryStatus with _$HandoffDeliveryStatus {
  const factory HandoffDeliveryStatus({
    required HandoffDeliveryStatusKind kind,
    String? lastErrorMessage,
    DateTime? lastAttemptAt,
    @Default(0) int retryCount,
  }) = _HandoffDeliveryStatus;

  factory HandoffDeliveryStatus.fromJson(Map<String, dynamic> json) =>
      _$HandoffDeliveryStatusFromJson(json);
}

/// FR-072(a) — submission-failure context attached to a still-drafted
/// handoff so the operator can amend and retry.
@freezed
class HandoffFailureContext with _$HandoffFailureContext {
  const factory HandoffFailureContext({
    required String errorCode,
    required String errorMessage,
    Map<String, dynamic>? details,
    DateTime? attemptedAt,
  }) = _HandoffFailureContext;

  factory HandoffFailureContext.fromJson(Map<String, dynamic> json) =>
      _$HandoffFailureContextFromJson(json);
}
