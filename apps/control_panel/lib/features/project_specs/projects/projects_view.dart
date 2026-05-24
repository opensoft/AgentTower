import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../domain/models/common_enums.dart';
import '../../../domain/models/project.dart';
import '../../../routing/route_paths.dart';
import '../../../ui/widgets/contract_checked_button.dart';
import '../../../ui/widgets/runtime_state_views.dart';
import '../providers.dart';
import 'add_project.dart';
import 'project_card.dart';
import 'remove_project.dart';

/// FR-023 / FR-024 — Projects view (cards, ≈5 sized). T087 (Phase 4 US2).
///
/// Lists every project the daemon advertises via `app.project.list`,
/// rendered as a wrapping grid of [ProjectCard]s. The "Add Project"
/// action lives in the AppBar; the per-card "Remove" action surfaces
/// through the card's overflow menu and gates on a confirm dialog
/// per FR-077.
///
/// Selecting a card sets [selectedProjectIdProvider] and navigates
/// the operator to Current Work for that project (the canonical
/// "I picked a project, now show me what's happening" jump).
class ProjectsView extends ConsumerWidget {
  const ProjectsView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final list = ref.watch(projectListProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Projects'),
        actions: [
          // FR-002 mutation gate (swarm-review CR-7): Add stays visible
          // but disables-with-tooltip on contract-incompatible / unreachable.
          ContractCheckedButton(
            onPressed: () => _onAdd(context, ref),
            builder: (ctx, onPressed, reason) => IconButton(
              tooltip: reason ?? 'Add project',
              icon: const Icon(Icons.add),
              onPressed: onPressed,
            ),
          ),
          IconButton(
            tooltip: 'Refresh',
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(projectListProvider),
          ),
        ],
      ),
      body: RuntimeStateGate(
        onUnreachable: (s) => OutageStateView(
          state: s,
          surfaceLabel: 'Projects',
          onRetry: () => ref.invalidate(projectListProvider),
        ),
        onIncompatible: (s) => ContractIncompatStateView(
          state: s,
          surfaceLabel: 'Projects',
        ),
        onDegraded: (s) => DegradedStateView(
          state: s,
          surfaceLabel: 'Projects',
          onRetry: () => ref.invalidate(projectListProvider),
        ),
        child: list.when(
          data: (projects) => projects.isEmpty
              ? const HealthyEmptyStateView(
                  message: 'No projects registered yet.\n\n'
                      'Use Add Project to register a repository, or adopt a '
                      'pane whose project_path will auto-register the project.',
                )
              : _ProjectsGrid(projects: projects),
          loading: () => const LoadingStateView(),
          error: (err, _) => ErrorStateView(
            error: err,
            surfaceLabel: 'projects',
            onRetry: () => ref.invalidate(projectListProvider),
          ),
        ),
      ),
    );
  }

  Future<void> _onAdd(BuildContext context, WidgetRef ref) async {
    final added = await showDialog<bool>(
      context: context,
      builder: (_) => const AddProjectDialog(),
    );
    if (added == true) ref.invalidate(projectListProvider);
  }
}

class _ProjectsGrid extends ConsumerWidget {
  const _ProjectsGrid({required this.projects});
  final List<Project> projects;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return LayoutBuilder(
      builder: (context, constraints) {
        // Aim for ~5 cards visible at a typical desktop width.
        final cardWidth = (constraints.maxWidth / 5).clamp(280.0, 420.0);
        return Padding(
          padding: const EdgeInsets.all(16),
          child: Wrap(
            spacing: 16,
            runSpacing: 16,
            children: [
              for (final p in projects)
                SizedBox(
                  width: cardWidth,
                  child: ProjectCard(
                    project: p,
                    onOpenProject: () => _onOpen(context, ref, p.projectId),
                    onOpenCurrentWork: () =>
                        _onOpenCurrentWork(context, ref, p.projectId),
                    onOpenSpecs: () => _onOpenSpecs(context, ref, p.projectId),
                    onOpenDrift: () => _onOpenDrift(context, ref, p.projectId),
                    onRemove: () => _onRemove(context, ref, p),
                  ),
                ),
            ],
          ),
        );
      },
    );
  }

  void _onOpen(BuildContext context, WidgetRef ref, String projectId) {
    ref.read(selectedProjectIdProvider.notifier).state = projectId;
    Navigator.of(context).pushNamed(
      const RoutePath(
        workspace: Workspace.projectSpecs,
        subViewId: 'current_work',
      ).toRouteString(),
    );
  }

  void _onOpenCurrentWork(BuildContext c, WidgetRef r, String id) =>
      _onOpen(c, r, id);

  void _onOpenSpecs(BuildContext context, WidgetRef ref, String projectId) {
    ref.read(selectedProjectIdProvider.notifier).state = projectId;
    Navigator.of(context).pushNamed(
      const RoutePath(
        workspace: Workspace.projectSpecs,
        subViewId: 'specs',
      ).toRouteString(),
    );
  }

  void _onOpenDrift(BuildContext context, WidgetRef ref, String projectId) {
    ref.read(selectedProjectIdProvider.notifier).state = projectId;
    Navigator.of(context).pushNamed(
      const RoutePath(
        workspace: Workspace.projectSpecs,
        subViewId: 'drift',
      ).toRouteString(),
    );
  }

  Future<void> _onRemove(
    BuildContext context,
    WidgetRef ref,
    Project project,
  ) async {
    final removed = await showDialog<bool>(
      context: context,
      builder: (_) => RemoveProjectDialog(
        projectId: project.projectId,
        projectLabel: project.label,
      ),
    );
    if (removed == true) ref.invalidate(projectListProvider);
  }
}

// Swarm-review CR-6: inline _EmptyState/_OutageState/_ErrorState were
// replaced with the shared widgets in ui/widgets/runtime_state_views.dart
// so every Phase 4-6 surface presents the FR-004 5-state vocabulary
// identically.

