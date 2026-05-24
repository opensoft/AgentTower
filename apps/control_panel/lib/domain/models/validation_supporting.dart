import 'package:freezed_annotation/freezed_annotation.dart';

part 'validation_supporting.freezed.dart';
part 'validation_supporting.g.dart';

/// Supporting types for [ValidationEntrypoint] / [ValidationRun] /
/// [DemoReadinessSummary]. T119-T122 (Phase 7 US5).

/// FR-047 — scope binds the entrypoint to a specific operational
/// surface so the operator can act on the right surface.
@JsonEnum(valueField: 'wireValue')
enum EntrypointScopeKind {
  project('project'),
  branch('branch'),
  featureSet('feature_set'),
  changeSet('change_set'),
  worktree('worktree'),
  global('global');

  const EntrypointScopeKind(this.wireValue);
  final String wireValue;
  static EntrypointScopeKind fromWire(String v) => values.firstWhere(
        (e) => e.wireValue == v,
        orElse: () => EntrypointScopeKind.global,
      );
}

// Daemon wire field is `kind`; we keep that as the Dart field name
// (build.yaml's snake_case rename leaves it unchanged) so no
// @JsonKey override is needed.
@freezed
class EntrypointScope with _$EntrypointScope {
  const factory EntrypointScope({
    required EntrypointScopeKind kind,
    String? id,
    String? label,
  }) = _EntrypointScope;

  factory EntrypointScope.fromJson(Map<String, dynamic> json) =>
      _$EntrypointScopeFromJson(json);
}

/// FR-049 — what a validation run was launched against. Mirrors the
/// scope of its entrypoint but is captured at trigger time so a
/// later entrypoint-scope change doesn't retroactively change a
/// run's target.
@JsonEnum(valueField: 'wireValue')
enum ValidationTargetKind {
  project('project'),
  branch('branch'),
  featureSet('feature_set'),
  changeSet('change_set');

  const ValidationTargetKind(this.wireValue);
  final String wireValue;
  static ValidationTargetKind fromWire(String v) => values.firstWhere(
        (e) => e.wireValue == v,
        orElse: () => ValidationTargetKind.project,
      );
}

@freezed
class ValidationTarget with _$ValidationTarget {
  const factory ValidationTarget({
    required ValidationTargetKind kind,
    required String id,
    String? label,
  }) = _ValidationTarget;

  factory ValidationTarget.fromJson(Map<String, dynamic> json) =>
      _$ValidationTargetFromJson(json);
}

/// FR-048 — output artifact produced by a validation run (e.g. a
/// JUnit XML, a coverage report, a screenshot). The app surfaces
/// these as Open-externally links via SafeUrlLauncher; it never
/// reads the artifact body itself.
@freezed
class RunArtifact with _$RunArtifact {
  const factory RunArtifact({
    required String name,
    required String uri,
    String? mimeType,
    int? sizeBytes,
  }) = _RunArtifact;

  factory RunArtifact.fromJson(Map<String, dynamic> json) =>
      _$RunArtifactFromJson(json);
}

/// FR-050 — finding that blocks demo readiness. The daemon
/// enumerates these (drift signals, failed required runs, etc.);
/// the app renders + deep-links them.
@JsonEnum(valueField: 'wireValue')
enum BlockingFindingKind {
  driftSignal('drift_signal'),
  failedRun('failed_run'),
  missingRequiredRun('missing_required_run'),
  staleRun('stale_run'),
  other('other');

  const BlockingFindingKind(this.wireValue);
  final String wireValue;
  static BlockingFindingKind fromWire(String v) => values.firstWhere(
        (e) => e.wireValue == v,
        orElse: () => BlockingFindingKind.other,
      );
}

@freezed
class BlockingFinding with _$BlockingFinding {
  const factory BlockingFinding({
    required BlockingFindingKind kind,
    required String summary,
    String? linkedDriftFindingId,
    String? linkedRunId,
    String? linkedEntrypointId,
  }) = _BlockingFinding;

  factory BlockingFinding.fromJson(Map<String, dynamic> json) =>
      _$BlockingFindingFromJson(json);
}

/// FR-050 — recommended next run as part of the demo-readiness
/// summary. The daemon produces this list; the app renders a
/// "Run this now" affordance per entry that defers to
/// `app.validation.run.trigger`.
@freezed
class RecommendedNextRun with _$RecommendedNextRun {
  const factory RecommendedNextRun({
    required String entrypointId,
    required String entrypointLabel,
    required String reason,
    @Default(false) bool priority,
  }) = _RecommendedNextRun;

  factory RecommendedNextRun.fromJson(Map<String, dynamic> json) =>
      _$RecommendedNextRunFromJson(json);
}
