import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/persistence/sort_filter_state.dart';
import '../../../core/providers.dart';
import '../../../ui/widgets/list_controls.dart';
import '../providers.dart';

/// Agent Operations → Events. T072 (Phase 3 US1) + FR-019 + FR-080.
///
/// Renders events in observed-at descending order. The list is
/// virtualized (`ListView.builder` is virtualized by default) and the
/// "Jump to most recent" affordance scrolls back to index 0 — the head
/// of the stream.
///
/// Cursor-pagination + live updates land in Phase 9; for the MVP the
/// view fetches the first page on mount and "Jump to most recent"
/// re-invalidates the provider so the operator can manually pull the
/// freshest events.
class EventsView extends ConsumerStatefulWidget {
  const EventsView({super.key});

  @override
  ConsumerState<EventsView> createState() => _EventsViewState();
}

class _EventsViewState extends ConsumerState<EventsView> {
  static const _viewId = 'agent_ops/events';
  final _scroll = ScrollController();
  String? _filter;
  bool _loaded = false;

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!_loaded) {
      _loaded = true;
      final p = ref.read(sortFilterRepositoryProvider).load(viewId: _viewId);
      final v = p.filters['event_type'];
      _filter = v is String ? v : null;
    }
    final events = ref.watch(eventListProvider);
    return events.when(
      data: (rows) {
        // Event types are an open daemon-owned vocabulary (FEAT-006), so the
        // filter options are the distinct types present in the loaded page.
        final types = rows.map((e) => e.eventType).toSet().toList()..sort();
        final filtered = _filter == null
            ? rows
            : rows.where((e) => e.eventType == _filter).toList(growable: false);
        return Column(
          children: [
            ListControlsBar(
              controls: [
                EnumFilterMenu<String>(
                  tooltip: 'Filter by event type',
                  allLabel: 'All event types',
                  value: _filter,
                  options: types,
                  labelOf: (s) => s,
                  onSelected: _onFilter,
                ),
              ],
            ),
            Expanded(
              child: rows.isEmpty
                  ? const Center(
                      child: Padding(
                        padding: EdgeInsets.all(32),
                        child: Text(
                          'No events yet.\n\nAdopt an agent and watch its events stream in here.',
                          textAlign: TextAlign.center,
                        ),
                      ),
                    )
                  : Stack(
                      children: [
                        if (filtered.isEmpty)
                          const FilterNoMatch(
                              message: 'No events match the current filter.')
                        else
                          ListView.builder(
                            controller: _scroll,
                            itemCount: filtered.length,
                            itemBuilder: (_, i) {
                              final e = filtered[i];
                              return ListTile(
                                dense: true,
                                title: Text(
                                  '${e.eventType} · ${e.agentId}',
                                  style:
                                      const TextStyle(fontFamily: 'monospace'),
                                ),
                                subtitle: Text(e.excerpt, maxLines: 2),
                                trailing: Text(
                                  _timeLabel(e.observedAt),
                                  style: Theme.of(context).textTheme.labelSmall,
                                ),
                              );
                            },
                          ),
                        Positioned(
                          right: 16,
                          bottom: 16,
                          child: FloatingActionButton.small(
                            tooltip: 'Jump to most recent',
                            onPressed: () {
                              ref.invalidate(eventListProvider);
                              if (_scroll.hasClients) {
                                _scroll.jumpTo(0);
                              }
                            },
                            child: const Icon(Icons.vertical_align_top),
                          ),
                        ),
                      ],
                    ),
            ),
          ],
        );
      },
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => Center(child: Text('Could not load events: $e')),
    );
  }

  void _onFilter(String? v) {
    setState(() => _filter = v);
    ref.read(sortFilterRepositoryProvider).save(
          viewId: _viewId,
          value: ListSortFilterState(
            filters: {if (v != null) 'event_type': v},
          ),
        );
  }

  static String _timeLabel(DateTime ts) {
    final delta = DateTime.now().toUtc().difference(ts.toUtc());
    if (delta.inSeconds < 60) return '${delta.inSeconds}s';
    if (delta.inMinutes < 60) return '${delta.inMinutes}m';
    if (delta.inHours < 24) return '${delta.inHours}h';
    return '${delta.inDays}d';
  }
}
