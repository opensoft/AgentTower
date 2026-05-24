import '../../../domain/models/common_enums.dart';
import '../../../domain/models/demo_readiness_summary.dart';
import '../../../domain/models/validation_entrypoint.dart';
import '../../../domain/models/validation_run.dart';

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
/// downgraded from `ready` to `at_risk`) plus the reason for any
/// downgrade so the view can show it inline.
class ReadinessRenderResult {
  const ReadinessRenderResult({
    required this.effectiveState,
    this.downgradeReason,
  });

  final DemoReadinessState effectiveState;
  final String? downgradeReason;

  bool get wasDowngraded => downgradeReason != null;
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
  final runsOnBranch = recentRuns
      .where((r) => r.target.id == summary.branch)
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
      downgradeReason: 'Daemon reported `ready` but ${missing.length} required '
          'entrypoint${missing.length == 1 ? '' : 's'} '
          '(${missing.map((e) => e.label).join(", ")}) '
          'have not run on `${summary.branch}` (FR-050).',
    );
  }
  return ReadinessRenderResult(effectiveState: summary.overallState);
}
