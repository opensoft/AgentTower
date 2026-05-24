import 'package:flutter/material.dart';

import '../../../domain/models/common_enums.dart';
import '../../../domain/models/drift_signal.dart';
import '../../../domain/models/master_summary.dart';
import '../../../domain/models/project.dart';
import '../handoff/handoff_flow.dart';

/// FR-035 — launch a drift-repair handoff pre-filled with the affected
/// feature(s) and the drift signal id as context. T118 (Phase 6 US4).
///
/// **Mode**: forced to [HandoffMode.driftRepair] per FR-035. The
/// operator can still adjust other inputs (priority, deadline,
/// helper-policy override, notes) in the handoff flow.
///
/// **Master picker**: if there is exactly one currently-driving master
/// on the project, it is pre-selected as the target. Otherwise the
/// operator picks from the available masters via the handoff flow's
/// master step.
class DriftRepairHandoffLauncher {
  const DriftRepairHandoffLauncher._();

  static void launch({
    required BuildContext context,
    required DriftSignal drift,
    required Project project,
    required MasterSummary master,
  }) {
    // Swarm-review CR-9 + H-C1: previously this opened the handoff
    // flow with no mode pre-fill, then nudged the operator via
    // SnackBar to pick drift_repair manually. The pre-fill is now
    // genuine: `initialMode: HandoffMode.driftRepair` seeds step 4,
    // `initialOperatorNotes` seeds the FR-040 operator-notes block
    // with the drift signal id + linked feature ids so the master
    // sees them in context. FR-035 affordance is now functional.
    openHandoffFlow(
      context,
      master: master,
      project: project,
      initialMode: HandoffMode.driftRepair,
      initialOperatorNotes: _buildPrefilledNotes(drift),
    );
  }

  static String _buildPrefilledNotes(DriftSignal drift) {
    final lines = <String>[
      'Drift-repair handoff for drift signal: ${drift.findingId}',
      'Status: ${drift.status.wireValue} · '
          'Severity: ${drift.severity.wireValue} · '
          'Source: ${drift.source.wireValue}',
      'Summary: ${drift.summary}',
      'Recommended action: ${drift.recommendedAction}',
    ];
    if (drift.linkedFeatureIds.isNotEmpty) {
      lines.add('Linked features: ${drift.linkedFeatureIds.join(", ")}');
    }
    if (drift.linkedChangeIds.isNotEmpty) {
      lines.add('Linked changes: ${drift.linkedChangeIds.join(", ")}');
    }
    if (drift.linkedBranch != null) {
      lines.add('Linked branch: ${drift.linkedBranch}');
    }
    return lines.join('\n');
  }
}
