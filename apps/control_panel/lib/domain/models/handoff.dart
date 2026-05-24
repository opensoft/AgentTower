import 'package:freezed_annotation/freezed_annotation.dart';

import '../helper_policy/helper_policy.dart';
import 'common_enums.dart';
import 'handoff_supporting.dart';
import 'resolved_work_item.dart';

part 'handoff.freezed.dart';
part 'handoff.g.dart';

/// FR-036..FR-045 + FR-072 + FR-081 + data-model §1.6 — Handoff
/// aggregate. T098 (Phase 5 US3).
///
/// **Identity**: pre-submission a transient client-side `draftId` is
/// used; on submission the daemon issues a `handoffId` that is
/// identity-bearing for the rest of the lifecycle. Both fields are
/// surfaced on the model so the UI can render the right id depending
/// on lifecycle phase.
///
/// **Lifecycle (FR-044)**: see [AssignmentState]. Allowed transitions
/// are enforced by the daemon and validated client-side by
/// `lib/domain/lifecycles/handoff_state_validator.dart` (Phase 2).
///
/// **Failure modes (FR-072)**:
///   - (a) submission failure → stays `drafted`, [failureContext] is
///     populated so the operator can amend + retry without losing
///     context.
///   - (b) delivery failure → transitions to `submitted`, [deliveryStatus]
///     is populated, handoff-detail surface shows a Retry delivery
///     action.
///   - (c) offline master at submission → held in `submitted` until
///     reconnect; [deliveryStatus.kind == pending].
///
/// **Supersede (FR-081)**: the prior handoff transitions to
/// `superseded` and the new handoff records [supersedesHandoffId]. The
/// reverse pointer [supersededByHandoffId] is populated on the prior
/// handoff. Supersede is a record-only intent change; queue rows are
/// NOT auto-cancelled (left for the operator to terminate from the
/// Queue view if desired).
@freezed
class Handoff with _$Handoff {
  const factory Handoff({
    String? handoffId,
    String? draftId,
    required DateTime createdAt,
    required DateTime updatedAt,
    required String operatorLabel,
    required String targetMasterAgentId,
    required String targetMasterLabel,
    required String projectId,
    required String projectLabel,
    required HandoffMode mode,
    HandoffPriority? priority,
    DateTime? deadline,
    required AssignmentState assignmentState,
    required List<WorkItemRef> selectedWorkItems,
    required List<ResolvedWorkItem> resolvedWorkItems,
    required WorkItemRef primaryWorkItem,
    @Default(<String>[]) List<String> linkedFeatureIds,
    @Default(<String>[]) List<String> linkedChangeIds,
    required HandoffContextBundle contextBundle,
    required String helperPolicyId,
    required HelperPolicySnapshot helperPolicySnapshot,
    required String generatedPromptText,
    String? operatorNotes,
    DateTime? submittedAt,
    DateTime? acceptedAt,
    DateTime? completedAt,
    DateTime? cancelledAt,
    String? supersededByHandoffId,
    String? supersedesHandoffId,
    HandoffDeliveryStatus? deliveryStatus,
    HandoffFailureContext? failureContext,
    required DateTime asOf,
  }) = _Handoff;

  factory Handoff.fromJson(Map<String, dynamic> json) =>
      _$HandoffFromJson(json);
}
