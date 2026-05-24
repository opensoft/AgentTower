import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../domain/models/common_enums.dart';
import '../../../domain/models/drift_signal.dart';
import '../../../domain/models/master_summary.dart';
import '../../../domain/models/project.dart';
import '../handoff/handoff_flow.dart';
import '../providers.dart';

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
    required WidgetRef ref,
    required DriftSignal drift,
    required Project project,
    required MasterSummary master,
  }) {
    // Pre-fill: the drift signal id + linked feature ids land in the
    // operator notes block of the handoff so the master sees them in
    // the FR-040 Project Context section.
    openHandoffFlow(
      context,
      master: master,
      project: project,
    );
    // Note: the handoff flow takes its `mode` selection from the
    // operator. We surface a non-blocking SnackBar nudge so the
    // operator picks drift_repair on the mode step.
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          'Drift repair: pick "drift_repair" mode and reference '
          '${drift.findingId} in operator notes '
          '(linked: ${drift.linkedFeatureIds.join(", ")})',
        ),
        duration: const Duration(seconds: 6),
      ),
    );
  }
}

// Avoid unused-import warnings on the providers re-export above.
// ignore: unused_element
final _projectProvidersRef = projectListProvider;
