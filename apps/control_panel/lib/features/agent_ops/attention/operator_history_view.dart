import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:agenttower_control_panel/core/l10n/app_localizations.dart';
import '../../../domain/models/operator_history_entry.dart';
import '../../../ui/widgets/runtime_state_views.dart';
import 'providers.dart';

/// FR-055 — Operator history view. T138 (Phase 8 US6).
///
/// Renders durable resolved-attention / completed-workflow entries
/// rolled up by `parentAgentId` with `subAgentId` items nested
/// beneath their parent. FR-015 2-level cap applies — deeper
/// descendants flatten to the nearest displayed parent and surface
/// as "+N descendants" (the daemon already collapses; the view
/// renders what it receives).
class OperatorHistoryView extends ConsumerWidget {
  const OperatorHistoryView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final list = ref.watch(operatorHistoryListProvider(null));
    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.operatorHistoryAppBarTitle),
        actions: [
          IconButton(
            tooltip: l10n.operatorHistoryRefreshTooltip,
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(operatorHistoryListProvider(null)),
          ),
        ],
      ),
      body: RuntimeStateGate(
        onUnreachable: (s) => OutageStateView(
          state: s,
          surfaceLabel: l10n.operatorHistorySurfaceLabel,
          onRetry: () => ref.invalidate(operatorHistoryListProvider(null)),
        ),
        onIncompatible: (s) => ContractIncompatStateView(
          state: s,
          surfaceLabel: l10n.operatorHistorySurfaceLabel,
        ),
        child: list.when(
          data: (entries) {
            if (entries.isEmpty) {
              return HealthyEmptyStateView(
                message: l10n.operatorHistoryEmptyState,
                icon: Icons.history,
              );
            }
            final byParent = _groupByParent(entries);
            final parents = byParent.keys.toList()..sort();
            return ListView.builder(
              itemCount: parents.length,
              itemBuilder: (_, i) {
                final parent = parents[i];
                final children = byParent[parent]!;
                return ExpansionTile(
                  leading: const Icon(Icons.psychology),
                  title: Text(l10n.operatorHistoryParentAgentTitle(parent)),
                  subtitle:
                      Text(l10n.operatorHistoryEntryCount(children.length)),
                  children: [
                    for (final e in children) _HistoryEntryTile(entry: e),
                  ],
                );
              },
            );
          },
          loading: () => const LoadingStateView(),
          error: (err, _) => ErrorStateView(
            error: err,
            surfaceLabel: l10n.operatorHistorySurfaceLabelLowercase,
            onRetry: () => ref.invalidate(operatorHistoryListProvider(null)),
          ),
        ),
      ),
    );
  }

  static Map<String, List<OperatorHistoryEntry>> _groupByParent(
    List<OperatorHistoryEntry> entries,
  ) {
    final out = <String, List<OperatorHistoryEntry>>{};
    for (final e in entries) {
      (out[e.parentAgentId] ??= []).add(e);
    }
    for (final list in out.values) {
      list.sort((a, b) => b.occurredAt.compareTo(a.occurredAt));
    }
    return out;
  }
}

class _HistoryEntryTile extends StatelessWidget {
  const _HistoryEntryTile({required this.entry});
  final OperatorHistoryEntry entry;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final occurredAt = entry.occurredAt.toLocal().toString();
    final subAgentId = entry.subAgentId;
    final subtitle = subAgentId == null
        ? l10n.operatorHistoryEntrySubtitle(
            entry.kind.wireValue,
            occurredAt,
          )
        : l10n.operatorHistoryEntrySubtitleWithSubAgent(
            entry.kind.wireValue,
            occurredAt,
            subAgentId,
          );
    return Padding(
      padding: EdgeInsets.only(
        left: subAgentId == null ? 16 : 48,
        right: 16,
      ),
      child: ListTile(
        dense: true,
        leading: Icon(
          subAgentId == null
              ? Icons.adjust
              : Icons.subdirectory_arrow_right,
          size: 16,
        ),
        title: Text(entry.summary),
        subtitle: Text(subtitle),
      ),
    );
  }
}
