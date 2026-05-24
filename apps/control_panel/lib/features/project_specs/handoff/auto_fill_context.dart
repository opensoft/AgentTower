import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../domain/models/feature_change_status.dart';
import '../../../domain/models/handoff_supporting.dart';
import '../../../domain/models/project.dart';

/// FR-038 — auto-fill of [HandoffContextBundle]. T104 (Phase 5 US3).
///
/// **Sources (FR-001 + R-28)**: every doc path comes from the daemon's
/// project/feature-change detail responses; the app does NOT read
/// filesystem paths to discover docs. Missing paths surface as null
/// fields on the bundle so the prompt-skeleton renderer renders only
/// what the daemon provided.
///
/// **Helper-policy snapshot**: this layer does NOT include the helper
/// policy — that comes from [helperPolicyResolverProvider] in a
/// separate step so the operator's policy override (if any) can be
/// applied before snapshotting. The handoff_flow composes both.
class AutoFillContext {
  AutoFillContext(this.ref);
  final Ref ref;

  /// Builds the bundle from the currently-resolved [project] and the
  /// primary [featureChange]. Both come from existing providers
  /// ([projectDetailProvider] / [featureChangeDetailProvider]); the
  /// caller passes them in so the auto-fill is deterministic from
  /// the operator's selections rather than from background state.
  Future<HandoffContextBundle> build({
    required Project project,
    required FeatureChangeStatus featureChange,
    List<String> additionalFeatureSpecPaths = const <String>[],
    List<String> additionalOpenspecChangePaths = const <String>[],
  }) async {
    // The doc-path fields below land on the feature/change detail once
    // FEAT-011 exposes them per R-28. For MVP we accept that the
    // daemon may return null for unknown paths; the bundle preserves
    // that so the prompt renders only what's real.
    return HandoffContextBundle(
      repositoryPath: project.repositoryPath,
      activeBranch: project.activeBranch.branchName,
      worktreePath: project.activeBranch.worktreePath,
      prdPath: null, // populated when app.project.detail returns it
      architecturePath: null,
      roadmapPath: null,
      featureSpecPaths: additionalFeatureSpecPaths.isEmpty
          ? null
          : List.unmodifiable(additionalFeatureSpecPaths),
      openspecChangePaths: additionalOpenspecChangePaths.isEmpty
          ? null
          : List.unmodifiable(additionalOpenspecChangePaths),
      currentStage: featureChange.stage.wireValue,
      currentExecutionStatus: featureChange.executionStatus.wireValue,
      currentSubphaseToken: featureChange.subphaseToken,
      driftStateSummary: project.driftBadge.openCount == 0
          ? 'no open drift findings'
          : '${project.driftBadge.openCount} open findings '
              '(highest: ${project.driftBadge.highestSeverity.wireValue})',
      validationStateSummary:
          'validation badge: ${project.validationBadge.kind.wireValue}',
      repoWorkflowRulesText: null,
    );
  }
}

final autoFillContextProvider = Provider<AutoFillContext>(
  (ref) => AutoFillContext(ref),
);
