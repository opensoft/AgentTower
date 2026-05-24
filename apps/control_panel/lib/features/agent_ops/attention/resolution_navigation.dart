import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../domain/models/attention_item.dart';
import '../../../domain/models/common_enums.dart';
import '../../../routing/route_paths.dart';
import '../../project_specs/drift/drift_detail_view.dart';

/// FR-054 — resolution-target dispatcher. T137 (Phase 8 US6).
///
/// Click on an attention item navigates directly to its resolution
/// surface. The dispatcher pattern-matches on the [ResolutionTarget]
/// sealed class so adding a new target variant is a compile-time
/// error in the exhaustive switch.
///
/// Today's wiring:
///   - `queueRow` → Agent Ops · Queue (deep-link to row id deferred)
///   - `healthSubsystem` → Agent Ops · Health
///   - `driftFinding` → Project + Specs · Drift detail view
///   - `validationRun` → Testing & Demo · Runs (deep-link to row
///     deferred — RunsView filters by state but not by single run id
///     yet; for MVP we land on the list)
class AttentionResolutionDispatcher {
  const AttentionResolutionDispatcher._();

  static Future<void> open(
    BuildContext context,
    WidgetRef ref,
    AttentionItem item,
  ) async {
    final target = item.resolutionTarget;
    switch (target) {
      case ResolutionTargetQueueRow():
        await Navigator.of(context).pushNamed(
          const RoutePath(
            workspace: Workspace.agentOps,
            subViewId: 'queue',
          ).toRouteString(),
        );
      case ResolutionTargetHealthSubsystem():
        await Navigator.of(context).pushNamed(
          const RoutePath(
            workspace: Workspace.agentOps,
            subViewId: 'health',
          ).toRouteString(),
        );
      case ResolutionTargetDriftFinding(:final findingId):
        await Navigator.of(context).push(
          MaterialPageRoute<void>(
            builder: (_) => DriftDetailView(findingId: findingId),
          ),
        );
      case ResolutionTargetValidationRun():
        await Navigator.of(context).pushNamed(
          const RoutePath(
            workspace: Workspace.testingDemo,
            subViewId: 'runs',
          ).toRouteString(),
        );
    }
  }
}
