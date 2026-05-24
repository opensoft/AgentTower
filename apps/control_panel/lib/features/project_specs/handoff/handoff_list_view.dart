import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../domain/models/common_enums.dart';
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
    final list = ref.watch(handoffListProvider(_query));
    return Scaffold(
      appBar: AppBar(
        title: const Text('Handoffs'),
        actions: [
          PopupMenuButton<AssignmentState?>(
            tooltip: 'Filter by state',
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
              const PopupMenuItem(value: null, child: Text('All')),
              for (final s in AssignmentState.values)
                PopupMenuItem(value: s, child: Text(s.wireValue)),
            ],
          ),
          IconButton(
            tooltip: 'Refresh',
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(handoffListProvider(_query)),
          ),
        ],
      ),
      body: list.when(
        data: (rows) => rows.isEmpty
            ? const Center(child: Text('No handoffs match the current filter.'))
            : ListView.builder(
                itemCount: rows.length,
                itemBuilder: (_, i) {
                  final h = rows[i];
                  return ListTile(
                    leading: const Icon(Icons.assignment_turned_in),
                    title: Text(
                      h.primaryWorkItem.displayId +
                          (h.handoffId == null ? ' (draft)' : ''),
                    ),
                    subtitle: Text(
                      'Master: ${h.targetMasterLabel} · '
                      'State: ${h.assignmentState.wireValue} · '
                      'Created: ${h.createdAt.toLocal()}',
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
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (err, _) => Center(child: Text('Failed to load handoffs: $err')),
      ),
    );
  }
}
