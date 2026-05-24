import 'package:freezed_annotation/freezed_annotation.dart';

import 'common_enums.dart';

part 'resolved_work_item.freezed.dart';
part 'resolved_work_item.g.dart';

/// FR-039 + F7-c — single concrete work item resolved from the
/// operator's range selection during handoff composition. T099 (Phase 5
/// US3).
///
/// **Identity**: `displayId` plus the resolution context of the
/// containing Handoff draft; not persisted outside the Handoff.
///
/// **Exclusion rendering (F7-c)**: when [exclusion] is non-null the
/// preview + submitted prompt MUST render the entry as
/// `"<displayId> (excluded: <exclusion.wireValue>)"` — the master
/// receives the explicit annotation, not a silent omission. The two
/// rendered forms (preview vs. submitted prompt) MUST match
/// byte-for-byte per SC-004.
@freezed
class ResolvedWorkItem with _$ResolvedWorkItem {
  const factory ResolvedWorkItem({
    required String displayId,
    required WorkItemKind kind,
    ResolvedExclusion? exclusion,
    String? note,
  }) = _ResolvedWorkItem;

  factory ResolvedWorkItem.fromJson(Map<String, dynamic> json) =>
      _$ResolvedWorkItemFromJson(json);
}

/// Convenience: the canonical string form a [ResolvedWorkItem] takes
/// in the resolved-list section of the prompt (F7-c). Used by both the
/// live preview and the prompt-skeleton renderer so the SC-004
/// byte-for-byte invariant cannot drift.
extension ResolvedWorkItemRendering on ResolvedWorkItem {
  String renderForPrompt() {
    final base = displayId;
    if (exclusion == null) return base;
    return '$base (excluded: ${exclusion!.wireValue})';
  }
}
