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
    return Scaffold(
      appBar: AppBar(
        title: const Text('Runs'),
        actions: [
          PopupMenuButton<RunState?>(
            tooltip: 'Filter state',
            icon: const Icon(Icons.filter_alt),
            onSelected: (v) => setState(() => _stateFilter = v),
            itemBuilder: (_) => [
              const PopupMenuItem(value: null, child: Text('All states')),
              for (final s in RunState.values)
                PopupMenuItem(value: s, child: Text(s.wireValue)),
            ],
          ),
          IconButton(
            tooltip: 'Refresh',
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(validationRunListProvider(query)),
          ),
        ],
      ),
      body: RuntimeStateGate(
        onUnreachable: (s) => OutageStateView(
          state: s,
          surfaceLabel: 'Runs',
          onRetry: () => ref.invalidate(validationRunListProvider(query)),
        ),
        onIncompatible: (s) =>
            ContractIncompatStateView(state: s, surfaceLabel: 'Runs'),
        child: list.when(
          data: (rows) => rows.isEmpty
              ? const HealthyEmptyStateView(
                  message: 'No validation runs for this project yet.',
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
    final result = run.result;
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
        'state: ${run.state.wireValue}'
        '${result != null ? " · result: ${result.wireValue}" : ""} · '
        'started: ${run.startedAt?.toLocal() ?? "—"} · '
        'by: ${run.triggeredBy}',
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
    return const Center(
      child: Padding(
        padding: EdgeInsets.all(32),
        child: Text(
          'No project selected.\n\nPick a project from the Projects view '
          'to see its validation runs.',
          textAlign: TextAlign.center,
        ),
      ),
    );
  }
}
