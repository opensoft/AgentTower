import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../domain/helper_policy/helper_policy.dart';
import '../../../domain/models/common_enums.dart';
import '../../../domain/models/feature_change_status.dart';
import '../../../domain/models/handoff_supporting.dart';
import '../../../domain/models/master_summary.dart';
import '../../../domain/models/project.dart';
import '../../../domain/models/resolved_work_item.dart';
import '../providers.dart' as project_providers;
import 'auto_fill_context.dart';
import 'feature_range_resolver.dart';
import 'helper_policy_resolver.dart';
import 'preview_view.dart';

/// FR-036 — multi-step handoff flow. T102 (Phase 5 US3).
///
/// **Step order (FR-036, IMMUTABLE)**:
///   1. Master selection (master qualified per FR-071)
///   2. Project selection
///   3. Work-item selection (single id or `FEAT-N..FEAT-M` range)
///   4. Mode selection
///   5. Optional inputs (FR-037: priority, deadline, helper-policy
///      override, operator notes)
///   6. Preview → Submit
///
/// The flow lives in-memory only — pre-submission drafts are NOT
/// persisted to `ux-state.json` per FR-069 / data-model §2.1.
class HandoffFlow extends ConsumerStatefulWidget {
  const HandoffFlow({
    super.key,
    required this.master,
    required this.project,
    this.initialPrimaryWorkItem,
    this.initialMode,
    this.initialOperatorNotes,
  });

  final MasterSummary master;
  final Project project;
  final FeatureChangeStatus? initialPrimaryWorkItem;

  /// Swarm-review CR-9 / H-C1: lets the FR-035 drift-repair launcher
  /// pre-seed the mode (`HandoffMode.driftRepair`) so the operator
  /// does not have to pick it manually in step 4. Defaults to
  /// `engineeringExecution` when null.
  final HandoffMode? initialMode;

  /// Lets a launcher pre-seed operator notes (e.g. drift-repair
  /// launcher pastes the drift signal id + linked features for
  /// context, per FR-035 + FR-040 operator-notes preservation).
  final String? initialOperatorNotes;

  @override
  ConsumerState<HandoffFlow> createState() => _HandoffFlowState();
}

class _HandoffFlowState extends ConsumerState<HandoffFlow> {
  int _step = 0;
  // Swarm-review H-P1: TextEditingController previously constructed inside
  // build() so every keystroke + setState produced a fresh controller, lost
  // cursor position, and leaked the prior one. Hoisted to a member field
  // with proper dispose lifecycle.
  late final TextEditingController _workItemController;
  late final TextEditingController _notesController;
  String _workItemExpr = '';
  HandoffMode _mode = HandoffMode.engineeringExecution;
  HandoffPriority? _priority;
  DateTime? _deadline;
  String? _operatorOverrideOfPolicyId;
  String _operatorNotes = '';
  HelperPolicySnapshot? _snapshot;
  List<ResolvedWorkItem> _resolved = const <ResolvedWorkItem>[];

  @override
  void initState() {
    super.initState();
    if (widget.initialPrimaryWorkItem != null) {
      _workItemExpr = widget.initialPrimaryWorkItem!.displayId;
    }
    if (widget.initialMode != null) _mode = widget.initialMode!;
    if (widget.initialOperatorNotes != null) {
      _operatorNotes = widget.initialOperatorNotes!;
    }
    _workItemController = TextEditingController(text: _workItemExpr);
    _notesController = TextEditingController(text: _operatorNotes);
    // Swarm-review H-P2: pre-resolve from any seeded expression so the
    // Preview affordance enables without forcing the operator to type
    // into the field first.
    if (_workItemExpr.isNotEmpty) _resolveRange();
  }

  @override
  void dispose() {
    _workItemController.dispose();
    _notesController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final stepWidgets = <Widget>[
      _step1MasterPicked(),
      _step2ProjectPicked(),
      _step3WorkItem(),
      _step4Mode(),
      _step5Optional(),
    ];
    return Scaffold(
      appBar: AppBar(
        title: const Text('Handoff'),
        actions: [
          if (_step >= 3)
            TextButton.icon(
              onPressed: _resolved.isEmpty ? null : _openPreview,
              icon: const Icon(Icons.visibility),
              label: const Text('Preview'),
            ),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Stepper(
          currentStep: _step,
          onStepTapped: (i) => setState(() => _step = i),
          onStepContinue: _step == stepWidgets.length - 1
              ? _openPreview
              : () => setState(() => _step += 1),
          onStepCancel: _step == 0 ? null : () => setState(() => _step -= 1),
          steps: [
            for (var i = 0; i < stepWidgets.length; i++)
              Step(
                title: Text(_titleFor(i)),
                content: stepWidgets[i],
                isActive: _step >= i,
                state: _step > i ? StepState.complete : StepState.indexed,
              ),
          ],
        ),
      ),
    );
  }

  String _titleFor(int i) => switch (i) {
        0 => 'Target master',
        1 => 'Project',
        2 => 'Work item(s)',
        3 => 'Mode',
        4 => 'Optional inputs',
        _ => 'Step $i',
      };

  Widget _step1MasterPicked() {
    return ListTile(
      leading: const Icon(Icons.psychology),
      title: Text(widget.master.label),
      subtitle: Text(
        'Capability: ${widget.master.capability}  ·  '
        'Status: ${widget.master.currentStatus.wireValue}',
      ),
    );
  }

  Widget _step2ProjectPicked() {
    return ListTile(
      leading: const Icon(Icons.folder),
      title: Text(widget.project.label),
      subtitle: Text(widget.project.repositoryPath),
    );
  }

  Widget _step3WorkItem() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TextField(
          controller: _workItemController,
          decoration: const InputDecoration(
            labelText: 'Work item or range (e.g. FEAT-12 or FEAT-8..FEAT-12)',
            helperText: 'Canonical syntax FEAT-N..FEAT-M (FR-039).',
          ),
          onChanged: (v) {
            _workItemExpr = v;
            _resolveRange();
          },
        ),
        const SizedBox(height: 12),
        if (_resolved.isNotEmpty)
          Padding(
            padding: const EdgeInsets.all(8),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Resolved ${_resolved.length} item(s):',
                  style: Theme.of(context).textTheme.labelMedium,
                ),
                const SizedBox(height: 6),
                for (final item in _resolved)
                  Text('• ${item.renderForPrompt()}'),
              ],
            ),
          ),
      ],
    );
  }

  Widget _step4Mode() {
    return Column(
      children: [
        for (final m in HandoffMode.values)
          RadioListTile<HandoffMode>(
            value: m,
            groupValue: _mode,
            onChanged: (v) => setState(() => _mode = v ?? _mode),
            title: Text(m.wireValue),
          ),
      ],
    );
  }

  Widget _step5Optional() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        DropdownButtonFormField<HandoffPriority?>(
          initialValue: _priority,
          decoration: const InputDecoration(labelText: 'Priority (optional)'),
          items: [
            const DropdownMenuItem(value: null, child: Text('—')),
            for (final p in HandoffPriority.values)
              DropdownMenuItem(value: p, child: Text(p.wireValue)),
          ],
          onChanged: (v) => setState(() => _priority = v),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _notesController,
          decoration: const InputDecoration(
            labelText: 'Operator notes (optional)',
            helperText: 'Preserved through mode changes per FR-040.',
          ),
          minLines: 3,
          maxLines: 8,
          onChanged: (v) => _operatorNotes = v,
        ),
      ],
    );
  }

  void _resolveRange() {
    try {
      // Swarm-review H-B11: previously the catalog was hardcoded as
      // `const []` so EVERY range id resolved as a fake
      // `(excluded: deferred)`. Now we pull the project's
      // feature/change list synchronously from the provider cache (if
      // already loaded) and feed it as the catalog. When the list
      // isn't cached yet, we still allow the resolver to run but the
      // operator sees `(excluded: deferred — not found in feature
      // catalog)` rather than fake-deferred legitimate ids; the
      // pre-resolved list refreshes once the daemon round-trip
      // completes via the existing rebuild path.
      final cached = ref
              .read(project_providers
                  .featureChangeListProvider(widget.project.projectId))
              .valueOrNull ??
          const [];
      final catalog = [
        for (final fc in cached)
          FeatureRangeCatalogEntry(
            displayId: fc.displayId,
            stage: fc.stage,
          ),
      ];
      _resolved = const FeatureRangeResolver().resolve(
        rangeExpr: _workItemExpr,
        catalog: catalog,
      );
    } catch (_) {
      _resolved = const <ResolvedWorkItem>[];
    }
    setState(() {});
  }

  Future<void> _openPreview() async {
    if (_resolved.isEmpty) return;
    _snapshot ??= await _resolveSnapshot();
    final primary = _resolved.first;
    final ctx = await ref.read(autoFillContextProvider).build(
          project: widget.project,
          featureChange: widget.initialPrimaryWorkItem ??
              _stubFeatureChangeFor(primary.displayId),
        );
    if (!mounted) return;
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => HandoffPreviewView(
          targetMasterLabel: widget.master.label,
          targetMasterAgentId: widget.master.agentId,
          project: widget.project,
          mode: _mode,
          priority: _priority,
          deadline: _deadline,
          operatorNotes: _operatorNotes,
          resolved: _resolved,
          primary: WorkItemRef(
            displayId: primary.displayId,
            kind: primary.kind,
          ),
          contextBundle: ctx,
          helperPolicySnapshot: _snapshot!,
        ),
      ),
    );
  }

  Future<HelperPolicySnapshot> _resolveSnapshot() async {
    final resolver = ref.read(helperPolicyResolverProvider);
    try {
      return await resolver.resolve(
        projectId: widget.project.projectId,
        operatorOverrideOfPolicyId: _operatorOverrideOfPolicyId,
      );
    } catch (_) {
      return resolver.degradedSnapshot();
    }
  }

  FeatureChangeStatus _stubFeatureChangeFor(String displayId) {
    return FeatureChangeStatus(
      featureChangeId: displayId,
      displayId: displayId,
      stage: Stage.engineering,
      executionStatus: ExecutionStatus.notStarted,
      humanReadableLabel: 'Engineering / Not Started',
      projectId: widget.project.projectId,
      asOf: DateTime.now().toUtc(),
    );
  }
}

// Re-export so project-card / current-work can wire the modal.
typedef HandoffFlowOpener = void Function({
  required MasterSummary master,
  required Project project,
  FeatureChangeStatus? initialPrimaryWorkItem,
});

void openHandoffFlow(
  BuildContext context, {
  required MasterSummary master,
  required Project project,
  FeatureChangeStatus? initialPrimaryWorkItem,
  HandoffMode? initialMode,
  String? initialOperatorNotes,
}) {
  Navigator.of(context).push(
    MaterialPageRoute<void>(
      builder: (_) => HandoffFlow(
        master: master,
        project: project,
        initialPrimaryWorkItem: initialPrimaryWorkItem,
        initialMode: initialMode,
        initialOperatorNotes: initialOperatorNotes,
      ),
    ),
  );
}

// Avoid unused-import warnings on the providers re-export.
// ignore: unused_element
final _projectProvidersRef = project_providers.projectListProvider;
