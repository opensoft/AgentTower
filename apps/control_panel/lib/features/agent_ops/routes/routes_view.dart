import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/daemon/errors.dart';
import '../../../core/providers.dart';
import '../../../domain/models/route.dart' as model;
import '../providers.dart';
import 'add_route_flow.dart';

/// Agent Operations → Routes. T074 (Phase 3 US1) + FR-021 + FR-059.
///
/// Each row shows source scope, target rule, master rule, enabled
/// state, and (when applicable) `recentSkipExplanation` — the
/// explainability surface per FR-059. Enable/disable + remove
/// available inline. Add via [AddRouteFlow].
class RoutesView extends ConsumerWidget {
  const RoutesView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final routes = ref.watch(routeListProvider);
    return Scaffold(
      body: routes.when(
        data: (rows) => rows.isEmpty
            ? const Center(
                child: Padding(
                  padding: EdgeInsets.all(32),
                  child: Text(
                    'No routes defined.\n\nTap + to add a route that wires events from a source agent to a target.',
                    textAlign: TextAlign.center,
                  ),
                ),
              )
            : RefreshIndicator(
                onRefresh: () async => ref.invalidate(routeListProvider),
                child: ListView.separated(
                  itemCount: rows.length,
                  separatorBuilder: (_, __) => const Divider(height: 1),
                  itemBuilder: (_, i) => _RouteTile(route: rows[i]),
                ),
              ),
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('Could not load routes: $e')),
      ),
      floatingActionButton: FloatingActionButton.extended(
        icon: const Icon(Icons.add),
        label: const Text('Add route'),
        onPressed: () => AddRouteFlow.show(context),
      ),
    );
  }
}

class _RouteTile extends ConsumerStatefulWidget {
  const _RouteTile({required this.route});
  final model.Route route;

  @override
  ConsumerState<_RouteTile> createState() => _RouteTileState();
}

class _RouteTileState extends ConsumerState<_RouteTile> {
  bool _busy = false;

  @override
  Widget build(BuildContext context) {
    final r = widget.route;
    return ListTile(
      leading: Switch(
        value: r.enabled,
        onChanged: _busy ? null : (v) => _toggle(v),
      ),
      title: Text(
        '${r.sourceScope}  →  ${r.target}',
        style: const TextStyle(fontFamily: 'monospace'),
      ),
      subtitle: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('template: ${r.template}'),
          if (r.masterRule != null) Text('master: ${r.masterRule}'),
          if (r.recentSkipExplanation != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                '↳ recent skip: ${r.recentSkipExplanation}',
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ),
          if (r.recentMatchSummary != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                '↳ recent match: ${r.recentMatchSummary}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
        ],
      ),
      trailing: IconButton(
        tooltip: 'Remove',
        icon: const Icon(Icons.delete_outline),
        onPressed: _busy ? null : _remove,
      ),
    );
  }

  Future<void> _toggle(bool enabled) async {
    setState(() => _busy = true);
    final messenger = ScaffoldMessenger.of(context);
    try {
      await ref.read(appClientProvider).routeUpdate(
            routeId: widget.route.routeId,
            enabled: enabled,
          );
      ref.invalidate(routeListProvider);
    } catch (e) {
      if (!mounted) return;
      messenger
          .showSnackBar(SnackBar(content: Text('Toggle failed: ${_errorText(e)}')));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _remove() async {
    setState(() => _busy = true);
    final messenger = ScaffoldMessenger.of(context);
    try {
      await ref
          .read(appClientProvider)
          .routeRemove(routeId: widget.route.routeId);
      ref.invalidate(routeListProvider);
      if (!mounted) return;
      messenger.showSnackBar(const SnackBar(content: Text('Route removed')));
    } catch (e) {
      if (!mounted) return;
      messenger.showSnackBar(
        SnackBar(content: Text('Remove failed: ${_errorText(e)}')),
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
}

String _errorText(Object e) =>
    e is AppContractError ? e.message : e.toString();
