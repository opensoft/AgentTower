import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/l10n/app_localizations.dart';
import '../../../domain/models/feature_change_status.dart';
import '../../../ui/widgets/markdown_viewer.dart';
import '../../../ui/widgets/runtime_state_views.dart';
import '../providers.dart';

/// FR-031 — Specs view (project-first, then feature). T093 (Phase 4 US2).
///
/// The Specs view is a read-only navigation surface in the first
/// release (per spec Assumption: Specs/docs viewing first, in-app
/// editing deferred). Refinement happens via a `spec_refinement` mode
/// handoff to a master (Phase 5).
///
/// Layout: two-pane — left lists the project's specs (one entry per
/// feature/change with a spec markdown body); right renders the
/// selected entry via [MarkdownViewer]. The daemon resolves doc paths
/// server-side per R-28 and returns the markdown body; the app never
/// reads files itself.
class SpecsView extends ConsumerStatefulWidget {
  const SpecsView({super.key});

  @override
  ConsumerState<SpecsView> createState() => _SpecsViewState();
}

class _SpecsViewState extends ConsumerState<SpecsView> {
  String? _selectedFeatureChangeId;

  @override
  Widget build(BuildContext context) {
    final selectedId = ref.watch(selectedProjectIdProvider);
    if (selectedId == null) {
      return const _NoProjectSelected();
    }
    final l10n = AppLocalizations.of(context);
    final featureChanges = ref.watch(featureChangeListProvider(selectedId));
    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.specsViewTitle),
        actions: [
          IconButton(
            tooltip: l10n.specsRefreshTooltip,
            icon: const Icon(Icons.refresh),
            onPressed: () =>
                ref.invalidate(featureChangeListProvider(selectedId)),
          ),
        ],
      ),
      body: RuntimeStateGate(
        onUnreachable: (s) => OutageStateView(
          state: s,
          surfaceLabel: l10n.specsSurfaceLabel,
          onRetry: () => ref.invalidate(featureChangeListProvider(selectedId)),
        ),
        onIncompatible: (s) =>
            ContractIncompatStateView(state: s, surfaceLabel: l10n.specsSurfaceLabel),
        child: featureChanges.when(
        data: (fcs) => fcs.isEmpty
            ? HealthyEmptyStateView(
                message: l10n.specsEmptyMessage,
              )
            : Row(
                children: [
                  SizedBox(
                    width: 320,
                    child: _FeatureList(
                      featureChanges: fcs,
                      selectedId: _selectedFeatureChangeId,
                      onSelect: (id) =>
                          setState(() => _selectedFeatureChangeId = id),
                    ),
                  ),
                  const VerticalDivider(width: 1),
                  Expanded(
                    child: _selectedFeatureChangeId == null
                        ? const _SelectAFeature()
                        : _SpecPane(featureChangeId: _selectedFeatureChangeId!),
                  ),
                ],
              ),
        loading: () => const LoadingStateView(),
        error: (err, _) => ErrorStateView(
          error: err,
          surfaceLabel: l10n.specsSurfaceLabelLower,
          onRetry: () => ref.invalidate(featureChangeListProvider(selectedId)),
        ),
      ),
      ),
    );
  }
}

class _FeatureList extends StatelessWidget {
  const _FeatureList({
    required this.featureChanges,
    required this.selectedId,
    required this.onSelect,
  });

  final List<FeatureChangeStatus> featureChanges;
  final String? selectedId;
  final ValueChanged<String> onSelect;

  @override
  Widget build(BuildContext context) {
    return ListView.builder(
      itemCount: featureChanges.length,
      itemBuilder: (_, i) {
        final fc = featureChanges[i];
        return ListTile(
          selected: fc.featureChangeId == selectedId,
          title: Text(fc.displayId),
          subtitle: Text(fc.humanReadableLabel),
          onTap: () => onSelect(fc.featureChangeId),
        );
      },
    );
  }
}

class _SpecPane extends ConsumerWidget {
  const _SpecPane({required this.featureChangeId});
  final String featureChangeId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final detail = ref.watch(featureChangeDetailProvider(featureChangeId));
    return detail.when(
      data: (fc) {
        // Phase 4 wiring: the daemon's feature/change detail does not
        // yet return spec markdown bodies (that's a v1.x extension).
        // For MVP we render a placeholder body that names the resolved
        // spec path; clicking "Open externally" hands off to url_launcher.
        return MarkdownViewer(
          markdownText: l10n.specsPaneBodyPlaceholder(
            fc.displayId,
            fc.humanReadableLabel,
          ),
          sourceLabel: l10n.specsPaneSourceLabel(fc.displayId),
        );
      },
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (err, _) =>
          Center(child: Text(l10n.specsLoadFailed(err.toString()))),
    );
  }
}

class _SelectAFeature extends StatelessWidget {
  const _SelectAFeature();

  @override
  Widget build(BuildContext context) {
    return Center(child: Text(AppLocalizations.of(context).specsSelectAFeature));
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
          AppLocalizations.of(context).specsNoProjectSelected,
          textAlign: TextAlign.center,
        ),
      ),
    );
  }
}

// _EmptyState replaced by shared HealthyEmptyStateView (swarm-review CR-6).
