import 'package:freezed_annotation/freezed_annotation.dart';

import 'common_enums.dart';
import 'validation_supporting.dart';

part 'validation_run.freezed.dart';
part 'validation_run.g.dart';

/// FR-048 + data-model §1.11 — Validation Run. T121 (Phase 7 US5).
///
/// **Identity**: daemon-issued `runId`. Cancel + re-trigger produces
/// a new id; runs are immutable post-creation other than state
/// transitions.
///
/// **Lifecycle (FR-048)**:
///   - `queued → running → completed`
///   - `queued | running → cancelled`
///   - `queued → failed_to_start` (only)
///   - `completed`, `cancelled`, `failed_to_start` are terminal
///   - `result` is meaningful only in terminal states
/// Validated by `lib/domain/lifecycles/validation_run_state_validator.dart`
/// (T042).
///
/// **App never executes runners** (FR-049): cancel goes through
/// `app.validation.run.cancel`; the app never terminates a local
/// subprocess.
@freezed
class ValidationRun with _$ValidationRun {
  const factory ValidationRun({
    required String runId,
    required String entrypointId,
    required ValidationTarget target,
    required RunState state,
    RunResult? result,
    DateTime? startedAt,
    DateTime? completedAt,
    required String summary,
    String? logReference,
    @Default(<RunArtifact>[]) List<RunArtifact> artifacts,
    required String triggeredBy,
    @Default(<String>[]) List<String> linkedFeatureIds,
    @Default(<String>[]) List<String> linkedChangeIds,
    required DateTime asOf,
  }) = _ValidationRun;

  factory ValidationRun.fromJson(Map<String, dynamic> json) =>
      _$ValidationRunFromJson(json);
}
