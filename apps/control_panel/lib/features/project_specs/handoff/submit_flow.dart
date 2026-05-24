import '../../../core/daemon/app_client.dart';
import '../../../domain/helper_policy/helper_policy.dart';
import '../../../domain/models/common_enums.dart';
import '../../../domain/models/handoff.dart';
import '../../../domain/models/handoff_supporting.dart';
import '../../../domain/models/project.dart';
import '../../../domain/models/resolved_work_item.dart';

/// FR-042 + FR-043 + FR-072 — handoff submission. T108 (Phase 5 US3).
///
/// **Delivery (FR-043)**: the daemon delivers via the FEAT-009 safe
/// prompt queue — this layer does not touch the queue directly; it
/// only calls `app.handoff.submit` and the daemon owns the rest.
///
/// **Failure tiers (FR-072)**:
///   - (a) submission failure → daemon rejected. We rethrow so the
///     caller (preview surface) can render the FR-072(a) inline error
///     while the draft stays in memory.
///   - (b) delivery failure → daemon accepted but downstream queue
///     bounced. The returned Handoff carries [HandoffDeliveryStatus]
///     with `kind == failed`; the handoff detail surface (T111)
///     renders the "Retry delivery" affordance.
///   - (c) offline master at submission → handoff held in `submitted`
///     with `deliveryStatus.kind == pending`. The detail surface
///     names the offline-master state until reconnection.
///
/// All three tiers preserve operator context — never drop the draft
/// silently.
Future<Handoff> submitHandoff({
  required AppClient appClient,
  required String targetMasterLabel,
  required String targetMasterAgentId,
  required Project project,
  required HandoffMode mode,
  HandoffPriority? priority,
  DateTime? deadline,
  required String operatorNotes,
  required List<ResolvedWorkItem> resolved,
  required WorkItemRef primary,
  required HandoffContextBundle contextBundle,
  required HelperPolicySnapshot helperPolicySnapshot,
  required String generatedPromptText,
}) async {
  final draft = _serializeDraft(
    targetMasterAgentId: targetMasterAgentId,
    targetMasterLabel: targetMasterLabel,
    project: project,
    mode: mode,
    priority: priority,
    deadline: deadline,
    operatorNotes: operatorNotes,
    resolved: resolved,
    primary: primary,
    contextBundle: contextBundle,
    helperPolicySnapshot: helperPolicySnapshot,
    generatedPromptText: generatedPromptText,
  );
  final row = await appClient.handoffSubmit(draft: draft);
  return Handoff.fromJson(_withAsOf(row, DateTime.now().toUtc()));
}

Map<String, dynamic> _serializeDraft({
  required String targetMasterAgentId,
  required String targetMasterLabel,
  required Project project,
  required HandoffMode mode,
  HandoffPriority? priority,
  DateTime? deadline,
  required String operatorNotes,
  required List<ResolvedWorkItem> resolved,
  required WorkItemRef primary,
  required HandoffContextBundle contextBundle,
  required HelperPolicySnapshot helperPolicySnapshot,
  required String generatedPromptText,
}) {
  return {
    'target_master_agent_id': targetMasterAgentId,
    'target_master_label': targetMasterLabel,
    'project_id': project.projectId,
    'project_label': project.label,
    'mode': mode.wireValue,
    if (priority != null) 'priority': priority.wireValue,
    if (deadline != null) 'deadline': deadline.toIso8601String(),
    'operator_notes': operatorNotes,
    'primary_work_item': primary.toJson(),
    'resolved_work_items': [for (final r in resolved) r.toJson()],
    'context_bundle': contextBundle.toJson(),
    'helper_policy_id': helperPolicySnapshot.resolvedPolicy.policyId,
    'helper_policy_snapshot': helperPolicySnapshot.toJson(),
    'generated_prompt_text': generatedPromptText,
  };
}

Map<String, dynamic> _withAsOf(Map<String, dynamic> raw, DateTime asOf) {
  if (raw.containsKey('as_of')) return raw;
  return {...raw, 'as_of': asOf.toIso8601String()};
}
