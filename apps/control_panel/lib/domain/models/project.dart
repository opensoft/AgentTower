import 'package:freezed_annotation/freezed_annotation.dart';

import 'badges.dart';

part 'project.freezed.dart';
part 'project.g.dart';

/// FEAT-011 `app.project` mirror. T082 (Phase 4 US2) + data-model §1.1.
///
/// **Identity** (per FR-026 + spec Key Entities): daemon-issued
/// `projectId`, derived from the canonicalized repository absolute path.
/// Same repository path → same project id. Worktrees and branches are
/// subordinate context, not separate projects.
///
/// **Master fan-out (Round-2 finding F-A7)**: `primaryMasterAgentIds`
/// is capped at 2 on the daemon side; overflow counts beyond the
/// visible strip surface in [masterOverflowCount]. `subAgentCount`
/// is the total descendants-of-any-master roll-up for the card; the
/// per-master sub-agent rollup lives on [MasterSummary] instead.
///
/// **Persistence boundary (FR-005 / FR-069)**: `Project` is a daemon-
/// owned read mirror. The app NEVER persists project data — only the
/// `lastActiveProjectId` selector lives in `ux-state.json`.
@freezed
class Project with _$Project {
  const factory Project({
    required String projectId,
    required String label,
    required String repositoryPath,
    required RepoStateBadge repoState,
    required BranchWorktreeBadge activeBranch,
    String? activeFeatureChangeId,
    String? currentDrivingMasterAgentId,
    @Default(<String>[]) List<String> primaryMasterAgentIds,
    @Default(0) int masterOverflowCount,
    @Default(0) int subAgentCount,
    required ValidationBadge validationBadge,
    DateTime? validationLastRunAt,
    required DriftBadge driftBadge,
    String? driftSource,
    DateTime? driftAge,
    required AttentionSummary attentionSummary,
    @Default(0) int unreadNotificationCount,
    required DateTime lastActivityAt,
    required DateTime asOf,
  }) = _Project;

  factory Project.fromJson(Map<String, dynamic> json) =>
      _$ProjectFromJson(json);
}
