import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../domain/models/common_enums.dart';
import '../../../domain/models/drift_signal.dart';
import '../../../domain/models/drift_supporting.dart';
import '../../../domain/severity.dart';
import '../../../ui/widgets/runtime_state_views.dart';
import '../providers.dart' as project_providers;
import 'drift_detail_view.dart';
import 'providers.dart';

/// FR-033 + FR-080 — Drift list view. T115 (Phase 6 US4).
///
/// Virtualized list (per FR-080) of [DriftSignal] rows for the
/// currently selected project. Each row surfaces status, source,
/// severity, confidence, age, scope summary, recommendation, and the
/// project-card-equivalent badge color from research R-15.
class DriftView extends ConsumerStatefulWidget {
  const DriftView({super.key});

  @override
  ConsumerState<DriftView> createState() => _DriftViewState();
}

class _DriftViewState extends ConsumerState<DriftView> {
  DriftStatus? _statusFilter;
  DriftSeverity? _severityFilter;

  @override
  Widget build(BuildContext context) {
    final selectedId = ref.watch(project_providers.selectedProjectIdProvider);
    if (selectedId == null) return const _NoProjectSelected();
    final query = DriftListQuery(
      projectId: selectedId,
      status: _statusFilter?.wireValue,
      severity: _severityFilter?.wireValue,
    );
    final list = ref.watch(driftListProvider(query));
    return Scaffold(
      appBar: AppBar(
        title: const Text('Drift'),
        actions: [
          PopupMenuButton<DriftStatus?>(
            tooltip: 'Filter status',
            icon: const Icon(Icons.filter_alt),
            onSelected: (v) => setState(() => _statusFilter = v),
            itemBuilder: (_) => [
              const PopupMenuItem(value: null, child: Text('All statuses')),
              for (final s in DriftStatus.values)
                PopupMenuItem(value: s, child: Text(s.wireValue)),
            ],
          ),
          PopupMenuButton<DriftSeverity?>(
            tooltip: 'Filter severity',
            icon: const Icon(Icons.priority_high),
            onSelected: (v) => setState(() => _severityFilter = v),
            itemBuilder: (_) => [
              const PopupMenuItem(value: null, child: Text('All severities')),
              for (final s in DriftSeverity.values)
                PopupMenuItem(value: s, child: Text(s.wireValue)),
            ],
          ),
          IconButton(
            tooltip: 'Refresh',
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(driftListProvider(query)),
          ),
        ],
      ),
      body: RuntimeStateGate(
        onUnreachable: (s) => OutageStateView(
          state: s,
          surfaceLabel: 'Drift',
          onRetry: () => ref.invalidate(driftListProvider(query)),
        ),
        onIncompatible: (s) =>
            ContractIncompatStateView(state: s, surfaceLabel: 'Drift'),
        onDegraded: (s) => DegradedStateView(
          state: s,
          surfaceLabel: 'Drift',
          onRetry: () => ref.invalidate(driftListProvider(query)),
        ),
        child: list.when(
          data: (rows) => rows.isEmpty
              ? const HealthyEmptyStateView(
                  message: 'No drift findings for this project.',
                  icon: Icons.check_circle_outline,
                )
              : ListView.builder(
                  itemCount: rows.length,
                  itemBuilder: (_, i) => _DriftRow(drift: rows[i]),
                ),
          loading: () => const LoadingStateView(),
          error: (err, _) => ErrorStateView(
            error: err,
            surfaceLabel: 'drift',
            onRetry: () => ref.invalidate(driftListProvider(query)),
          ),
        ),
      ),
    );
  }
}

class _DriftRow extends StatelessWidget {
  const _DriftRow({required this.drift});
  final DriftSignal drift;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final age = DateTime.now().difference(drift.ageStartedAt);
    // Swarm-review CR-8 + H-C3: R-15 palette + R-22 color/icon/label
    // triad. Severity label is now visible in the row subtitle so
    // colorblind operators get the same information.
    final sev = SeverityVisuals.forDrift(drift.severity, theme.brightness);
    return Semantics(
      label: '${sev.semanticDescription} drift: ${drift.summary}',
      child: ListTile(
        leading: CircleAvatar(
          backgroundColor: sev.color,
          child: Icon(sev.icon, color: sev.onColor, size: 18),
        ),
        title: Text(drift.summary),
        subtitle: Text(
          '${sev.label} · ${drift.status.wireValue} · '
          '${drift.source.wireValue} · confidence ${drift.confidence.wireValue} · '
          'scope ${drift.scope.kind.wireValue}'
          '${drift.scope.id != null ? ":${drift.scope.id}" : ""} · '
          '${_humanAge(age)}',
        ),
        trailing: Text(
          drift.findingId,
          style: theme.textTheme.labelSmall,
        ),
        onTap: () => Navigator.of(context).push(
          MaterialPageRoute<void>(
            builder: (_) => DriftDetailView(findingId: drift.findingId),
          ),
        ),
      ),
    );
  }

  static String _humanAge(Duration d) {
    if (d.inDays > 0) return '${d.inDays}d ago';
    if (d.inHours > 0) return '${d.inHours}h ago';
    if (d.inMinutes > 0) return '${d.inMinutes}m ago';
    return 'just now';
  }
}

class _NoProjectSelected extends StatelessWidget {
  const _NoProjectSelected();

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Padding(
        padding: EdgeInsets.all(32),
        child: Text(
          'No project selected.\n\n'
          'Pick a project from the Projects view to see its drift findings.',
          textAlign: TextAlign.center,
        ),
      ),
    );
  }
}

// _EmptyState replaced by shared HealthyEmptyStateView (swarm-review CR-6).
