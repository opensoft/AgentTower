import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/daemon/errors.dart';
import '../../../core/l10n/app_localizations.dart';
import '../../../core/persistence/sort_filter_state.dart';
import '../../../core/providers.dart';
import '../../../domain/models/common_enums.dart';
import '../../../domain/models/queue_row.dart';
import '../../../ui/widgets/list_controls.dart';
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
///
/// FR-078 (T180): persisted queue-state filter, global scope.
class QueueView extends ConsumerStatefulWidget {
  const QueueView({super.key});

  @override
  ConsumerState<QueueView> createState() => _QueueViewState();
}

class _QueueViewState extends ConsumerState<QueueView> {
  static const _viewId = 'agent_ops/queue';
  QueueRowState? _filter;
  bool _loaded = false;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    if (!_loaded) {
      _loaded = true;
      final p = ref.read(sortFilterRepositoryProvider).load(viewId: _viewId);
      _filter = filterValueFromWire(
          p.filters['state'], QueueRowState.values, (s) => s.wireValue);
    }
    final queue = ref.watch(queueListProvider);
    return queue.when(
      data: (rows) {
        final filtered = _filter == null
            ? rows
            : rows.where((r) => r.state == _filter).toList(growable: false);
        return Column(
          children: [
            ListControlsBar(
              controls: [
                EnumFilterMenu<QueueRowState>(
                  tooltip: l10n.queueFilterStateTooltip,
                  allLabel: l10n.queueFilterAllStates,
                  value: _filter,
                  options: QueueRowState.values,
                  labelOf: (s) => s.wireValue,
                  onSelected: _onFilter,
                ),
              ],
            ),
            Expanded(
              child: rows.isEmpty
                  ? Center(
                      child: Padding(
                        padding: const EdgeInsets.all(32),
                        child: Text(
                          l10n.queueEmptyMessage,
                          textAlign: TextAlign.center,
                        ),
                      ),
                    )
                  : RefreshIndicator(
                      onRefresh: () async => ref.invalidate(queueListProvider),
                      child: filtered.isEmpty
                          ? FilterNoMatch(
                              message: l10n.queueFilterNoMatch)
                          : ListView.separated(
                              itemCount: filtered.length,
                              separatorBuilder: (_, __) =>
                                  const Divider(height: 1),
                              itemBuilder: (_, i) =>
                                  _QueueTile(row: filtered[i]),
                            ),
                    ),
            ),
          ],
        );
      },
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) =>
          Center(child: Text(l10n.queueLoadError(e.toString()))),
    );
  }

  void _onFilter(QueueRowState? v) {
    setState(() => _filter = v);
    ref.read(sortFilterRepositoryProvider).save(
          viewId: _viewId,
          value: ListSortFilterState(
            filters: {if (v != null) 'state': v.wireValue},
          ),
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
        _payloadPreview(row.payload),
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
    final l10n = AppLocalizations.of(context);
    if (widget.row.state.isTerminal) {
      return const SizedBox.shrink();
    }
    // Per FEAT-011 §app.queue.* state transitions (Round-5):
    //   - approve: blocked → queued                  (blocked only)
    //   - delay:   queued → blocked (operator_delayed) (queued only)
    //   - cancel:  queued|blocked → canceled        (both non-terminal)
    // The previous UI offered Delay only on blocked rows, which inverted
    // the lifecycle — corrected here (review fix H8).
    return Wrap(
      spacing: 4,
      children: [
        if (widget.row.state == QueueRowState.blocked)
          IconButton(
            tooltip: l10n.queueApprove,
            icon: const Icon(Icons.check),
            onPressed: _busy ? null : () => _do('approve'),
          ),
        if (widget.row.state == QueueRowState.queued)
          IconButton(
            tooltip: l10n.queueDelay,
            icon: const Icon(Icons.snooze),
            onPressed: _busy ? null : () => _do('delay'),
          ),
        IconButton(
          tooltip: l10n.queueCancel,
          icon: const Icon(Icons.close),
          onPressed: _busy ? null : () => _do('cancel'),
        ),
      ],
    );
  }

  Future<void> _do(String action) async {
    setState(() => _busy = true);
    // Capture messenger BEFORE awaits so the SnackBar dispatch is safe even
    // if the parent rebuilds and detaches our context (review fix H5).
    final messenger = ScaffoldMessenger.of(context);
    final l10n = AppLocalizations.of(context);
    try {
      final client = ref.read(appClientProvider);
      switch (action) {
        case 'approve':
          await client.queueApprove(messageId: widget.row.messageId);
        case 'delay':
          await client.queueDelay(
            messageId: widget.row.messageId,
            by: const Duration(seconds: 60),
          );
        case 'cancel':
          await client.queueCancel(messageId: widget.row.messageId);
      }
      ref.invalidate(queueListProvider);
      if (!mounted) return;
      messenger.showSnackBar(
          SnackBar(content: Text(l10n.queueActionOk(action))));
    } catch (e) {
      if (!mounted) return;
      messenger.showSnackBar(
        SnackBar(content: Text(l10n.queueActionFailed(action, _errorText(e)))),
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
}

String _errorText(Object e) =>
    e is AppContractError ? e.message : e.toString();

/// Renders the structured `payload` map as a short preview. The convention
/// is `{"text": "..."}` (see `DirectSendDialog._send`); other shapes fall
/// back to their JSON string representation so the operator can still see
/// what was queued.
String _payloadPreview(Map<String, dynamic> payload) {
  final text = payload['text'];
  if (text is String && text.isNotEmpty) return text;
  return payload.toString();
}
