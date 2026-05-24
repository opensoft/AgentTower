import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/providers.dart';
import '../../../domain/helper_policy/helper_policy.dart';
import '../../../domain/models/common_enums.dart';

/// FR-038a + contracts/helper-policy.md — helper-policy resolution
/// for the handoff flow. T105 (Phase 5 US3).
///
/// **Sourcing**: this layer only calls
/// [AppClient.helperPolicyList] (at handoff-flow entry) and
/// [AppClient.helperPolicyResolve] (at submission). The app never
/// reads policy YAML files directly per FR-001.
///
/// **Override scope**: the operator override is per-handoff only —
/// it lives in the draft until submission and never mutates the
/// daemon-side default. The snapshot embedded in the submitted
/// handoff carries the resolved policy + the override pointer so the
/// handoff is reproducible.
class HelperPolicyResolver {
  HelperPolicyResolver(this.ref);
  final Ref ref;

  /// Lists policies available for the policy-picker UI. Returns the
  /// raw rows (a thin wrapper since the UI renders fields directly).
  Future<List<Map<String, dynamic>>> list() async {
    final page = await ref.read(appClientProvider).helperPolicyList();
    return page.items;
  }

  /// Resolves the snapshot the daemon would embed if the handoff were
  /// submitted now, with [operatorOverrideOfPolicyId] applied. Returns
  /// a parsed [HelperPolicySnapshot] ready to embed in a Handoff draft.
  Future<HelperPolicySnapshot> resolve({
    required String projectId,
    String? operatorOverrideOfPolicyId,
  }) async {
    final raw = await ref.read(appClientProvider).helperPolicyResolve(
          projectId: projectId,
          operatorOverrideOfPolicyId: operatorOverrideOfPolicyId,
        );
    final snapshottedAt = DateTime.now().toUtc();
    if (!raw.containsKey('snapshotted_at')) {
      raw['snapshotted_at'] = snapshottedAt.toIso8601String();
    }
    return HelperPolicySnapshot.fromJson(raw);
  }

  /// Fallback when the daemon does not yet expose helper-policy
  /// methods (R-19 caveat). Produces a minimal baked-default snapshot
  /// so the handoff flow can still proceed; the snapshot's
  /// `policySource` is [PolicySource.bakedDefault] and the policy id
  /// is `"unset"` so callers can detect the degraded path.
  HelperPolicySnapshot degradedSnapshot() {
    return HelperPolicySnapshot(
      resolvedPolicy: const HelperPolicy(
        policyId: 'unset',
        allowedHelperCapabilities: <String>{'shell'},
        defaultHelperCapability: 'shell',
        policySource: PolicySource.bakedDefault,
      ),
      snapshottedAt: DateTime.now().toUtc(),
    );
  }
}

final helperPolicyResolverProvider = Provider<HelperPolicyResolver>(
  (ref) => HelperPolicyResolver(ref),
);
