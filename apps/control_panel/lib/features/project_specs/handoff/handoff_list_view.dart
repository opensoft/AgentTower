import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/l10n/app_localizations.dart';
import '../../../domain/models/common_enums.dart';
import '../../../ui/widgets/runtime_state_views.dart';
import 'handoff_detail_view.dart';
import 'providers.dart';

/// FR-045 — Handoff list. T110 (Phase 5 US3).
///
/// Queryable by project / master / feature-change / assignment state +
/// optional date range on `created_at`. The list reuses the
/// pagination conventions of every other FEAT-011-backed list (cursor
/// `cursor_next`, 50-row default page size).
class HandoffListView extends ConsumerStatefulWidget {
  const HandoffListView({
    super.key,
    this.initialQuery = const HandoffListQuery(),
  });

  final HandoffListQuery initialQuery;

  @override
  ConsumerState<HandoffListView> createState() => _HandoffListViewState();
}

class _HandoffListViewState extends ConsumerState<HandoffListView> {
  late HandoffListQuery _query;

  @override
  void initState() {
    super.initState();
    _query = widget.initialQuery;
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final list = ref.watch(handoffListProvider(_query));
    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.handoffListTitle),
        actions: [
          PopupMenuButton<AssignmentState?>(
            tooltip: l10n.handoffListFilterTooltip,
            icon: const Icon(Icons.filter_list),
            onSelected: (v) {
              setState(() {
                _query = HandoffListQuery(
                  projectId: _query.projectId,
                  targetMasterAgentId: _query.targetMasterAgentId,
                  featureChangeId: _query.featureChangeId,
                  assignmentState: v?.wireValue,
                );
              });
            },
            itemBuilder: (_) => [
              PopupMenuItem(value: null, child: Text(l10n.handoffListFilterAll)),
              for (final s in AssignmentState.values)
                PopupMenuItem(value: s, child: Text(s.wireValue)),
            ],
          ),
          IconButton(
            tooltip: l10n.handoffListRefreshTooltip,
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(handoffListProvider(_query)),
          ),
        ],
      ),
      body: RuntimeStateGate(
        onUnreachable: (s) => OutageStateView(
          state: s,
          surfaceLabel: l10n.handoffListSurfaceLabel,
          onRetry: () => ref.invalidate(handoffListProvider(_query)),
        ),
        onIncompatible: (s) =>
            ContractIncompatStateView(state: s, surfaceLabel: l10n.handoffListSurfaceLabel),
        child: list.when(
        data: (rows) => rows.isEmpty
            ? HealthyEmptyStateView(
                message: l10n.handoffListEmptyMessage,
              )
            : ListView.builder(
                itemCount: rows.length,
                itemBuilder: (_, i) {
                  final h = rows[i];
                  return ListTile(
                    leading: const Icon(Icons.assignment_turned_in),
                    title: Text(
                      h.primaryWorkItem.displayId +
                          (h.handoffId == null
                              ? l10n.handoffListItemTitleDraftSuffix
                              : ''),
                    ),
                    subtitle: Text(
                      l10n.handoffListItemSubtitle(
                        h.targetMasterLabel,
                        h.assignmentState.wireValue,
                        h.createdAt.toLocal().toString(),
                      ),
                    ),
                    trailing: Text(
                      h.handoffId ?? h.draftId ?? '?',
                      style: Theme.of(context).textTheme.labelSmall,
                    ),
                    onTap: h.handoffId == null
                        ? null
                        : () => Navigator.of(context).push(
                              MaterialPageRoute<void>(
                                builder: (_) => HandoffDetailView(
                                  handoffId: h.handoffId!,
                                ),
                              ),
                            ),
                  );
                },
              ),
        loading: () => const LoadingStateView(),
        error: (err, _) => ErrorStateView(
          error: err,
          surfaceLabel: l10n.handoffListSurfaceLabelLower,
          onRetry: () => ref.invalidate(handoffListProvider(_query)),
        ),
      ),
      ),
    );
  }
}
