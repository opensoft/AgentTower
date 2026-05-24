import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/providers.dart';
import '../../../domain/models/common_enums.dart';
import '../../../domain/models/queue_row.dart';
import '../providers.dart';

/// Agent Operations → Queue. T073 (Phase 3 US1) + FR-020 + FR-080.
///
/// Renders the 5-state safe-prompt queue. Per-row actions:
///   - blocked:  Approve · Delay · Cancel
///   - queued:   Cancel only
///   - delivered/canceled/failed (terminal): no actions
///
/// Mutations route through `app.queue.approve` / `.delay` / `.cancel`
/// with auto-stamped idempotency_key (Round-3 R-28).
class QueueView extends ConsumerWidget {
  const QueueView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final queue = ref.watch(queueListProvider);
    return queue.when(
      data: (rows) => rows.isEmpty
          ? const Center(
              child: Padding(
                padding: EdgeInsets.all(32),
                child: Text(
                  'Queue is empty.\n\nMessages waiting for routing or operator approval will appear here.',
                  textAlign: TextAlign.center,
                ),
              ),
            )
          : RefreshIndicator(
              onRefresh: () async => ref.invalidate(queueListProvider),
              child: ListView.separated(
                itemCount: rows.length,
                separatorBuilder: (_, __) => const Divider(height: 1),
                itemBuilder: (_, i) => _QueueTile(row: rows[i]),
              ),
            ),
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => Center(child: Text('Could not load queue: $e')),
    );
  }
}

class _QueueTile extends ConsumerWidget {
  const _QueueTile({required this.row});
  final QueueRow row;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return ListTile(
      leading: _StateBadge(state: row.state),
      title: Text(
        '${row.sourceAgentId} → ${row.targetAgentId}',
        style: const TextStyle(fontFamily: 'monospace'),
      ),
      subtitle: Text(
        row.payload,
        maxLines: 2,
        overflow: TextOverflow.ellipsis,
      ),
      trailing: _Actions(row: row),
    );
  }
}

class _StateBadge extends StatelessWidget {
  const _StateBadge({required this.state});
  final QueueRowState state;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final color = switch (state) {
      QueueRowState.queued => scheme.primary,
      QueueRowState.blocked => scheme.error,
      QueueRowState.delivered => scheme.tertiary,
      QueueRowState.canceled => scheme.outline,
      QueueRowState.failed => scheme.error,
    };
    return Chip(
      label: Text(state.wireValue),
      backgroundColor: color.withValues(alpha: 0.15),
      labelStyle: TextStyle(color: color),
    );
  }
}

class _Actions extends ConsumerStatefulWidget {
  const _Actions({required this.row});
  final QueueRow row;

  @override
  ConsumerState<_Actions> createState() => _ActionsState();
}

class _ActionsState extends ConsumerState<_Actions> {
  bool _busy = false;

  @override
  Widget build(BuildContext context) {
    if (widget.row.state.isTerminal) {
      return const SizedBox.shrink();
    }
    return Wrap(
      spacing: 4,
      children: [
        if (widget.row.state == QueueRowState.blocked)
          IconButton(
            tooltip: 'Approve',
            icon: const Icon(Icons.check),
            onPressed: _busy ? null : () => _do('approve'),
          ),
        if (widget.row.state == QueueRowState.blocked)
          IconButton(
            tooltip: 'Delay 60s',
            icon: const Icon(Icons.snooze),
            onPressed: _busy ? null : () => _do('delay'),
          ),
        IconButton(
          tooltip: 'Cancel',
          icon: const Icon(Icons.close),
          onPressed: _busy ? null : () => _do('cancel'),
        ),
      ],
    );
  }

  Future<void> _do(String action) async {
    setState(() => _busy = true);
    final messenger = ScaffoldMessenger.of(context);
    try {
      final client = ref.read(appClientProvider);
      switch (action) {
        case 'approve':
          await client.queueApprove(queueRowId: widget.row.queueRowId);
        case 'delay':
          await client.queueDelay(
            queueRowId: widget.row.queueRowId,
            by: const Duration(seconds: 60),
          );
        case 'cancel':
          await client.queueCancel(queueRowId: widget.row.queueRowId);
      }
      ref.invalidate(queueListProvider);
      messenger.showSnackBar(SnackBar(content: Text('Queue $action ok')));
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('Queue $action failed: $e')));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
}
