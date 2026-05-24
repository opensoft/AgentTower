import 'package:freezed_annotation/freezed_annotation.dart';

import 'common_enums.dart';
import 'validation_supporting.dart';

part 'validation_entrypoint.freezed.dart';
part 'validation_entrypoint.g.dart';

/// FR-047 + data-model §1.10 — Validation Entrypoint. T120 (Phase 7
/// US5).
///
/// **Identity**: daemon-issued `entrypointId`, stable per project. An
/// entrypoint disabled then re-enabled retains its id.
///
/// **Blocking level (FR-050 invariant)**: `BlockingLevel.required`
/// entrypoints participate in the "at most at_risk" demo-readiness
/// invariant; a required entrypoint that hasn't run on the current
/// branch caps `overallState` at `at_risk`.
///
/// **App never executes runners** (FR-049): triggering a run goes
/// through `app.validation.run.trigger`; the daemon owns execution.
/// The app surfaces state transitions only.
@freezed
class ValidationEntrypoint with _$ValidationEntrypoint {
  const factory ValidationEntrypoint({
    required String entrypointId,
    required String label,
    required EntrypointType type,
    required EntrypointScope scope,
    required String description,
    String? recommendedWhen,
    // Daemon emits `estimated_duration_ms` (build.yaml's snake_case
    // rename handles the camelCase → snake_case mapping automatically).
    int? estimatedDurationMs,
    required BlockingLevel blockingLevel,
    @Default(<String>[]) List<String> tags,
    required bool enabled,
    required DateTime asOf,
  }) = _ValidationEntrypoint;

  factory ValidationEntrypoint.fromJson(Map<String, dynamic> json) =>
      _$ValidationEntrypointFromJson(json);
}

extension ValidationEntrypointDuration on ValidationEntrypoint {
  /// Convenience accessor — daemon wire format is integer
  /// milliseconds (json_serializable can't round-trip `Duration`
  /// without a custom converter and the contract uses ms).
  Duration? get estimatedDuration => estimatedDurationMs == null
      ? null
      : Duration(milliseconds: estimatedDurationMs!);
}
