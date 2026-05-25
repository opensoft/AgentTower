import '../../../core/l10n/app_localizations.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../domain/models/common_enums.dart';
import '../../../domain/models/validation_run.dart';
import '../../../ui/widgets/runtime_state_views.dart';
import '../../project_specs/providers.dart' as project_providers;
import '../providers.dart';
import 'cancel_run.dart';

/// FR-048 + FR-080 — Runs view. T126 (Phase 7 US5).
///
/// Renders runs with the 5-state vocabulary + 5-result vocabulary.
/// Virtualized via `ListView.builder` per FR-080.
class RunsView extends ConsumerStatefulWidget {
  const RunsView({super.key});

  @override
  ConsumerState<RunsView> createState() => _RunsViewState();
}

class _RunsViewState extends ConsumerState<RunsView> {
  RunState? _stateFilter;

  @override
  Widget build(BuildContext context) {
    final selectedId = ref.watch(project_providers.selectedProjectIdProvider);
    if (selectedId == null) return const _NoProjectSelected();
    final query = RunListQuery(
      projectId: selectedId,
      state: _stateFilter?.wireValue,
    );
    final list = ref.watch(validationRunListProvider(query));
    final l10n = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.runsViewTitle),
        actions: [
          PopupMenuButton<RunState?>(
            tooltip: l10n.runsViewFilterTooltip,
            icon: const Icon(Icons.filter_alt),
            onSelected: (v) => setState(() => _stateFilter = v),
            itemBuilder: (_) => [
              PopupMenuItem(value: null, child: Text(l10n.runsViewFilterAllStates)),
              for (final s in RunState.values)
                PopupMenuItem(value: s, child: Text(s.wireValue)),
            ],
          ),
          IconButton(
            tooltip: l10n.commonRefresh,
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(validationRunListProvider(query)),
          ),
        ],
      ),
      body: RuntimeStateGate(
        onUnreachable: (s) => OutageStateView(
          state: s,
          surfaceLabel: l10n.runsViewTitle,
          onRetry: () => ref.invalidate(validationRunListProvider(query)),
        ),
        onIncompatible: (s) =>
            ContractIncompatStateView(state: s, surfaceLabel: l10n.runsViewTitle),
        child: list.when(
          data: (rows) => rows.isEmpty
              ? HealthyEmptyStateView(
                  message: l10n.runsViewEmptyState,
                  icon: Icons.history,
                )
              : ListView.builder(
                  itemCount: rows.length,
                  itemBuilder: (_, i) => _RunRow(run: rows[i]),
                ),
          loading: () => const LoadingStateView(),
          error: (err, _) => ErrorStateView(
            error: err,
            surfaceLabel: 'runs',
            onRetry: () => ref.invalidate(validationRunListProvider(query)),
          ),
        ),
      ),
    );
  }
}

class _RunRow extends StatelessWidget {
  const _RunRow({required this.run});
  final ValidationRun run;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final l10n = AppLocalizations.of(context);
    final result = run.result;
    final resultSuffix =
        result != null ? ' · result: ${result.wireValue}' : '';
    final startedAt = run.startedAt?.toLocal().toString() ?? '—';
    return ListTile(
      leading: CircleAvatar(
        backgroundColor: _stateColor(theme, run.state),
        child: Icon(
          _stateIcon(run.state),
          size: 18,
          color: theme.colorScheme.onPrimary,
        ),
      ),
      title: Text('${run.entrypointId} → ${run.target.id}'),
      subtitle: Text(
        l10n.runsViewRowSubtitle(
          run.state.wireValue,
          resultSuffix,
          startedAt,
          run.triggeredBy,
        ),
      ),
      trailing: SizedBox(
        width: 140,
        child: CancelRunButton(run: run),
      ),
    );
  }

  static Color _stateColor(ThemeData theme, RunState s) => switch (s) {
        RunState.queued => theme.colorScheme.secondary,
        RunState.running => theme.colorScheme.primary,
        RunState.completed => theme.colorScheme.tertiary,
        RunState.cancelled => theme.colorScheme.outline,
        RunState.failedToStart => theme.colorScheme.error,
      };

  static IconData _stateIcon(RunState s) => switch (s) {
        RunState.queued => Icons.schedule,
        RunState.running => Icons.play_arrow,
        RunState.completed => Icons.check,
        RunState.cancelled => Icons.cancel,
        RunState.failedToStart => Icons.error,
      };
}

class _NoProjectSelected extends StatelessWidget {
  const _NoProjectSelected();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Text(
          AppLocalizations.of(context).runsViewNoProjectSelected,
          textAlign: TextAlign.center,
        ),
      ),
    );
  }
}
