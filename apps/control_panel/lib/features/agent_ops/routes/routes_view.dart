import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/daemon/errors.dart';
import '../../../core/l10n/app_localizations.dart';
import '../../../core/persistence/sort_filter_state.dart';
import '../../../core/providers.dart';
import '../../../domain/models/route.dart' as model;
import '../../../ui/widgets/list_controls.dart';
import '../providers.dart';
import 'add_route_flow.dart';

/// Agent Operations → Routes. T074 (Phase 3 US1) + FR-021 + FR-059.
///
/// Each row shows source scope, target rule, master rule, enabled
/// state, and (when applicable) `recentSkipExplanation` — the
/// explainability surface per FR-059. Enable/disable + remove
/// available inline. Add via [AddRouteFlow].
///
/// FR-078 (T180): persisted enabled/disabled filter, global scope.
class RoutesView extends ConsumerStatefulWidget {
  const RoutesView({super.key});

  @override
  ConsumerState<RoutesView> createState() => _RoutesViewState();
}

class _RoutesViewState extends ConsumerState<RoutesView> {
  static const _viewId = 'agent_ops/routes';
  bool? _enabledFilter;
  bool _loaded = false;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    if (!_loaded) {
      _loaded = true;
      final p = ref.read(sortFilterRepositoryProvider).load(viewId: _viewId);
      _enabledFilter = filterValueFromWire(
          p.filters['enabled'], const [true, false], (b) => b.toString());
    }
    final routes = ref.watch(routeListProvider);
    return Scaffold(
      body: routes.when(
        data: (rows) {
          final filtered = _enabledFilter == null
              ? rows
              : rows
                  .where((r) => r.enabled == _enabledFilter)
                  .toList(growable: false);
          return Column(
            children: [
              ListControlsBar(
                controls: [
                  EnumFilterMenu<bool>(
                    tooltip: l10n.routesFilterEnabledTooltip,
                    allLabel: l10n.routesFilterAll,
                    value: _enabledFilter,
                    options: const [true, false],
                    labelOf: (b) =>
                        b ? l10n.routesFilterEnabled : l10n.routesFilterDisabled,
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
                            l10n.routesEmptyMessage,
                            textAlign: TextAlign.center,
                          ),
                        ),
                      )
                    : RefreshIndicator(
                        onRefresh: () async =>
                            ref.invalidate(routeListProvider),
                        child: filtered.isEmpty
                            ? FilterNoMatch(
                                message: l10n.routesFilterNoMatch)
                            : ListView.separated(
                                itemCount: filtered.length,
                                separatorBuilder: (_, __) =>
                                    const Divider(height: 1),
                                itemBuilder: (_, i) =>
                                    _RouteTile(route: filtered[i]),
                              ),
                      ),
              ),
            ],
          );
        },
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) =>
            Center(child: Text(l10n.routesLoadError(e.toString()))),
      ),
      floatingActionButton: FloatingActionButton.extended(
        icon: const Icon(Icons.add),
        label: Text(l10n.routesAddRoute),
        onPressed: () => AddRouteFlow.show(context),
      ),
    );
  }

  void _onFilter(bool? v) {
    setState(() => _enabledFilter = v);
    ref.read(sortFilterRepositoryProvider).save(
          viewId: _viewId,
          value: ListSortFilterState(
            filters: {if (v != null) 'enabled': v},
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
    final l10n = AppLocalizations.of(context);
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
          Text(l10n.routesTemplate(r.template)),
          if (r.masterRule != null) Text(l10n.routesMaster(r.masterRule!)),
          if (r.recentSkipExplanation != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                l10n.routesRecentSkip(r.recentSkipExplanation!),
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ),
          if (r.recentMatchSummary != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                l10n.routesRecentMatch(r.recentMatchSummary!),
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
        ],
      ),
      trailing: IconButton(
        tooltip: l10n.routesRemove,
        icon: const Icon(Icons.delete_outline),
        onPressed: _busy ? null : _remove,
      ),
    );
  }

  Future<void> _toggle(bool enabled) async {
    setState(() => _busy = true);
    final messenger = ScaffoldMessenger.of(context);
    final l10n = AppLocalizations.of(context);
    try {
      await ref.read(appClientProvider).routeUpdate(
            routeId: widget.route.routeId,
            enabled: enabled,
          );
      ref.invalidate(routeListProvider);
    } catch (e) {
      if (!mounted) return;
      messenger.showSnackBar(
          SnackBar(content: Text(l10n.routesToggleFailed(_errorText(e)))));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _remove() async {
    setState(() => _busy = true);
    final messenger = ScaffoldMessenger.of(context);
    final l10n = AppLocalizations.of(context);
    try {
      await ref
          .read(appClientProvider)
          .routeRemove(routeId: widget.route.routeId);
      ref.invalidate(routeListProvider);
      if (!mounted) return;
      messenger.showSnackBar(SnackBar(content: Text(l10n.routesRemoved)));
    } catch (e) {
      if (!mounted) return;
      messenger.showSnackBar(
        SnackBar(content: Text(l10n.routesRemoveFailed(_errorText(e)))),
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
}

String _errorText(Object e) =>
    e is AppContractError ? e.message : e.toString();
