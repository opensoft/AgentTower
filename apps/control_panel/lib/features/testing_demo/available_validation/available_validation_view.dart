import '../../../core/l10n/app_localizations.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/persistence/sort_filter_state.dart';
import '../../../core/providers.dart';
import '../../../domain/models/common_enums.dart';
import '../../../domain/models/validation_entrypoint.dart';
import '../../../ui/widgets/list_controls.dart';
import '../../../ui/widgets/runtime_state_views.dart';
import '../../project_specs/providers.dart' as project_providers;
import '../providers.dart';
import 'trigger_run.dart';

/// FR-046 + FR-047 — Available Validation view. T124 (Phase 7 US5).
///
/// Renders entrypoints grouped by [EntrypointScope.kind]. Each card
/// shows label / type / scope / description / blocking level /
/// estimated duration / enabled state and an inline Run button.
///
/// FR-078 (T180): persisted blocking-level filter, per-project scope.
class AvailableValidationView extends ConsumerStatefulWidget {
  const AvailableValidationView({super.key});

  @override
  ConsumerState<AvailableValidationView> createState() =>
      _AvailableValidationViewState();
}

class _AvailableValidationViewState
    extends ConsumerState<AvailableValidationView> {
  static const _viewId = 'testing_demo/available_validation';
  BlockingLevel? _filter;
  String? _loadedForProject;

  @override
  Widget build(BuildContext context) {
    final selectedId = ref.watch(project_providers.selectedProjectIdProvider);
    if (selectedId == null) return const _NoProjectSelected();
    if (selectedId != _loadedForProject) {
      _loadedForProject = selectedId;
      final p = ref
          .read(sortFilterRepositoryProvider)
          .load(viewId: _viewId, projectId: selectedId);
      _filter = filterValueFromWire(
          p.filters['blocking_level'], BlockingLevel.values, (s) => s.wireValue);
    }
    final query = EntrypointListQuery(projectId: selectedId);
    final list = ref.watch(validationEntrypointListProvider(query));
    final l10n = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.availableValidationTitle),
        actions: [
          EnumFilterMenu<BlockingLevel>(
            tooltip: l10n.availableValidationFilterTooltip,
            allLabel: l10n.availableValidationFilterAll,
            value: _filter,
            options: BlockingLevel.values,
            labelOf: (s) => s.wireValue,
            onSelected: (v) => _onFilter(selectedId, v),
          ),
          IconButton(
            tooltip: l10n.commonRefresh,
            icon: const Icon(Icons.refresh),
            onPressed: () =>
                ref.invalidate(validationEntrypointListProvider(query)),
          ),
        ],
      ),
      body: RuntimeStateGate(
        onUnreachable: (s) => OutageStateView(
          state: s,
          surfaceLabel: l10n.availableValidationTitle,
          onRetry: () =>
              ref.invalidate(validationEntrypointListProvider(query)),
        ),
        onIncompatible: (s) => ContractIncompatStateView(
          state: s,
          surfaceLabel: l10n.availableValidationTitle,
        ),
        child: list.when(
          data: (rows) {
            if (rows.isEmpty) {
              return HealthyEmptyStateView(
                message: l10n.availableValidationEmptyState,
                icon: Icons.science_outlined,
              );
            }
            final filtered = _filter == null
                ? rows
                : rows
                    .where((e) => e.blockingLevel == _filter)
                    .toList(growable: false);
            if (filtered.isEmpty) {
              return FilterNoMatch(
                message: l10n.availableValidationFilterNoMatch,
              );
            }
            return _GroupedList(entries: filtered, projectId: selectedId);
          },
          loading: () => const LoadingStateView(),
          error: (err, _) => ErrorStateView(
            error: err,
            surfaceLabel: 'available validation',
            onRetry: () =>
                ref.invalidate(validationEntrypointListProvider(query)),
          ),
        ),
      ),
    );
  }

  void _onFilter(String projectId, BlockingLevel? v) {
    setState(() => _filter = v);
    ref.read(sortFilterRepositoryProvider).save(
          viewId: _viewId,
          projectId: projectId,
          value: ListSortFilterState(
            filters: {if (v != null) 'blocking_level': v.wireValue},
          ),
        );
  }
}

class _GroupedList extends StatelessWidget {
  const _GroupedList({required this.entries, required this.projectId});
  final List<ValidationEntrypoint> entries;
  final String projectId;

  @override
  Widget build(BuildContext context) {
    // Group by scope kind. Sort within group by blocking level
    // descending (required first), then by label.
    final byScope = <String, List<ValidationEntrypoint>>{};
    for (final e in entries) {
      final key = e.scope.kind.wireValue;
      (byScope[key] ??= []).add(e);
    }
    for (final list in byScope.values) {
      list.sort((a, b) {
        final ar = _blockingRank(a.blockingLevel);
        final br = _blockingRank(b.blockingLevel);
        if (ar != br) return br - ar;
        return a.label.compareTo(b.label);
      });
    }
    final orderedScopes = byScope.keys.toList()..sort();
    return ListView.builder(
      itemCount: orderedScopes.length,
      itemBuilder: (_, scopeIdx) {
        final scope = orderedScopes[scopeIdx];
        final group = byScope[scope]!;
        return Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Text(
                  AppLocalizations.of(context)
                      .availableValidationScopeHeader(scope),
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              ),
              for (final e in group)
                _EntrypointCard(entrypoint: e, projectId: projectId),
            ],
          ),
        );
      },
    );
  }

  static int _blockingRank(BlockingLevel b) => switch (b) {
        BlockingLevel.required => 3,
        BlockingLevel.recommended => 2,
        BlockingLevel.informational => 1,
      };
}

class _EntrypointCard extends StatelessWidget {
  const _EntrypointCard({required this.entrypoint, required this.projectId});
  final ValidationEntrypoint entrypoint;
  final String projectId;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final l10n = AppLocalizations.of(context);
    final duration = entrypoint.estimatedDuration;
    final scopeIdSuffix =
        entrypoint.scope.id != null ? ':${entrypoint.scope.id}' : '';
    final durationSuffix =
        duration != null ? ' · ~${duration.inSeconds}s' : '';
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text(
                        entrypoint.label,
                        style: theme.textTheme.titleSmall,
                      ),
                      const SizedBox(width: 8),
                      _BlockingChip(level: entrypoint.blockingLevel),
                    ],
                  ),
                  const SizedBox(height: 4),
                  Text(
                    l10n.availableValidationCardMeta(
                      entrypoint.type.wireValue,
                      entrypoint.scope.kind.wireValue,
                      scopeIdSuffix,
                      entrypoint.enabled.toString(),
                      durationSuffix,
                    ),
                    style: theme.textTheme.bodySmall,
                  ),
                  const SizedBox(height: 4),
                  Text(entrypoint.description),
                  if (entrypoint.recommendedWhen != null) ...[
                    const SizedBox(height: 4),
                    Text(
                      l10n.availableValidationRecommendedWhen(
                        entrypoint.recommendedWhen!,
                      ),
                      style: theme.textTheme.labelSmall,
                    ),
                  ],
                ],
              ),
            ),
            const SizedBox(width: 12),
            TriggerRunButton(
              entrypoint: entrypoint,
              projectId: projectId,
              // Default target is the project; richer pickers land in
              // a future polish item if operators want branch-scoped
              // triggers from this surface.
              targetKind: 'project',
              targetId: projectId,
            ),
          ],
        ),
      ),
    );
  }
}

class _BlockingChip extends StatelessWidget {
  const _BlockingChip({required this.level});
  final BlockingLevel level;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final l10n = AppLocalizations.of(context);
    final (color, label) = switch (level) {
      BlockingLevel.required => (
          theme.colorScheme.error,
          l10n.availableValidationBlockingRequired,
        ),
      BlockingLevel.recommended => (
          theme.colorScheme.tertiary,
          l10n.availableValidationBlockingRecommended,
        ),
      BlockingLevel.informational => (
          theme.colorScheme.secondary,
          l10n.availableValidationBlockingInformational,
        ),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(
        label,
        style: TextStyle(color: color, fontSize: 11),
      ),
    );
  }
}

class _NoProjectSelected extends StatelessWidget {
  const _NoProjectSelected();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Text(
          AppLocalizations.of(context).availableValidationNoProjectSelected,
          textAlign: TextAlign.center,
        ),
      ),
    );
  }
}
