import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:agenttower_control_panel/core/l10n/app_localizations.dart';
import '../../../domain/models/attention_item.dart';
import '../../../domain/models/common_enums.dart';
import '../../../domain/severity.dart';
import '../../../ui/widgets/runtime_state_views.dart';
import '../../project_specs/providers.dart' as project_providers;
import 'interaction_stability.dart';
import 'providers.dart';
import 'resolution_navigation.dart';

/// FR-052 — Attention queue. T135 (Phase 8 US6).
///
/// Renders actionable items only; each row shows class (icon),
/// severity (color, per R-15 palette via [SeverityVisuals]), age,
/// and a one-line summary. Default sort is severity-then-age.
///
/// **FR-053 stability**: the view owns an [InteractionStabilityController]
/// that defers reorders / item changes while the operator hovers /
/// clicks / presses keys on the queue. Updates from
/// `attentionListProvider` go through [InteractionStabilityController.acceptIncoming]
/// so the SC-008a invariant ("no position change under the pointer
/// for ≥ 2 s") holds without changing the daemon-side stream.
class AttentionQueueView extends ConsumerStatefulWidget {
  const AttentionQueueView({super.key});

  @override
  ConsumerState<AttentionQueueView> createState() => _AttentionQueueViewState();
}

class _AttentionQueueViewState extends ConsumerState<AttentionQueueView> {
  late final InteractionStabilityController _stability;

  @override
  void initState() {
    super.initState();
    _stability = InteractionStabilityController();
  }

  @override
  void dispose() {
    _stability.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final selectedId =
        ref.watch(project_providers.selectedProjectIdProvider);
    final query = AttentionListQuery(projectId: selectedId);
    final list = ref.watch(attentionListProvider(query));

    // Push provider data into the stability controller. Items are
    // sorted severity-then-age (FR-052 default).
    list.whenData((rows) {
      final sorted = [...rows]..sort((a, b) {
          final s = _severityRank(b.severity) - _severityRank(a.severity);
          if (s != 0) return s;
          return a.ageStartedAt.compareTo(b.ageStartedAt);
        });
      _stability.acceptIncoming(sorted);
    });

    final l10n = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.attentionQueueAppBarTitle),
        actions: [
          IconButton(
            tooltip: l10n.attentionQueueRefreshTooltip,
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(attentionListProvider(query)),
          ),
        ],
      ),
      body: RuntimeStateGate(
        onUnreachable: (s) => OutageStateView(
          state: s,
          surfaceLabel: l10n.attentionQueueSurfaceLabel,
          onRetry: () => ref.invalidate(attentionListProvider(query)),
        ),
        onIncompatible: (s) => ContractIncompatStateView(
          state: s,
          surfaceLabel: l10n.attentionQueueSurfaceLabel,
        ),
        child: list.when(
          data: (_) => _StableListView(
            stability: _stability,
            onTap: _onTap,
          ),
          loading: () => const LoadingStateView(),
          error: (err, _) => ErrorStateView(
            error: err,
            surfaceLabel: l10n.attentionQueueSurfaceLabelLowercase,
            onRetry: () => ref.invalidate(attentionListProvider(query)),
          ),
        ),
      ),
    );
  }

  void _onTap(AttentionItem item) {
    AttentionResolutionDispatcher.open(context, ref, item);
  }

  static int _severityRank(AttentionSeverity severity) => switch (severity.wireValue) {
        'critical' => 4,
        'high' => 3,
        'warning' => 2,
        'info' => 1,
        _ => 0,
      };
}

class _StableListView extends StatelessWidget {
  const _StableListView({required this.stability, required this.onTap});
  final InteractionStabilityController stability;
  final void Function(AttentionItem) onTap;

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: stability,
      builder: (context, _) {
        final items = stability.stableList;
        if (items.isEmpty) {
          return HealthyEmptyStateView(
            message:
                AppLocalizations.of(context).attentionQueueNoActionableItems,
            icon: Icons.check_circle_outline,
          );
        }
        return ListView.builder(
          itemCount: items.length,
          itemBuilder: (_, i) => _AttentionRow(
            item: items[i],
            stability: stability,
            onTap: onTap,
          ),
        );
      },
    );
  }
}

class _AttentionRow extends StatelessWidget {
  const _AttentionRow({
    required this.item,
    required this.stability,
    required this.onTap,
  });

  final AttentionItem item;
  final InteractionStabilityController stability;
  final void Function(AttentionItem) onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final l10n = AppLocalizations.of(context);
    final sev = SeverityVisuals.forAttention(item.severity, theme.brightness);
    final age = DateTime.now().difference(item.ageStartedAt);
    return MouseRegion(
      onEnter: (_) => stability.noteInteraction(),
      onHover: (_) => stability.noteInteraction(),
      child: Semantics(
        label: l10n.attentionQueueRowSemanticLabel(
          sev.semanticDescription,
          item.oneLineSummary,
        ),
        child: ListTile(
          leading: CircleAvatar(
            backgroundColor: sev.color,
            child: Icon(_classIcon(item.attentionClass), color: sev.onColor),
          ),
          title: Text(item.oneLineSummary),
          subtitle: Text(
            l10n.attentionQueueRowSubtitle(
              sev.label,
              item.attentionClass.wireValue,
              _humanAge(l10n, age),
            ),
          ),
          onTap: () {
            stability.noteInteraction();
            onTap(item);
          },
        ),
      ),
    );
  }

  static IconData _classIcon(AttentionClass attentionClass) => switch (attentionClass.wireValue) {
        'blocked_queue_row' => Icons.block,
        'route_skip' => Icons.skip_next,
        'degraded_subsystem' => Icons.health_and_safety,
        'drift_confirmed' => Icons.flag,
        'validation_failed' => Icons.error_outline,
        _ => Icons.notifications_active,
      };

  static String _humanAge(AppLocalizations l10n, Duration d) {
    if (d.inDays > 0) return l10n.attentionItemAgeDays(d.inDays);
    if (d.inHours > 0) return l10n.attentionItemAgeHours(d.inHours);
    if (d.inMinutes > 0) return l10n.attentionItemAgeMinutes(d.inMinutes);
    return l10n.attentionItemAgeJustNow;
  }
}
