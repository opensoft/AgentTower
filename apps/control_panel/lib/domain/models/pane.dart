// ignore_for_file: invalid_annotation_target — @JsonKey(name:) on freezed
// constructor params is the documented wire-mapping pattern (see T176/event.dart).
import 'package:freezed_annotation/freezed_annotation.dart';

import 'common_enums.dart';

part 'pane.freezed.dart';
part 'pane.g.dart';

/// FEAT-011 `app.pane` mirror. T058 (Phase 3 US1) + data-model §1.4.
///
/// State transitions per FR-014 (encoded in [PaneStateValidator]):
///   discovered-and-unmanaged ↔ discovered-and-registered (adopt / de-adopt)
///   any state → inactive/stale on pane disappearance
///   any state → discovery-degraded on probe failure
/// No terminal pane states — any state may return to a prior state on
/// rediscovery / probe recovery.
///
/// `registeredAgentId` is populated iff `state == discovered-and-registered`.
/// The Pane view (T067) uses it to render an inline link to the agent.
///
/// Identity fields required by `app.agent.register_from_pane` (FR-028a):
/// `containerId`, `tmuxSocket`, `tmuxSessionName`, `tmuxWindowIndex` (int),
/// `tmuxPaneIndex` (int), `paneId` — all six MUST round-trip byte-for-byte
/// or the daemon rejects with `pane_not_found.details.mismatch_field`.
@freezed
class Pane with _$Pane {
  const factory Pane({
    required String paneId,
    required String containerId,
    required String tmuxSocket,
    required String tmuxSessionName,
    required int tmuxWindowIndex,
    required int tmuxPaneIndex,
    required PaneState state,
    String? registeredAgentId,
    @JsonKey(unknownEnumValue: PaneDiscoveredClass.unknown)
    PaneDiscoveredClass? discoveredClass,
    DateTime? lastSeenAt,
    required DateTime asOf,
  }) = _Pane;

  factory Pane.fromJson(Map<String, dynamic> json) => _$PaneFromJson(json);
}
