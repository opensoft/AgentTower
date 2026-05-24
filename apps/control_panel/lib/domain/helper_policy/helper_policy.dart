import 'package:freezed_annotation/freezed_annotation.dart';

import '../models/common_enums.dart';

part 'helper_policy.freezed.dart';
part 'helper_policy.g.dart';

/// FR-038a + data-model §1.8 — Helper-agent policy. T100 (Phase 5 US3).
///
/// **Sourcing (FR-001 / R-19)**: helper policies are exposed by the
/// daemon through `app.helper_policies.list` / `.resolve`. The app
/// NEVER reads helper-policy YAML/markdown files directly. If those
/// methods are not present in the deployed FEAT-011 version, the
/// handoff helper-policy section surfaces as `runtime-degraded` per
/// FR-004 and policy override is disabled per FR-002.
@freezed
class HelperPolicy with _$HelperPolicy {
  const factory HelperPolicy({
    required String policyId,
    required Set<String> allowedHelperCapabilities,
    required String defaultHelperCapability,
    required PolicySource policySource,
  }) = _HelperPolicy;

  factory HelperPolicy.fromJson(Map<String, dynamic> json) =>
      _$HelperPolicyFromJson(json);
}

/// FR-038a — Helper-policy snapshot embedded in a Handoff at submission
/// time. The snapshot is immutable; subsequent policy edits MUST NOT
/// retroactively alter a submitted handoff (the daemon enforces this
/// invariant, but the app preserves the snapshot through every
/// detail/list response).
///
/// **operatorOverrideOfPolicyId**: non-null only when
/// `resolvedPolicy.policySource == operatorOverride`, naming the base
/// policy the operator overrode.
///
/// **repoOverridePath**: non-null only when
/// `resolvedPolicy.policySource == repoOverride`, naming the in-repo
/// file the daemon resolved (e.g. `agenttower/helper-policy.yaml`).
@freezed
class HelperPolicySnapshot with _$HelperPolicySnapshot {
  const factory HelperPolicySnapshot({
    required HelperPolicy resolvedPolicy,
    required DateTime snapshottedAt,
    String? operatorOverrideOfPolicyId,
    String? repoOverridePath,
  }) = _HelperPolicySnapshot;

  factory HelperPolicySnapshot.fromJson(Map<String, dynamic> json) =>
      _$HelperPolicySnapshotFromJson(json);
}
