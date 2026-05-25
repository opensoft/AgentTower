import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/l10n/app_localizations.dart';
import '../../../ui/widgets/markdown_viewer.dart';
import '../../../ui/widgets/runtime_state_views.dart';
import '../providers.dart';

/// FR-032 — Changes view (OpenSpec-side proposed/active changes). T094
/// (Phase 4 US2).
///
/// Same two-pane layout as Specs but scoped to OpenSpec changes
/// (deltas-only proposals) rather than feature specs. The daemon-side
/// shape distinguishes the two via the work-item kind (`change`
/// per [WorkItemKind.change]). Read-only at MVP; refinement is a
/// `spec_refinement` mode handoff (Phase 5).
class ChangesView extends ConsumerStatefulWidget {
  const ChangesView({super.key});

  @override
  ConsumerState<ChangesView> createState() => _ChangesViewState();
}

class _ChangesViewState extends ConsumerState<ChangesView> {
  String? _selectedChangeId;

  @override
  Widget build(BuildContext context) {
    final selectedId = ref.watch(selectedProjectIdProvider);
    if (selectedId == null) return const _NoProjectSelected();
    final l10n = AppLocalizations.of(context);
    final list = ref.watch(featureChangeListProvider(selectedId));
    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.changesViewTitle),
        actions: [
          IconButton(
            tooltip: l10n.changesRefreshTooltip,
            icon: const Icon(Icons.refresh),
            onPressed: () =>
                ref.invalidate(featureChangeListProvider(selectedId)),
          ),
        ],
      ),
      body: RuntimeStateGate(
        onUnreachable: (s) => OutageStateView(
          state: s,
          surfaceLabel: l10n.changesSurfaceLabel,
          onRetry: () => ref.invalidate(featureChangeListProvider(selectedId)),
        ),
        onIncompatible: (s) =>
            ContractIncompatStateView(state: s, surfaceLabel: l10n.changesSurfaceLabel),
        child: list.when(
        data: (entries) {
          // Filter to OpenSpec changes — the daemon returns a mixed
          // feature/change list; the `displayId` convention is
          // `FEAT-N` for features and `CHG-N` (or similar) for
          // changes. Until FEAT-011 exposes a `kind` field, we
          // pattern-match on `displayId` prefix.
          final changes = entries
              .where((e) => !e.displayId.startsWith('FEAT-'))
              .toList(growable: false);
          if (changes.isEmpty) {
            return HealthyEmptyStateView(
              message: l10n.changesEmptyMessage,
            );
          }
          return Row(
            children: [
              SizedBox(
                width: 320,
                child: ListView.builder(
                  itemCount: changes.length,
                  itemBuilder: (_, i) {
                    final c = changes[i];
                    return ListTile(
                      selected: c.featureChangeId == _selectedChangeId,
                      title: Text(c.displayId),
                      subtitle: Text(c.humanReadableLabel),
                      onTap: () => setState(
                        () => _selectedChangeId = c.featureChangeId,
                      ),
                    );
                  },
                ),
              ),
              const VerticalDivider(width: 1),
              Expanded(
                child: _selectedChangeId == null
                    ? Center(child: Text(l10n.changesSelectAChange))
                    : _ChangePane(changeId: _selectedChangeId!),
              ),
            ],
          );
        },
        loading: () => const LoadingStateView(),
        error: (err, _) => ErrorStateView(
          error: err,
          surfaceLabel: l10n.changesSurfaceLabelLower,
          onRetry: () => ref.invalidate(featureChangeListProvider(selectedId)),
        ),
      ),
      ),
    );
  }
}

class _ChangePane extends ConsumerWidget {
  const _ChangePane({required this.changeId});
  final String changeId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final detail = ref.watch(featureChangeDetailProvider(changeId));
    return detail.when(
      data: (c) => MarkdownViewer(
        markdownText: l10n.changesPaneBodyPlaceholder(
          c.displayId,
          c.humanReadableLabel,
        ),
        sourceLabel: l10n.changesPaneSourceLabel(c.displayId),
      ),
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (err, _) =>
          Center(child: Text(l10n.changesLoadFailed(err.toString()))),
    );
  }
}

class _NoProjectSelected extends StatelessWidget {
  const _NoProjectSelected();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Text(
          AppLocalizations.of(context).changesNoProjectSelected,
          textAlign: TextAlign.center,
        ),
      ),
    );
  }
}

// _EmptyState replaced by HealthyEmptyStateView (swarm-review CR-6).
