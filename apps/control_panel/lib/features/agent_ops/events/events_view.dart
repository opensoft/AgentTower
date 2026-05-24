import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

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
  final _scroll = ScrollController();

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final events = ref.watch(eventListProvider);
    return events.when(
      data: (rows) => rows.isEmpty
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
                ListView.builder(
                  controller: _scroll,
                  itemCount: rows.length,
                  itemBuilder: (_, i) {
                    final e = rows[i];
                    return ListTile(
                      dense: true,
                      title: Text(
                        '${e.eventType} · ${e.agentId}',
                        style: const TextStyle(fontFamily: 'monospace'),
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
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => Center(child: Text('Could not load events: $e')),
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
