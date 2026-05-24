import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/daemon/errors.dart';
import '../../../core/providers.dart';
import '../../../domain/models/common_enums.dart';
import '../../../domain/models/pane.dart';
import '../../../routing/route_paths.dart';
import '../providers.dart';
import 'adopt_flow.dart';

/// Agent Operations → Panes. T067 (Phase 3 US1) + FR-014.
///
/// Renders the 4-state vocabulary (discovered-and-unmanaged,
/// discovered-and-registered, inactive/stale, discovery-degraded) and
/// per-state next-action affordance:
///   - discovered-and-unmanaged   → "Adopt" (opens [AdoptFlow])
///   - discovered-and-registered  → "Open agent" (jumps to Agents view)
///   - inactive/stale             → "Re-probe" (kicks `app.scan.panes`)
///   - discovery-degraded         → "Re-probe" + inline reason
class PanesView extends ConsumerWidget {
  const PanesView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final panes = ref.watch(paneListProvider);
    return panes.when(
      data: (rows) => rows.isEmpty
          ? const Center(
              child: Padding(
                padding: EdgeInsets.all(32),
                child: Text(
                  'No tmux panes discovered yet.\n\nStart an agent in a tmux pane inside any '
                  'discovered container — it will appear here as '
                  '"discovered-and-unmanaged".',
                  textAlign: TextAlign.center,
                ),
              ),
            )
          : RefreshIndicator(
              onRefresh: () async => ref.invalidate(paneListProvider),
              child: ListView.separated(
                itemCount: rows.length,
                separatorBuilder: (_, __) => const Divider(height: 1),
                itemBuilder: (_, i) => _PaneTile(pane: rows[i]),
              ),
            ),
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('Could not load panes: $e', textAlign: TextAlign.center),
            const SizedBox(height: 12),
            OutlinedButton(
              onPressed: () => ref.invalidate(paneListProvider),
              child: const Text('Retry'),
            ),
          ],
        ),
      ),
    );
  }
}

class _PaneTile extends ConsumerWidget {
  const _PaneTile({required this.pane});
  final Pane pane;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return ListTile(
      title: Text(
        '${pane.tmuxSessionName}:${pane.tmuxWindowIndex}.${pane.tmuxPaneIndex}',
        style: const TextStyle(fontFamily: 'monospace'),
      ),
      subtitle: Text(
        '${pane.containerId} · ${pane.state.wireValue}'
        '${pane.discoveredClass != null ? ' · ${pane.discoveredClass!.wireValue}' : ''}',
      ),
      trailing: _NextAction(pane: pane),
    );
  }
}

class _NextAction extends ConsumerWidget {
  const _NextAction({required this.pane});
  final Pane pane;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    switch (pane.state) {
      case PaneState.discoveredAndUnmanaged:
        return TextButton.icon(
          icon: const Icon(Icons.add_circle_outline),
          label: const Text('Adopt'),
          onPressed: () => AdoptFlow.show(context, pane: pane),
        );
      case PaneState.discoveredAndRegistered:
        return TextButton.icon(
          icon: const Icon(Icons.open_in_new),
          label: const Text('Open agent'),
          onPressed: pane.registeredAgentId == null
              ? null
              : () => Navigator.of(context).pushReplacementNamed(
                    const RoutePath(
                      workspace: Workspace.agentOps,
                      subViewId: 'agents',
                    ).toRouteString(),
                  ),
        );
      case PaneState.inactiveOrStale:
      case PaneState.discoveryDegraded:
        return TextButton.icon(
          icon: const Icon(Icons.refresh),
          label: const Text('Re-probe'),
          onPressed: () => _reprobe(context, ref),
        );
    }
  }

  Future<void> _reprobe(BuildContext context, WidgetRef ref) async {
    // Capture cross-await dependencies BEFORE awaiting — `_NextAction` is a
    // ConsumerWidget (stateless), so there is no `mounted` to gate post-await
    // SnackBar dispatch. Per `app-methods.md` §app.scan.panes the call accepts
    // ONLY {wait}; the v1.0 contract has no container scoping.
    final messenger = ScaffoldMessenger.of(context);
    try {
      await ref.read(appClientProvider).scanPanes();
      ref.invalidate(paneListProvider);
      messenger.showSnackBar(const SnackBar(content: Text('Re-probe queued')));
    } catch (e) {
      messenger.showSnackBar(
        SnackBar(content: Text('Re-probe failed: ${_errorText(e)}')),
      );
    }
  }
}

/// Renders a closed-set [AppContractError] using its code-driven message
/// rather than `e.toString()` (which embeds the code + prose verbatim and
/// is an injection vector — review fix M1). Falls through to `toString`
/// for non-contract errors.
String _errorText(Object e) =>
    e is AppContractError ? e.message : e.toString();
