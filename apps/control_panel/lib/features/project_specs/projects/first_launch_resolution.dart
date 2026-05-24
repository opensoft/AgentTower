import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../domain/models/adopted_agent.dart';
import '../providers.dart';

/// FR-076 first-launch project resolution. T096 (Phase 4 US2).
///
/// On a "compatible app launch" (per FR-070) the app attempts to
/// restore the persisted `last_active_project_id` from ux-state.
/// Resolution order:
///
///   1. If a `projectId` is persisted AND the daemon's project list
///      contains it → restore selection. Land the operator on the
///      project's last sub-view per [WorkspaceSelection].
///   2. If a `projectId` is persisted but does NOT resolve → drop the
///      selection, land on the Projects view with no project selected,
///      and surface the FR-076 non-blocking banner naming the project
///      that could not be restored. The banner widget lives in the
///      shell; this layer only exposes the unresolved project id via
///      [unresolvedPersistedProjectIdProvider] so the shell can read
///      it on first frame.
///   3. If no `projectId` is persisted AND there is exactly one
///      adopted agent whose `project_path` matches a registered
///      project → infer that project as the selection (one-shot
///      inference per Assumption: project registration model).
///   4. Otherwise → no selection; operator lands on Projects view.
///
/// This file exposes [FirstLaunchResolution.run] which the shell
/// invokes once at first-frame after the daemon bootstrap completes.

/// Carries the FR-076 banner state for the shell.
class FirstLaunchOutcome {
  const FirstLaunchOutcome({
    required this.selectedProjectId,
    this.unresolvedPersistedProjectId,
    this.inferredFromAgentId,
  });

  /// The project id the app ended on after resolution, or `null` if
  /// no project was selected.
  final String? selectedProjectId;

  /// The persisted project id that could NOT be resolved. When
  /// non-null, the shell renders the FR-076 banner.
  final String? unresolvedPersistedProjectId;

  /// The adopted agent whose `project_path` was used to infer the
  /// selection (case 3). `null` unless inference was the resolution
  /// mechanism.
  final String? inferredFromAgentId;

  bool get hasUnresolvedBanner => unresolvedPersistedProjectId != null;
}

/// Provider that drives the FR-076 banner. `null` until [FirstLaunchResolution.run]
/// completes.
final firstLaunchOutcomeProvider =
    StateProvider<FirstLaunchOutcome?>((_) => null);

class FirstLaunchResolution {
  FirstLaunchResolution(this.ref);
  final Ref ref;

  /// Runs the FR-076 resolution. Idempotent: subsequent calls are
  /// no-ops if [firstLaunchOutcomeProvider] is already populated.
  Future<FirstLaunchOutcome> run({
    required String? persistedProjectId,
    required List<AdoptedAgent> currentAdoptedAgents,
  }) async {
    final existing = ref.read(firstLaunchOutcomeProvider);
    if (existing != null) return existing;

    final projects = await ref.read(projectListProvider.future);
    final knownIds = projects.map((p) => p.projectId).toSet();
    final knownPaths = {
      for (final p in projects) p.repositoryPath: p.projectId,
    };

    String? selection;
    String? unresolved;
    String? inferredFromAgent;

    if (persistedProjectId != null && knownIds.contains(persistedProjectId)) {
      // Case 1: restore.
      selection = persistedProjectId;
    } else if (persistedProjectId != null) {
      // Case 2: persisted but not resolvable → banner.
      unresolved = persistedProjectId;
      selection = null;
    } else {
      // Case 3: try one-shot inference from adopted agents.
      final matchedAgents = currentAdoptedAgents
          .where((a) => knownPaths.containsKey(a.projectPath))
          .toList(growable: false);
      if (matchedAgents.length == 1) {
        final a = matchedAgents.single;
        selection = knownPaths[a.projectPath];
        inferredFromAgent = a.agentId;
      }
    }

    final outcome = FirstLaunchOutcome(
      selectedProjectId: selection,
      unresolvedPersistedProjectId: unresolved,
      inferredFromAgentId: inferredFromAgent,
    );
    ref.read(firstLaunchOutcomeProvider.notifier).state = outcome;
    if (selection != null) {
      ref.read(selectedProjectIdProvider.notifier).state = selection;
    }
    return outcome;
  }
}

final firstLaunchResolutionProvider = Provider<FirstLaunchResolution>(
  (ref) => FirstLaunchResolution(ref),
);
