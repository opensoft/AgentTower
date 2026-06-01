import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/l10n/app_localizations.dart';
import '../../../core/providers.dart';
import '../../../domain/helper_policy/helper_policy.dart';
import '../../../ui/widgets/contract_checked_button.dart';
import '../../../domain/models/common_enums.dart';
import '../../../domain/models/handoff_supporting.dart';
import '../../../domain/models/project.dart';
import '../../../domain/models/resolved_work_item.dart';
import 'prompt_skeleton.dart';
import 'submit_flow.dart';

/// FR-040 + FR-041 — handoff preview surface. T107 (Phase 5 US3).
///
/// Renders the prompt body via [PromptSkeleton.render]. Edits to the
/// skeleton sections are rejected per FR-041 — the operator can only
/// edit operator notes, selected work items, mode, helper-policy
/// override, priority, and deadline via the upstream flow.
///
/// Submit → calls [submitHandoff] from `submit_flow.dart` which
/// handles the FR-072 (a/b/c) failure tiers.
class HandoffPreviewView extends ConsumerStatefulWidget {
  const HandoffPreviewView({
    super.key,
    required this.targetMasterLabel,
    required this.targetMasterAgentId,
    required this.project,
    required this.mode,
    required this.priority,
    required this.deadline,
    required this.operatorNotes,
    required this.resolved,
    required this.primary,
    required this.contextBundle,
    required this.helperPolicySnapshot,
  });

  final String targetMasterLabel;
  final String targetMasterAgentId;
  final Project project;
  final HandoffMode mode;
  final HandoffPriority? priority;
  final DateTime? deadline;
  final String operatorNotes;
  final List<ResolvedWorkItem> resolved;
  final WorkItemRef primary;
  final HandoffContextBundle contextBundle;
  final HelperPolicySnapshot helperPolicySnapshot;

  @override
  ConsumerState<HandoffPreviewView> createState() =>
      _HandoffPreviewViewState();
}

class _HandoffPreviewViewState extends ConsumerState<HandoffPreviewView> {
  bool _submitting = false;
  String? _error;

  @override
  Widget build(BuildContext context) {
    final skeleton = PromptSkeleton(
      targetMasterLabel: widget.targetMasterLabel,
      projectLabel: widget.project.label,
      mode: widget.mode,
      primaryWorkItem: widget.primary,
      resolvedWorkItems: widget.resolved,
      contextBundle: widget.contextBundle,
      helperPolicySnapshot: widget.helperPolicySnapshot,
      priority: widget.priority,
      deadline: widget.deadline,
      operatorNotes: widget.operatorNotes,
    );
    final body = skeleton.render();
    final l10n = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.handoffPreviewTitle),
        actions: [
          // Swarm-review CR-7 + H-B7/H-B8: submission is gated on
          // both the in-flight state and the contract-version invariant.
          // ContractCheckedButton disables the action with an inline
          // tooltip when the daemon is unreachable or contract-incompat.
          ContractCheckedButton(
            additionalGate: !_submitting,
            onPressed: () => _submit(body),
            builder: (ctx, onPressed, reason) => FilledButton.icon(
              onPressed: onPressed,
              icon: _submitting
                  ? const SizedBox(
                      height: 16,
                      width: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.send),
              label: Text(_submitting
                  ? l10n.handoffPreviewSubmitting
                  : l10n.handoffPreviewSubmit),
            ),
          ),
          const SizedBox(width: 12),
        ],
      ),
      body: Column(
        children: [
          if (_error != null)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              color: Theme.of(context).colorScheme.errorContainer,
              child: Text(
                _error!,
                style: TextStyle(
                  color: Theme.of(context).colorScheme.onErrorContainer,
                ),
              ),
            ),
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: SelectableText(
                body,
                style: const TextStyle(
                  fontFamily: 'monospace',
                  fontSize: 13,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _submit(String generatedPromptText) async {
    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      final handoff = await submitHandoff(
        appClient: ref.read(appClientProvider),
        operatorLabel: Platform.environment['USER'] ?? 'operator',
        selectedWorkItems: [
          for (final r in widget.resolved)
            WorkItemRef(displayId: r.displayId, kind: r.kind),
        ],
        linkedFeatureIds: [
          for (final r in widget.resolved)
            if (r.exclusion == null && r.kind == WorkItemKind.feature)
              r.displayId,
        ],
        linkedChangeIds: [
          for (final r in widget.resolved)
            if (r.exclusion == null && r.kind == WorkItemKind.change)
              r.displayId,
        ],
        targetMasterLabel: widget.targetMasterLabel,
        targetMasterAgentId: widget.targetMasterAgentId,
        project: widget.project,
        mode: widget.mode,
        priority: widget.priority,
        deadline: widget.deadline,
        operatorNotes: widget.operatorNotes,
        resolved: widget.resolved,
        primary: widget.primary,
        contextBundle: widget.contextBundle,
        helperPolicySnapshot: widget.helperPolicySnapshot,
        generatedPromptText: generatedPromptText,
      );
      if (!mounted) return;
      Navigator.of(context).pop();
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            AppLocalizations.of(context).handoffPreviewSubmittedSnack(
              handoff.handoffId ?? handoff.draftId ?? "?",
            ),
          ),
        ),
      );
    } catch (e) {
      setState(() {
        _submitting = false;
        _error = e.toString();
      });
    }
  }
}
