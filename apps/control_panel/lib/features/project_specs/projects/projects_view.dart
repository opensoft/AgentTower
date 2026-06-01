import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/l10n/app_localizations.dart';
import '../../../core/persistence/sort_filter_state.dart';
import '../../../core/providers.dart';
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
///
/// FR-078 (T180): persisted card sort (name / recent activity), global
/// scope (Projects is not a project-scoped view).
class ProjectsView extends ConsumerStatefulWidget {
  const ProjectsView({super.key});

  @override
  ConsumerState<ProjectsView> createState() => _ProjectsViewState();
}

class _ProjectsViewState extends ConsumerState<ProjectsView> {
  static const _viewId = 'project_specs/projects';

  /// `'name'` | `'recent'` | `null` (daemon order).
  String? _sort;
  bool _loaded = false;

  @override
  Widget build(BuildContext context) {
    if (!_loaded) {
      _loaded = true;
      final p = ref.read(sortFilterRepositoryProvider).load(viewId: _viewId);
      _sort = switch (p.sortField) {
        'label' => 'name',
        'last_activity' => 'recent',
        _ => null,
      };
    }
    final list = ref.watch(projectListProvider);
    final l10n = AppLocalizations.of(context);
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.projectsViewTitle),
        actions: [
          // FR-002 mutation gate (swarm-review CR-7): Add stays visible
          // but disables-with-tooltip on contract-incompatible / unreachable.
          ContractCheckedButton(
            onPressed: () => _onAdd(context),
            builder: (ctx, onPressed, reason) => IconButton(
              tooltip: reason ?? l10n.projectsAddProjectTooltip,
              icon: const Icon(Icons.add),
              onPressed: onPressed,
            ),
          ),
          PopupMenuButton<String>(
            tooltip: l10n.projectsSortTooltip,
            icon: Icon(Icons.sort, color: _sort != null ? scheme.primary : null),
            onSelected: _onSort,
            itemBuilder: (_) => [
              CheckedPopupMenuItem<String>(
                value: 'name',
                checked: _sort == 'name',
                child: Text(l10n.projectsSortByName),
              ),
              CheckedPopupMenuItem<String>(
                value: 'recent',
                checked: _sort == 'recent',
                child: Text(l10n.projectsSortByRecent),
              ),
            ],
          ),
          IconButton(
            tooltip: l10n.projectsRefreshTooltip,
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(projectListProvider),
          ),
        ],
      ),
      body: RuntimeStateGate(
        onUnreachable: (s) => OutageStateView(
          state: s,
          surfaceLabel: l10n.projectsSurfaceLabel,
          onRetry: () => ref.invalidate(projectListProvider),
        ),
        onIncompatible: (s) => ContractIncompatStateView(
          state: s,
          surfaceLabel: l10n.projectsSurfaceLabel,
        ),
        onDegraded: (s) => DegradedStateView(
          state: s,
          surfaceLabel: l10n.projectsSurfaceLabel,
          onRetry: () => ref.invalidate(projectListProvider),
        ),
        child: list.when(
          data: (projects) => projects.isEmpty
              ? HealthyEmptyStateView(
                  message: l10n.projectsEmptyMessage,
                )
              : _ProjectsGrid(projects: _sorted(projects)),
          loading: () => const LoadingStateView(),
          error: (err, _) => ErrorStateView(
            error: err,
            surfaceLabel: l10n.projectsSurfaceLabelLower,
            onRetry: () => ref.invalidate(projectListProvider),
          ),
        ),
      ),
    );
  }

  List<Project> _sorted(List<Project> projects) {
    switch (_sort) {
      case 'name':
        return [...projects]..sort(
            (a, b) => a.label.toLowerCase().compareTo(b.label.toLowerCase()));
      case 'recent':
        return [...projects]
          ..sort((a, b) => b.lastActivityAt.compareTo(a.lastActivityAt));
      default:
        return projects;
    }
  }

  void _onSort(String key) {
    setState(() => _sort = key);
    final sortField = key == 'name' ? 'label' : 'last_activity';
    final dir = key == 'name' ? SortDirection.asc : SortDirection.desc;
    ref.read(sortFilterRepositoryProvider).save(
          viewId: _viewId,
          value: ListSortFilterState(
            sortField: sortField,
            sortDirection: dir,
          ),
        );
  }

  Future<void> _onAdd(BuildContext context) async {
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

