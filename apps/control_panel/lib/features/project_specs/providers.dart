import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';
import '../../core/json_utils.dart';
import '../../domain/models/feature_change_status.dart';
import '../../domain/models/project.dart';

/// Riverpod providers for the Project + Specs workspace. T087+ (Phase 4 US2).
///
/// Each `*ListProvider` is a `FutureProvider.autoDispose` matching the
/// pattern established in `agent_ops/providers.dart` (T065+).
///
/// Refresh-on-invalidate is the live-update strategy for MVP; the
/// FR-064 2 s live-update budget for project surfaces lands as a
/// Phase 9 polish task (T155 surface coverage).

// ============================================================== Projects

final projectListProvider =
    FutureProvider.autoDispose<List<Project>>((ref) async {
  final page = await ref.watch(appClientProvider).projectList();
  final asOf = DateTime.now().toUtc();
  return page.items
      .map((m) => Project.fromJson(withAsOfDefault(m, asOf)))
      .toList(growable: false);
});

final projectDetailProvider =
    FutureProvider.autoDispose.family<Project, String>((ref, projectId) async {
  final raw = await ref.watch(appClientProvider).projectDetail(projectId);
  return Project.fromJson(withAsOfDefault(raw, DateTime.now().toUtc()));
});

/// Operator-selected current project. `null` while no project is
/// active (first-launch unresolved-project case per FR-076).
///
/// This is in-memory only; the persisted `lastActiveProjectId` lives
/// in `ux-state.json` and is restored on launch by
/// [firstLaunchResolution].
final selectedProjectIdProvider = StateProvider<String?>((_) => null);

/// Convenience: the currently selected [Project] if any, fetched via
/// [projectDetailProvider]. Returns `null` if no project is selected.
final selectedProjectProvider =
    FutureProvider.autoDispose<Project?>((ref) async {
  final id = ref.watch(selectedProjectIdProvider);
  if (id == null) return null;
  return ref.watch(projectDetailProvider(id).future);
});

// ========================================================== FeatureChange

final featureChangeListProvider =
    FutureProvider.autoDispose.family<List<FeatureChangeStatus>, String>(
  (ref, projectId) async {
    final page = await ref
        .watch(appClientProvider)
        .featureChangeList(projectId: projectId);
    final asOf = DateTime.now().toUtc();
    return page.items
        .map((m) => FeatureChangeStatus.fromJson(withAsOfDefault(m, asOf)))
        .toList(growable: false);
  },
);

final featureChangeDetailProvider =
    FutureProvider.autoDispose.family<FeatureChangeStatus, String>(
  (ref, featureChangeId) async {
    final raw = await ref
        .watch(appClientProvider)
        .featureChangeDetail(featureChangeId);
    return FeatureChangeStatus.fromJson(
      withAsOfDefault(raw, DateTime.now().toUtc()),
    );
  },
);

/// Active feature/change for the currently selected project — what
/// Current Work and the project-card "active feature" badge render.
/// Returns `null` when no project is selected or the project has no
/// active feature/change.
final activeFeatureChangeProvider =
    FutureProvider.autoDispose<FeatureChangeStatus?>((ref) async {
  final project = await ref.watch(selectedProjectProvider.future);
  if (project == null) return null;
  final activeId = project.activeFeatureChangeId;
  if (activeId == null) return null;
  return ref.watch(featureChangeDetailProvider(activeId).future);
});
