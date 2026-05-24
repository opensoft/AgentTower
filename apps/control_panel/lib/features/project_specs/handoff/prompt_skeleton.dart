import '../../../domain/helper_policy/helper_policy.dart';
import '../../../domain/models/common_enums.dart';
import '../../../domain/models/handoff_supporting.dart';
import '../../../domain/models/resolved_work_item.dart';

/// FR-040 + FR-041 — prompt skeleton renderer. T106 (Phase 5 US3).
///
/// **Section order (FR-040, IMMUTABLE)**:
///   1. Assignment
///   2. Project Context
///   3. Workflow Instruction
///   4. Helper-Agent Policy
///   5. Success Criteria
///   6. Stopping and Escalation Rules
///
/// **Mode-change behavior (FR-040)**: switching [mode] regenerates the
/// body while preserving operator notes already entered. The skeleton
/// itself is system-owned — the operator cannot edit any of the six
/// sections directly (FR-041); edits to the body via the preview
/// surface are rejected with an inline explanation.
///
/// **Resolved-list invariant (SC-004)**: the resolved-work-items
/// section MUST render entries using [ResolvedWorkItemRendering.renderForPrompt]
/// so the preview and the submitted prompt cannot drift byte-for-byte.
class PromptSkeleton {
  const PromptSkeleton({
    required this.targetMasterLabel,
    required this.projectLabel,
    required this.mode,
    required this.primaryWorkItem,
    required this.resolvedWorkItems,
    required this.contextBundle,
    required this.helperPolicySnapshot,
    this.priority,
    this.deadline,
    this.operatorNotes,
  });

  final String targetMasterLabel;
  final String projectLabel;
  final HandoffMode mode;
  final WorkItemRef primaryWorkItem;
  final List<ResolvedWorkItem> resolvedWorkItems;
  final HandoffContextBundle contextBundle;
  final HelperPolicySnapshot helperPolicySnapshot;
  final HandoffPriority? priority;
  final DateTime? deadline;
  final String? operatorNotes;

  /// Renders the full prompt body in FR-040 section order. Output is
  /// markdown-flavored plain text. The exact byte sequence is the
  /// reference point for SC-004's preview-matches-submitted-prompt
  /// invariant; the preview surface and the submit pipeline MUST
  /// invoke this method on the same draft to satisfy the contract.
  String render() {
    final buf = StringBuffer();
    _assignment(buf);
    _projectContext(buf);
    _workflowInstruction(buf);
    _helperAgentPolicy(buf);
    _successCriteria(buf);
    _stoppingAndEscalationRules(buf);
    if (operatorNotes != null && operatorNotes!.trim().isNotEmpty) {
      buf.writeln();
      buf.writeln('---');
      buf.writeln();
      buf.writeln('## Operator Notes');
      buf.writeln();
      buf.writeln(operatorNotes!.trim());
    }
    return buf.toString();
  }

  void _assignment(StringBuffer buf) {
    buf.writeln('## Assignment');
    buf.writeln();
    buf.writeln('- Target master: $targetMasterLabel');
    buf.writeln('- Project: $projectLabel');
    buf.writeln('- Mode: ${mode.wireValue}');
    buf.writeln('- Primary work item: ${primaryWorkItem.displayId}');
    if (priority != null) buf.writeln('- Priority: ${priority!.wireValue}');
    if (deadline != null) buf.writeln('- Deadline: ${deadline!.toIso8601String()}');
    buf.writeln();
    buf.writeln('### Resolved work items');
    buf.writeln();
    for (final item in resolvedWorkItems) {
      buf.writeln('- ${item.renderForPrompt()}');
    }
    buf.writeln();
  }

  void _projectContext(StringBuffer buf) {
    buf.writeln('## Project Context');
    buf.writeln();
    buf.writeln('- Repository: ${contextBundle.repositoryPath}');
    if (contextBundle.activeBranch != null) {
      buf.writeln('- Active branch: ${contextBundle.activeBranch}');
    }
    if (contextBundle.worktreePath != null) {
      buf.writeln('- Worktree: ${contextBundle.worktreePath}');
    }
    if (contextBundle.prdPath != null) {
      buf.writeln('- PRD: ${contextBundle.prdPath}');
    }
    if (contextBundle.architecturePath != null) {
      buf.writeln('- Architecture: ${contextBundle.architecturePath}');
    }
    if (contextBundle.roadmapPath != null) {
      buf.writeln('- Roadmap: ${contextBundle.roadmapPath}');
    }
    final featureSpecs = contextBundle.featureSpecPaths ?? const <String>[];
    if (featureSpecs.isNotEmpty) {
      buf.writeln('- Feature specs:');
      for (final p in featureSpecs) {
        buf.writeln('  - $p');
      }
    }
    final changes = contextBundle.openspecChangePaths ?? const <String>[];
    if (changes.isNotEmpty) {
      buf.writeln('- OpenSpec changes:');
      for (final p in changes) {
        buf.writeln('  - $p');
      }
    }
    if (contextBundle.currentStage != null) {
      buf.writeln('- Current stage: ${contextBundle.currentStage}');
    }
    if (contextBundle.currentExecutionStatus != null) {
      buf.writeln(
        '- Current execution status: ${contextBundle.currentExecutionStatus}',
      );
    }
    if (contextBundle.currentSubphaseToken != null) {
      buf.writeln('- Current subphase: ${contextBundle.currentSubphaseToken}');
    }
    if (contextBundle.driftStateSummary != null) {
      buf.writeln('- Drift state: ${contextBundle.driftStateSummary}');
    }
    if (contextBundle.validationStateSummary != null) {
      buf.writeln('- Validation state: ${contextBundle.validationStateSummary}');
    }
    buf.writeln();
  }

  void _workflowInstruction(StringBuffer buf) {
    buf.writeln('## Workflow Instruction');
    buf.writeln();
    final repoRules = contextBundle.repoWorkflowRulesText;
    if (repoRules != null && repoRules.trim().isNotEmpty) {
      buf.writeln(repoRules.trim());
    } else {
      buf.writeln(_defaultWorkflowFor(mode));
    }
    buf.writeln();
  }

  void _helperAgentPolicy(StringBuffer buf) {
    final policy = helperPolicySnapshot.resolvedPolicy;
    buf.writeln('## Helper-Agent Policy');
    buf.writeln();
    buf.writeln('- Policy id: ${policy.policyId}');
    buf.writeln('- Source: ${policy.policySource.wireValue}');
    if (helperPolicySnapshot.operatorOverrideOfPolicyId != null) {
      buf.writeln(
        '- Operator override of: ${helperPolicySnapshot.operatorOverrideOfPolicyId}',
      );
    }
    if (helperPolicySnapshot.repoOverridePath != null) {
      buf.writeln('- Repo override path: ${helperPolicySnapshot.repoOverridePath}');
    }
    buf.writeln('- Default helper: ${policy.defaultHelperCapability}');
    final allowed = policy.allowedHelperCapabilities.toList()..sort();
    buf.writeln('- Allowed helpers: ${allowed.join(", ")}');
    buf.writeln();
  }

  void _successCriteria(StringBuffer buf) {
    buf.writeln('## Success Criteria');
    buf.writeln();
    buf.writeln(_defaultSuccessFor(mode));
    buf.writeln();
  }

  void _stoppingAndEscalationRules(StringBuffer buf) {
    buf.writeln('## Stopping and Escalation Rules');
    buf.writeln();
    buf.writeln(
      '- Stop and surface an attention item if any required helper '
      'capability is unavailable.',
    );
    buf.writeln(
      '- Stop and request operator input if the resolved work item set '
      'changes during execution.',
    );
    buf.writeln(
      '- Escalate via the safe prompt queue (FEAT-009) if a blocking '
      'drift finding appears for the primary work item.',
    );
    buf.writeln();
  }

  static String _defaultWorkflowFor(HandoffMode mode) {
    return switch (mode) {
      HandoffMode.specRefinement =>
        'Operate in spec-refinement mode: read the linked specs, propose '
            'edits as diffs, and surface ambiguities back to the operator '
            'without modifying production code.',
      HandoffMode.engineeringExecution =>
        'Execute the engineering phase per the linked specs: produce '
            'commits on the active branch, run validation, and report '
            'progress per the workflow rules.',
      HandoffMode.driftRepair =>
        'Operate in drift-repair mode: triage open drift findings, '
            'produce repairs as discrete commits, and re-run validation '
            'on each repair.',
      HandoffMode.validationDemoPrep =>
        'Prepare the project for validation + demo: run the available '
            'validation suite, summarize results, and prepare a demo '
            'narrative referencing the resolved work items.',
    };
  }

  static String _defaultSuccessFor(HandoffMode mode) {
    return switch (mode) {
      HandoffMode.specRefinement =>
        'Spec edits land as a reviewable proposal; ambiguities are '
            'enumerated; no production-code commits.',
      HandoffMode.engineeringExecution =>
        'All resolved work items reach `complete` execution status; '
            'validation suite passes; no critical drift findings remain.',
      HandoffMode.driftRepair =>
        'All targeted drift findings transition to `resolved` or '
            '`accepted_as_built`; validation passes on each repair.',
      HandoffMode.validationDemoPrep =>
        'Demo Readiness summary is `ready`; validation runs are recent; '
            'demo narrative names every resolved work item.',
    };
  }
}
