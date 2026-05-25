import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/l10n/app_localizations.dart';
import '../../../domain/models/common_enums.dart';
import '../../../features/shell/runtime_state_provider.dart';
import '../providers.dart';

/// Agent Operations → Dashboard. T065 (Phase 3 US1) + FR-012.
///
/// Renders the FEAT-011 v1.0 `app.dashboard` payload directly (review
/// fix C8 / Option A). FR-012 also enumerates "pane count BY STATE",
/// "registered-agent count BY STATE", "recently-skipped-route count",
/// and "recommended next action" — none of which `app.dashboard` v1.0
/// exposes. Those tiles are suppressed (with `TODO(openspec)` markers)
/// until the openspec change `extend-app-dashboard-fields-for-feat012`
/// lands and bumps the contract to 1.1. The Dashboard remains
/// functional against today's daemon; the missing tiles do not block
/// US1 sign-off.
///
/// On daemon outage the surface short-circuits to a `runtime-unreachable`
/// empty state per FR-004 with an explicit "Retry connection" affordance
/// (review fix H4 / arch lane).
class DashboardView extends ConsumerWidget {
  const DashboardView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final runtime = ref.watch(runtimeStateProvider);

    // FR-004 short-circuit: when the daemon is unreachable the dashboard
    // would otherwise spin forever waiting for the FutureProvider. Render
    // the documented empty state directly + offer Retry connection.
    if (runtime.kind == RuntimeStateKind.runtimeUnreachable) {
      return _OutageState(
        runtime: runtime,
        onRetry: () => ref.invalidate(dashboardProvider),
      );
    }

    final dashboard = ref.watch(dashboardProvider);
    return Padding(
      padding: const EdgeInsets.all(16),
      child: dashboard.when(
        data: (data) => _DashboardBody(data: data, runtime: runtime),
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (err, _) => _DashboardError(
          error: err,
          onRetry: () => ref.invalidate(dashboardProvider),
        ),
      ),
    );
  }
}

class _DashboardBody extends StatelessWidget {
  const _DashboardBody({required this.data, required this.runtime});

  final Map<String, dynamic> data;
  final RuntimeState runtime;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final counts = (data['counts'] as Map<String, dynamic>?) ?? const {};
    final containers =
        (counts['containers'] as Map<String, dynamic>?) ?? const {};
    final panes = (counts['panes'] as Map<String, dynamic>?) ?? const {};
    final agents = (counts['agents'] as Map<String, dynamic>?) ?? const {};
    final agentsByRole =
        (agents['by_role'] as Map<String, dynamic>?) ?? const {};
    final logAttachments =
        (counts['log_attachments'] as Map<String, dynamic>?) ?? const {};
    final events = (counts['events'] as Map<String, dynamic>?) ?? const {};
    final queue = (counts['queue'] as Map<String, dynamic>?) ?? const {};
    final routes = (counts['routes'] as Map<String, dynamic>?) ?? const {};

    return ListView(
      children: [
        _Section(
          title: l10n.dashboardSectionDaemon,
          child: Wrap(
            spacing: 24,
            runSpacing: 8,
            children: [
              _Stat(
                label: l10n.dashboardStatState,
                value: _runtimeLabel(l10n, runtime.kind),
              ),
              _Stat(
                label: l10n.dashboardStatDaemonVersion,
                value: runtime.daemonVersion ?? '—',
              ),
              _Stat(
                label: l10n.dashboardStatContractVersion,
                value: runtime.contractCompat?.daemonVersion.toString() ?? '—',
              ),
            ],
          ),
        ),
        _Section(
          title: l10n.dashboardSectionContainers,
          child: Wrap(
            spacing: 24,
            runSpacing: 8,
            children: [
              _Stat(
                label: l10n.dashboardStatActive,
                value: '${containers['active'] ?? 0}',
              ),
              _Stat(
                label: l10n.dashboardStatInactive,
                value: '${containers['inactive'] ?? 0}',
              ),
              _Stat(
                label: l10n.dashboardStatDegradedScan,
                value: '${containers['degraded_scan'] ?? 0}',
              ),
            ],
          ),
        ),
        _Section(
          title: l10n.dashboardSectionPanes,
          child: Wrap(
            spacing: 24,
            runSpacing: 8,
            children: [
              _Stat(
                label: l10n.dashboardStatTotal,
                value: '${panes['total'] ?? 0}',
              ),
              _Stat(
                label: l10n.dashboardStatRegistered,
                value: '${panes['registered'] ?? 0}',
              ),
              _Stat(
                label: l10n.dashboardStatUnregistered,
                value: '${panes['unregistered'] ?? 0}',
              ),
            ],
          ),
        ),
        // TODO(openspec/extend-app-dashboard-fields-for-feat012):
        // re-enable a per-state pane breakdown when the contract 1.1
        // adds counts.panes.by_state.
        _Section(
          title: l10n.dashboardSectionAgents,
          child: Wrap(
            spacing: 24,
            runSpacing: 8,
            children: [
              _Stat(
                label: l10n.dashboardStatTotal,
                value: '${agents['total'] ?? 0}',
              ),
              for (final entry in agentsByRole.entries)
                _Stat(
                  label: l10n.dashboardStatAgentByRole(entry.key),
                  value: '${entry.value}',
                ),
            ],
          ),
        ),
        _Section(
          title: l10n.dashboardSectionLogAttachments,
          child: Wrap(
            spacing: 24,
            runSpacing: 8,
            children: [
              _Stat(
                label: l10n.dashboardStatActive,
                value: '${logAttachments['active'] ?? 0}',
              ),
              _Stat(
                label: l10n.dashboardStatDegraded,
                value: '${logAttachments['degraded'] ?? 0}',
              ),
              _Stat(
                label: l10n.dashboardStatNone,
                value: '${logAttachments['none'] ?? 0}',
              ),
            ],
          ),
        ),
        _Section(
          title: l10n.dashboardSectionEventsQueueRoutes,
          child: Wrap(
            spacing: 24,
            runSpacing: 8,
            children: [
              _Stat(
                label: l10n.dashboardStatEventsTotal,
                value: '${events['total'] ?? 0}',
              ),
              _Stat(
                label: l10n.dashboardStatQueueQueued,
                value: '${queue['queued'] ?? 0}',
              ),
              _Stat(
                label: l10n.dashboardStatQueueBlocked,
                value: '${queue['blocked'] ?? 0}',
              ),
              _Stat(
                label: l10n.dashboardStatQueueDelivered,
                value: '${queue['delivered'] ?? 0}',
              ),
              _Stat(
                label: l10n.dashboardStatRoutesEnabled,
                value: '${routes['enabled'] ?? 0}',
              ),
              _Stat(
                label: l10n.dashboardStatRoutesDisabled,
                value: '${routes['disabled'] ?? 0}',
              ),
            ],
          ),
        ),
        // TODO(openspec/extend-app-dashboard-fields-for-feat012):
        // re-enable the "recommended next action" tile when the contract
        // 1.1 adds result.recommended_next_action.
      ],
    );
  }

  static String _runtimeLabel(AppLocalizations l10n, RuntimeStateKind kind) =>
      switch (kind) {
        RuntimeStateKind.runtimeUnreachable =>
          l10n.dashboardRuntimeLabelUnreachable,
        RuntimeStateKind.contractVersionIncompatible =>
          l10n.dashboardRuntimeLabelContractMismatch,
        RuntimeStateKind.runtimeHealthyEmpty =>
          l10n.dashboardRuntimeLabelHealthyEmpty,
        RuntimeStateKind.runtimeHealthyPopulated =>
          l10n.dashboardRuntimeLabelHealthy,
        RuntimeStateKind.runtimeDegraded => l10n.dashboardRuntimeLabelDegraded,
      };
}

class _OutageState extends StatelessWidget {
  const _OutageState({required this.runtime, required this.onRetry});

  final RuntimeState runtime;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.cloud_off_outlined,
              size: 48,
              color: Theme.of(context).colorScheme.error,
            ),
            const SizedBox(height: 16),
            Text(
              l10n.dashboardOutageTitle,
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            Text(
              runtime.lastError == null
                  ? l10n.dashboardOutageBody
                  : l10n.dashboardOutageBodyLastError(
                      runtime.lastError.toString(),
                    ),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 16),
            FilledButton.icon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh),
              label: Text(l10n.dashboardOutageRetryButton),
            ),
          ],
        ),
      ),
    );
  }
}

class _DashboardError extends StatelessWidget {
  const _DashboardError({required this.error, required this.onRetry});

  final Object error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            l10n.dashboardErrorBody(error.toString()),
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: onRetry,
            icon: const Icon(Icons.refresh),
            label: Text(l10n.dashboardErrorRetryButton),
          ),
        ],
      ),
    );
  }
}

class _Section extends StatelessWidget {
  const _Section({required this.title, required this.child});

  final String title;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            child,
          ],
        ),
      ),
    );
  }
}

class _Stat extends StatelessWidget {
  const _Stat({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: Theme.of(context).textTheme.labelMedium),
        Text(value, style: Theme.of(context).textTheme.headlineSmall),
      ],
    );
  }
}
