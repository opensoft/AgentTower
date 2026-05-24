import 'package:freezed_annotation/freezed_annotation.dart';

import 'common_enums.dart';
import 'validation_supporting.dart';

part 'demo_readiness_summary.freezed.dart';
part 'demo_readiness_summary.g.dart';

/// FR-050 + data-model §1.12 — Demo Readiness Summary. T122 (Phase 7
/// US5).
///
/// **Source**: `app.demo_readiness.detail` (per-branch).
///
/// **Invariant (FR-050)**: `overallState` MAY be at most `at_risk`
/// if any `required`-blocking-level entrypoint has not run on
/// `branch`. The daemon enforces this; the app re-checks via
/// [enforceRequiredInvariant] before rendering so a misbehaving
/// daemon cannot trick the UI into showing `ready` when a required
/// run is missing. See `readiness_computation.dart`.
@freezed
class DemoReadinessSummary with _$DemoReadinessSummary {
  const factory DemoReadinessSummary({
    required String projectId,
    required String branch,
    required DateTime updatedAt,
    required DemoReadinessState overallState,
    required String summary,
    @Default(<BlockingFinding>[]) List<BlockingFinding> blockingFindings,
    @Default(<RecommendedNextRun>[]) List<RecommendedNextRun> recommendedNextRuns,
    @Default(<String>[]) List<String> recentRunIds,
    @Default(<String>[]) List<String> linkedFeatureIds,
    required DateTime asOf,
  }) = _DemoReadinessSummary;

  factory DemoReadinessSummary.fromJson(Map<String, dynamic> json) =>
      _$DemoReadinessSummaryFromJson(json);
}
