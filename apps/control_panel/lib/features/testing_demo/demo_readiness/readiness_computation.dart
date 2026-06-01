import '../../../domain/models/common_enums.dart';
import '../../../domain/models/demo_readiness_summary.dart';
import '../../../domain/models/validation_entrypoint.dart';
import '../../../domain/models/validation_run.dart';
import '../../../domain/models/validation_supporting.dart';

/// FR-050 invariant enforcement — local rendering helper. T129
/// (Phase 7 US5).
///
/// Per FR-050: "the overall state MUST be at most `at_risk` if any
/// `required`-blocking-level entrypoint has not run on the current
/// branch." The daemon owns this invariant, but a misbehaving or
/// degraded daemon could ship a `ready` overall state alongside a
/// missing required entrypoint. This helper re-checks before
/// rendering so the UI is safe regardless.
///
/// Returns the effective overall state to render (which may be
/// downgraded from `ready` to `at_risk`) plus the structured
/// downgrade details (missing required entrypoint labels + branch)
/// so the view can format a localized inline reason.
///
/// T165 (i18n): the previous version of this helper built an
/// English reason string here. That has been split out so that
/// the view layer can construct a localized message via
/// `AppLocalizations` — no BuildContext is reachable from this
/// pure-Dart helper.
class ReadinessRenderResult {
  const ReadinessRenderResult({
    required this.effectiveState,
    this.missingRequiredLabels = const [],
    this.branch,
  });

  final DemoReadinessState effectiveState;

  /// Labels of the required entrypoints that have not run on
  /// [branch]. Empty when no downgrade was applied.
  final List<String> missingRequiredLabels;

  /// Branch the FR-050 invariant was evaluated against. Null when
  /// no downgrade was applied.
  final String? branch;

  bool get wasDowngraded => missingRequiredLabels.isNotEmpty;
}

ReadinessRenderResult enforceRequiredInvariant({
  required DemoReadinessSummary summary,
  required Iterable<ValidationEntrypoint> entrypoints,
  required Iterable<ValidationRun> recentRuns,
}) {
  final requiredEntrypoints = entrypoints
      .where((e) => e.blockingLevel == BlockingLevel.required && e.enabled)
      .toList(growable: false);
  if (requiredEntrypoints.isEmpty) {
    return ReadinessRenderResult(effectiveState: summary.overallState);
  }
  // The runs handed to this helper are already branch-scoped by the
  // daemon (the caller passes `RunListQuery(branch: summary.branch)`),
  // so any run here ran on the current branch. A run's `target.id`
  // only equals the branch name when `target.kind` is `branch`; for
  // other kinds (e.g. `project`, used by the Available Validation
  // surface) `target.id` is a project/feature/change id, not a branch.
  // Match on kind so those daemon-branch-scoped runs are not falsely
  // discarded, which would otherwise leave `missing` non-empty and
  // wrongly downgrade a `ready` overall state to `at_risk`.
  final runsOnBranch = recentRuns
      .where((r) =>
          r.target.kind != ValidationTargetKind.branch ||
          r.target.id == summary.branch)
      .toList(growable: false);
  final entrypointIdsThatRan =
      runsOnBranch.map((r) => r.entrypointId).toSet();
  final missing = requiredEntrypoints
      .where((e) => !entrypointIdsThatRan.contains(e.entrypointId))
      .toList(growable: false);
  if (missing.isEmpty) {
    return ReadinessRenderResult(effectiveState: summary.overallState);
  }
  // Cap at at_risk per FR-050.
  if (summary.overallState == DemoReadinessState.ready) {
    return ReadinessRenderResult(
      effectiveState: DemoReadinessState.atRisk,
      missingRequiredLabels:
          missing.map((e) => e.label).toList(growable: false),
      branch: summary.branch,
    );
  }
  return ReadinessRenderResult(effectiveState: summary.overallState);
}
