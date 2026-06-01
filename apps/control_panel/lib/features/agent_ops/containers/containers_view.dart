import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/persistence/sort_filter_state.dart';
import '../../../core/providers.dart';
import '../../../domain/models/common_enums.dart';
import '../../../ui/widgets/list_controls.dart';
import '../providers.dart';

/// Agent Operations → Containers. T066 (Phase 3 US1) + FR-013.
/// Shows label, discovered status, project path per container.
/// FR-078 (T180): persisted state filter, global scope.
class ContainersView extends ConsumerStatefulWidget {
  const ContainersView({super.key});

  @override
  ConsumerState<ContainersView> createState() => _ContainersViewState();
}

class _ContainersViewState extends ConsumerState<ContainersView> {
  static const _viewId = 'agent_ops/containers';
  ContainerState? _filter;
  bool _loaded = false;

  @override
  Widget build(BuildContext context) {
    if (!_loaded) {
      _loaded = true;
      final p = ref.read(sortFilterRepositoryProvider).load(viewId: _viewId);
      _filter = filterValueFromWire(
          p.filters['state'], ContainerState.values, (s) => s.wireValue);
    }
    final containers = ref.watch(containerListProvider);
    return containers.when(
      data: (rows) {
        final filtered = _filter == null
            ? rows
            : rows.where((c) => c.state == _filter).toList(growable: false);
        return Column(
          children: [
            ListControlsBar(
              controls: [
                EnumFilterMenu<ContainerState>(
                  tooltip: 'Filter by state',
                  allLabel: 'All states',
                  value: _filter,
                  options: ContainerState.values,
                  labelOf: (s) => s.wireValue,
                  onSelected: _onFilter,
                ),
              ],
            ),
            Expanded(
              child: rows.isEmpty
                  ? const _Empty()
                  : RefreshIndicator(
                      onRefresh: () async =>
                          ref.invalidate(containerListProvider),
                      child: filtered.isEmpty
                          ? const FilterNoMatch(
                              message: 'No containers match the current filter.')
                          : ListView.builder(
                              itemCount: filtered.length,
                              itemBuilder: (_, i) {
                                final c = filtered[i];
                                return ListTile(
                                  leading: Icon(_iconFor(c.state.wireValue)),
                                  title: Text(c.name),
                                  subtitle: Text(
                                      '${c.projectPath} · ${c.state.wireValue}'),
                                  trailing: Text(
                                    c.containerId,
                                    style:
                                        Theme.of(context).textTheme.labelSmall,
                                  ),
                                );
                              },
                            ),
                    ),
            ),
          ],
        );
      },
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => _ErrorState(
        error: e,
        onRetry: () => ref.invalidate(containerListProvider),
      ),
    );
  }

  void _onFilter(ContainerState? v) {
    setState(() => _filter = v);
    ref.read(sortFilterRepositoryProvider).save(
          viewId: _viewId,
          value: ListSortFilterState(
            filters: {if (v != null) 'state': v.wireValue},
          ),
        );
  }

  static IconData _iconFor(String state) {
    return switch (state) {
      'running' => Icons.circle,
      'exited' => Icons.stop_circle_outlined,
      'paused' => Icons.pause_circle_outlined,
      'restarting' => Icons.refresh,
      _ => Icons.help_outline,
    };
  }
}

class _Empty extends StatelessWidget {
  const _Empty();

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Padding(
        padding: EdgeInsets.all(32),
        child: Text(
          'No containers discovered yet.\n\nLaunch a bench container with agenttowerd running '
          'and the Panes view will surface its tmux panes for adoption.',
          textAlign: TextAlign.center,
        ),
      ),
    );
  }
}

class _ErrorState extends StatelessWidget {
  const _ErrorState({required this.error, required this.onRetry});
  final Object error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text('Could not load containers: $error', textAlign: TextAlign.center),
          const SizedBox(height: 12),
          OutlinedButton(onPressed: onRetry, child: const Text('Retry')),
        ],
      ),
    );
  }
}
