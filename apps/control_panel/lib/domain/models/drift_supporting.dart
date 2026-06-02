// ignore_for_file: invalid_annotation_target — @JsonKey(name:) on freezed
// constructor params is the documented wire-mapping pattern (see T176/event.dart).
import 'package:freezed_annotation/freezed_annotation.dart';

part 'drift_supporting.freezed.dart';
part 'drift_supporting.g.dart';

/// Supporting types for [DriftSignal] (data-model §1.9). T113
/// (Phase 6 US4).

/// FR-033 — Drift scope binds a finding to a specific operational
/// surface so the operator can act on it from the right place
/// (project card, feature/change detail, branch view, etc.).
@JsonEnum(valueField: 'wireValue')
enum DriftScopeKind {
  project('project'),
  featureChange('feature_change'),
  feature('feature'),
  change('change'),
  branch('branch'),
  worktree('worktree'),
  global('global');

  const DriftScopeKind(this.wireValue);
  final String wireValue;
  static DriftScopeKind fromWire(String v) => values.firstWhere(
        (e) => e.wireValue == v,
        orElse: () => DriftScopeKind.global,
      );
}

/// Wire field `type` is the daemon-side spelling; we keep the same name
/// on the model so json_serializable round-trips without an
/// annotation. Callers refer to it via the more conventional `kind`
/// alias defined below.
@freezed
class DriftScope with _$DriftScope {
  const factory DriftScope({
    @JsonKey(unknownEnumValue: DriftScopeKind.global)
    required DriftScopeKind type,
    String? id,
    String? label,
  }) = _DriftScope;

  factory DriftScope.fromJson(Map<String, dynamic> json) =>
      _$DriftScopeFromJson(json);
}

/// Convenience alias so the rest of the codebase reads naturally
/// (`scope.kind` matches every other "kind of thing" field in the
/// project without colliding with the `type` JSON wire name).
extension DriftScopeAlias on DriftScope {
  DriftScopeKind get kind => type;
}

/// FR-033 — Per-finding evidence item. The daemon enumerates these;
/// the app renders them with [DriftEvidenceKind]-specific affordances
/// (e.g. log excerpts get a monospace block, file pointers get an
/// Open-externally affordance).
@JsonEnum(valueField: 'wireValue')
enum DriftEvidenceKind {
  logExcerpt('log_excerpt'),
  filePointer('file_pointer'),
  agentQuote('agent_quote'),
  testResult('test_result'),
  staticCheck('static_check'),
  operatorNote('operator_note'),
  other('other');

  const DriftEvidenceKind(this.wireValue);
  final String wireValue;
  static DriftEvidenceKind fromWire(String v) => values.firstWhere(
        (e) => e.wireValue == v,
        orElse: () => DriftEvidenceKind.other,
      );
}

@freezed
class DriftEvidence with _$DriftEvidence {
  const factory DriftEvidence({
    @JsonKey(unknownEnumValue: DriftEvidenceKind.other)
    required DriftEvidenceKind kind,
    required String summary,
    String? text,
    String? filePath,
    int? lineNumber,
    String? url,
    // Swarm-review M-22: previously `agentAgentId` auto-renamed to
    // `agent_agent_id` via the snake_case field_rename build rule.
    // That wire field never appears in any daemon response; the
    // canonical field is `agent_id`.
    String? agentId,
  }) = _DriftEvidence;

  factory DriftEvidence.fromJson(Map<String, dynamic> json) =>
      _$DriftEvidenceFromJson(json);
}
