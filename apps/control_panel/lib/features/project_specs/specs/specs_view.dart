import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

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
    final featureChanges = ref.watch(featureChangeListProvider(selectedId));
    return Scaffold(
      appBar: AppBar(
        title: const Text('Specs'),
        actions: [
          IconButton(
            tooltip: 'Refresh',
            icon: const Icon(Icons.refresh),
            onPressed: () =>
                ref.invalidate(featureChangeListProvider(selectedId)),
          ),
        ],
      ),
      body: RuntimeStateGate(
        onUnreachable: (s) => OutageStateView(
          state: s,
          surfaceLabel: 'Specs',
          onRetry: () => ref.invalidate(featureChangeListProvider(selectedId)),
        ),
        onIncompatible: (s) =>
            ContractIncompatStateView(state: s, surfaceLabel: 'Specs'),
        child: featureChanges.when(
        data: (fcs) => fcs.isEmpty
            ? const HealthyEmptyStateView(
                message:
                    'No features or changes registered for this project yet.',
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
          surfaceLabel: 'specs',
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
    final detail = ref.watch(featureChangeDetailProvider(featureChangeId));
    return detail.when(
      data: (fc) {
        // Phase 4 wiring: the daemon's feature/change detail does not
        // yet return spec markdown bodies (that's a v1.x extension).
        // For MVP we render a placeholder body that names the resolved
        // spec path; clicking "Open externally" hands off to url_launcher.
        return MarkdownViewer(
          markdownText:
              '# ${fc.displayId}\n\n${fc.humanReadableLabel}\n\n'
              '_Spec body rendering pending FEAT-011 v1.x doc-content method._',
          sourceLabel: 'spec for ${fc.displayId}',
        );
      },
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (err, _) => Center(child: Text('Failed to load spec: $err')),
    );
  }
}

class _SelectAFeature extends StatelessWidget {
  const _SelectAFeature();

  @override
  Widget build(BuildContext context) {
    return const Center(child: Text('Select a feature/change to view its spec.'));
  }
}

class _NoProjectSelected extends StatelessWidget {
  const _NoProjectSelected();

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Padding(
        padding: EdgeInsets.all(32),
        child: Text(
          'No project selected.\n\n'
          'Pick a project from the Projects view to see its specs.',
          textAlign: TextAlign.center,
        ),
      ),
    );
  }
}

// _EmptyState replaced by shared HealthyEmptyStateView (swarm-review CR-6).
