import 'package:agenttower_control_panel/domain/models/common_enums.dart';

/// Test fixture builders for integration + unit tests. T053 (Phase 2 Foundational).
///
/// Each builder returns a JSON map shaped like the FEAT-011 response payload
/// for the corresponding entity. Used by the mock-daemon harness (T050) and
/// directly by widget/unit tests that need pre-built model JSON.
///
/// Convention: builders accept named optional parameters with sensible
/// defaults so a test reads `agentFixture(role: 'master')` not 18 lines of
/// boilerplate.

class Fixtures {
  Fixtures._();

  // ---- Container ----
  static Map<String, dynamic> container({
    String containerId = 'bench-1',
    String name = 'bench-frontend',
    String state = 'running',
    String projectPath = '/work/agenttower',
    String? discoveredAt,
  }) =>
      {
        'container_id': containerId,
        'name': name,
        'state': state,
        'project_path': projectPath,
        'discovered_at':
            discoveredAt ?? DateTime.now().toUtc().toIso8601String(),
      };

  // ---- Pane ----
  /// Mirrors the `app.pane` ViewModel. All 6 identity fields
  /// (`container_id`, `tmux_socket`, `tmux_session_name`, `tmux_window_index`,
  /// `tmux_pane_index`, `pane_id`) MUST be present — they are what
  /// `app.agent.register_from_pane` echoes back at FR-028a-mismatch time.
  /// `tmux_window_index` and `tmux_pane_index` are ints per the contract.
  static Map<String, dynamic> pane({
    String paneId = 'p1',
    String containerId = 'bench-1',
    String tmuxSocket = '/tmp/tmux-1000/default',
    String tmuxSession = 'main',
    int tmuxWindow = 0,
    int tmuxPane = 0,
    PaneState state = PaneState.discoveredAndUnmanaged,
    String? registeredAgentId,
    String? lastSeenAt,
  }) =>
      {
        'pane_id': paneId,
        'container_id': containerId,
        'tmux_socket': tmuxSocket,
        'tmux_session_name': tmuxSession,
        'tmux_window_index': tmuxWindow,
        'tmux_pane_index': tmuxPane,
        'state': state.wireValue,
        if (registeredAgentId != null) 'registered_agent_id': registeredAgentId,
        'last_seen_at':
            lastSeenAt ?? DateTime.now().toUtc().toIso8601String(),
      };

  // ---- AdoptedAgent ----
  static Map<String, dynamic> agent({
    String agentId = 'agent-1',
    String label = 'claude-master-1',
    AgentRole role = AgentRole.master,
    String capability = 'claude',
    String projectPath = '/work/agenttower',
    AgentState state = AgentState.active,
    String? parentAgentId,
    int? descendants,
    String containerId = 'bench-1',
    String paneId = 'p1',
    String? lastActivityAt,
  }) =>
      {
        'agent_id': agentId,
        'label': label,
        'role': role.wireValue,
        'capability': capability,
        'project_path': projectPath,
        'state': state.wireValue,
        if (parentAgentId != null) 'parent_agent_id': parentAgentId,
        if (descendants != null) 'descendants_beyond_visible': descendants,
        'container_id': containerId,
        'pane_id': paneId,
        'last_meaningful_activity_at':
            lastActivityAt ?? DateTime.now().toUtc().toIso8601String(),
      };

  // ---- Project (real shape lives further down at Phase-4 US2 builder) ----
  // The Phase-2 stub here was a placeholder before the badge sub-maps existed
  // (data-model §1.1). The current Project freezed class requires nested
  // RepoStateBadge / BranchWorktreeBadge / ValidationBadge / DriftBadge /
  // AttentionSummary maps; the comprehensive builder added by T085 below
  // produces them in the correct shape. Use that one — the stub has been
  // removed to avoid the duplicate-definition compile error.

  // ---- Drift Signal ----
  static Map<String, dynamic> drift({
    String findingId = 'drift-1',
    DriftStatus status = DriftStatus.newFinding,
    DriftSeverity severity = DriftSeverity.warning,
    DriftSource source = DriftSource.staticCheck,
    DriftConfidence confidence = DriftConfidence.medium,
    String summary = 'Branch does not match intended feature/change',
    String recommendedAction = 'Switch to the intended branch or update the spec',
    Map<String, dynamic>? scope,
    List<Map<String, dynamic>>? evidence,
    List<String> linkedFeatureIds = const <String>[],
    List<String> linkedChangeIds = const <String>[],
    String? linkedBranch,
    String? linkedWorktree,
  }) =>
      {
        'finding_id': findingId,
        'status': status.wireValue,
        'severity': severity.wireValue,
        'source': source.wireValue,
        'confidence': confidence.wireValue,
        'age_started_at': DateTime.now().toUtc().toIso8601String(),
        'scope': scope ?? const {'type': 'feature', 'id': 'FEAT-012'},
        'summary': summary,
        'recommended_action': recommendedAction,
        'evidence': evidence ?? const <Map<String, dynamic>>[],
        'linked_feature_ids': linkedFeatureIds,
        'linked_change_ids': linkedChangeIds,
        if (linkedBranch != null) 'linked_branch': linkedBranch,
        if (linkedWorktree != null) 'linked_worktree': linkedWorktree,
      };

  // ---- Handoff (real shape lives further down at Phase-5 US3 builder) ----
  // The Phase-2 stub here was a placeholder before the data-model §1.6
  // requirements were fleshed out. The current Handoff freezed class
  // requires nested context_bundle, helper_policy_snapshot, lifecycle
  // timestamps, etc. The Phase-5 builder added by T097 below is the
  // single source of truth.

  // ---- Validation Run ----
  static Map<String, dynamic> validationRun({
    String runId = 'run-1',
    String entrypointId = 'ep-1',
    RunState state = RunState.queued,
    RunResult? result,
    String triggeredBy = 'test-operator',
  }) =>
      {
        'run_id': runId,
        'entrypoint_id': entrypointId,
        'target': {'kind': 'project', 'id': 'proj-1'},
        'state': state.wireValue,
        if (result != null) 'result': result.wireValue,
        'summary': '',
        'triggered_by': triggeredBy,
      };

  // ---- Validation Entrypoint ----
  static Map<String, dynamic> validationEntrypoint({
    String entrypointId = 'ep-1',
    String label = 'unit tests',
    EntrypointType type = EntrypointType.unitTest,
    BlockingLevel blockingLevel = BlockingLevel.required,
    bool enabled = true,
  }) =>
      {
        'entrypoint_id': entrypointId,
        'label': label,
        'type': type.wireValue,
        'scope': 'project',
        'description': '',
        'estimated_duration_ms': 30000,
        'blocking_level': blockingLevel.wireValue,
        'tags': [],
        'enabled': enabled,
      };

  // ---- Notification ----
  static Map<String, dynamic> notification({
    String notificationId = 'notif-1',
    String eventClass = 'route_skipped',
    String agentId = 'agent-1',
    NotificationSeverity severity = NotificationSeverity.warning,
    String summary = 'Route skipped: source agent paused',
  }) =>
      {
        'notification_id': notificationId,
        'event_class': eventClass,
        'agent_id': agentId,
        'severity': severity.wireValue,
        'emitted_at': DateTime.now().toUtc().toIso8601String(),
        'summary': summary,
        'lifecycle': 'incoming',
      };

  // ---- Event (FR-019 Agent Operations → Events view) ----
  /// Builder for the `app.event` list/detail surface (T5 review fix).
  static Map<String, dynamic> event({
    String eventId = 'evt-1',
    String eventClass = 'route_skipped',
    String? agentId = 'agent-1',
    String? containerId = 'bench-1',
    String? paneId = 'p1',
    String? queueMessageId,
    NotificationSeverity severity = NotificationSeverity.warning,
    String? emittedAt,
    String summary = 'Route skipped: source agent paused',
    Map<String, dynamic>? extra,
  }) =>
      {
        'event_id': eventId,
        'event_class': eventClass,
        if (agentId != null) 'agent_id': agentId,
        if (containerId != null) 'container_id': containerId,
        if (paneId != null) 'pane_id': paneId,
        if (queueMessageId != null) 'queue_message_id': queueMessageId,
        'severity': severity.wireValue,
        'emitted_at': emittedAt ?? DateTime.now().toUtc().toIso8601String(),
        'summary': summary,
        if (extra != null) ...extra,
      };

  // ---- Queue Row (FR-020 5-state safe-prompt queue) ----
  /// Builder for the `app.queue` list/detail surface.
  /// Field names match FEAT-011 `app-methods.md` exactly:
  ///   - `message_id` (not `queue_row_id`)
  ///   - `payload` is the structured object accepted by `app.send_input`
  ///     (`{text: "..."}` by convention; arbitrary shape otherwise)
  ///   - `source_agent_id` / `target_agent_id` (not `from_/to_`)
  static Map<String, dynamic> queueRow({
    String messageId = 'q-1',
    String state = 'blocked',
    String sourceAgentId = 'agent-1',
    String targetAgentId = 'agent-2',
    String? routeId,
    Map<String, dynamic>? payload,
    String? createdAt,
    String? terminalAt,
  }) =>
      {
        'message_id': messageId,
        'state': state,
        'source_agent_id': sourceAgentId,
        'target_agent_id': targetAgentId,
        if (routeId != null) 'route_id': routeId,
        'payload': payload ?? const {'text': 'sample queued prompt'},
        'created_at': createdAt ?? DateTime.now().toUtc().toIso8601String(),
        if (terminalAt != null) 'terminal_at': terminalAt,
      };

  // ---- Route (FR-021 Routes view) ----
  /// Builder for the `app.route` list/detail surface.
  /// Field names match the FEAT-010 route definition surfaced by FEAT-011:
  /// `source_scope`, `template`, `target` (not `from_/to_` agent ids).
  /// `recent_skip_explanation` and `recent_match_summary` are surface
  /// fields for the FR-021 + FR-059 explainability pane.
  static Map<String, dynamic> route({
    String routeId = 'route-1',
    String sourceScope = 'agent:claude-master-1',
    String template = 'forward_event_to',
    String target = 'agent:codex-slave-1',
    String masterRule = 'any',
    bool enabled = true,
    String? recentSkipExplanation,
    String? recentMatchSummary,
  }) =>
      {
        'route_id': routeId,
        'source_scope': sourceScope,
        'template': template,
        'target': target,
        'master_rule': masterRule,
        'enabled': enabled,
        if (recentSkipExplanation != null)
          'recent_skip_explanation': recentSkipExplanation,
        if (recentMatchSummary != null)
          'recent_match_summary': recentMatchSummary,
      };

  // ---- Log Attachment (FR-017) ----
  /// Builder for the `app.log_attachment` list surface (T5 review fix).
  static Map<String, dynamic> logAttachment({
    String attachmentId = 'log-1',
    String agentId = 'agent-1',
    String? paneId = 'p1',
    String logPath = '/work/agenttower/logs/agent-1.log',
    bool isAttached = true,
    String? attachedAt,
    String? detachedAt,
    String? lastError,
  }) =>
      {
        'log_attachment_id': attachmentId,
        'agent_id': agentId,
        if (paneId != null) 'pane_id': paneId,
        'log_path': logPath,
        'is_attached': isAttached,
        'attached_at': attachedAt ?? DateTime.now().toUtc().toIso8601String(),
        if (detachedAt != null) 'detached_at': detachedAt,
        if (lastError != null) 'last_error': lastError,
      };

  // ---- Dashboard counts (FR-012 Agent Operations Dashboard) ----
  /// Builder for the `app.dashboard` result envelope.
  /// Field names match `specs/011-app-backend-contract/contracts/app-methods.md`
  /// §app.dashboard exactly:
  ///   counts.{containers,panes,agents,log_attachments,events,queue,routes}
  ///   recent.{events,queue,routes}
  ///   hints
  ///
  /// FR-012's "recommended next action" + per-state pane/agent breakdowns
  /// are NOT in FEAT-011 v1.0 and are tracked by openspec change
  /// `extend-app-dashboard-fields-for-feat012`. Until that lands the
  /// dashboard view degrades gracefully (Option A: render only the
  /// fields the contract actually returns).
  static Map<String, dynamic> dashboardResult({
    int containersActive = 1,
    int containersInactive = 0,
    int containersDegradedScan = 0,
    int panesTotal = 1,
    int panesRegistered = 0,
    int panesUnregistered = 1,
    int agentsTotal = 0,
    Map<String, int>? agentsByRole,
    int logAttachmentsActive = 0,
    int logAttachmentsDegraded = 0,
    int logAttachmentsNone = 0,
    int eventsTotal = 0,
    int queueQueued = 0,
    int queueBlocked = 0,
    int queueDelivered = 0,
    int queueCanceled = 0,
    int queueFailed = 0,
    int routesEnabled = 0,
    int routesDisabled = 0,
    Map<String, dynamic>? recent,
    List<Map<String, dynamic>>? hints,
  }) =>
      {
        'counts': {
          'containers': {
            'active': containersActive,
            'inactive': containersInactive,
            'degraded_scan': containersDegradedScan,
          },
          'panes': {
            'total': panesTotal,
            'registered': panesRegistered,
            'unregistered': panesUnregistered,
          },
          'agents': {
            'total': agentsTotal,
            'by_role': agentsByRole ??
                const {
                  'master': 0,
                  'slave': 0,
                  'swarm': 0,
                  'test-runner': 0,
                  'shell': 0,
                  'unknown': 0,
                },
          },
          'log_attachments': {
            'active': logAttachmentsActive,
            'degraded': logAttachmentsDegraded,
            'none': logAttachmentsNone,
          },
          'events': {'total': eventsTotal},
          'queue': {
            'queued': queueQueued,
            'blocked': queueBlocked,
            'delivered': queueDelivered,
            'canceled': queueCanceled,
            'failed': queueFailed,
          },
          'routes': {'enabled': routesEnabled, 'disabled': routesDisabled},
        },
        'recent': recent ?? const {'events': [], 'queue': [], 'routes': []},
        'hints': hints ?? const [],
      };

  // ---- Project (Phase 4 US2 / T085) ----
  /// Mirrors `app.project` for the Project + Specs workspace. The badge
  /// sub-maps follow the shapes declared in
  /// `lib/domain/models/badges.dart`; missing optional fields default
  /// to the empty/unknown variants so fixtures stay compact.
  static Map<String, dynamic> project({
    String projectId = 'proj-1',
    String label = 'AgentTower',
    String repositoryPath = '/work/agenttower',
    String repoStateKind = 'clean',
    int? aheadCount,
    int? behindCount,
    int? dirtyFileCount,
    String branchName = 'main',
    String? worktreePath,
    String? activeFeatureChangeId,
    String? currentDrivingMasterAgentId,
    List<String>? primaryMasterAgentIds,
    int masterOverflowCount = 0,
    int subAgentCount = 0,
    String validationKind = 'unknown',
    String? validationLastRunAt,
    String driftSeverity = 'info',
    int driftOpenCount = 0,
    String? driftSource,
    String? driftAge,
    String attentionSeverity = 'info',
    int attentionOpenCount = 0,
    int unreadNotificationCount = 0,
    String? lastActivityAt,
  }) =>
      {
        'project_id': projectId,
        'label': label,
        'repository_path': repositoryPath,
        'repo_state': {
          'kind': repoStateKind,
          if (aheadCount != null) 'ahead_count': aheadCount,
          if (behindCount != null) 'behind_count': behindCount,
          if (dirtyFileCount != null) 'dirty_file_count': dirtyFileCount,
        },
        'active_branch': {
          'branch_name': branchName,
          if (worktreePath != null) 'worktree_path': worktreePath,
          'detached': false,
        },
        if (activeFeatureChangeId != null)
          'active_feature_change_id': activeFeatureChangeId,
        if (currentDrivingMasterAgentId != null)
          'current_driving_master_agent_id': currentDrivingMasterAgentId,
        'primary_master_agent_ids': primaryMasterAgentIds ?? const [],
        'master_overflow_count': masterOverflowCount,
        'sub_agent_count': subAgentCount,
        'validation_badge': {
          'kind': validationKind,
          if (validationLastRunAt != null) 'last_run_at': validationLastRunAt,
        },
        if (validationLastRunAt != null)
          'validation_last_run_at': validationLastRunAt,
        'drift_badge': {
          'highest_severity': driftSeverity,
          'open_count': driftOpenCount,
        },
        if (driftSource != null) 'drift_source': driftSource,
        if (driftAge != null) 'drift_age': driftAge,
        'attention_summary': {
          'highest_severity': attentionSeverity,
          'open_count': attentionOpenCount,
        },
        'unread_notification_count': unreadNotificationCount,
        'last_activity_at':
            lastActivityAt ?? DateTime.now().toUtc().toIso8601String(),
      };

  // ---- FeatureChange (Phase 4 US2 / T084) ----
  static Map<String, dynamic> featureChange({
    String featureChangeId = 'fc-1',
    String displayId = 'FEAT-012',
    String stage = 'engineering',
    String executionStatus = 'active',
    String? subphaseToken,
    String humanReadableLabel = 'Engineering / Active',
    String projectId = 'proj-1',
    String? drivingMasterAgentId,
    String? drivingHandoffId,
  }) =>
      {
        'feature_change_id': featureChangeId,
        'display_id': displayId,
        'stage': stage,
        'execution_status': executionStatus,
        if (subphaseToken != null) 'subphase_token': subphaseToken,
        'human_readable_label': humanReadableLabel,
        'project_id': projectId,
        if (drivingMasterAgentId != null)
          'driving_master_agent_id': drivingMasterAgentId,
        if (drivingHandoffId != null) 'driving_handoff_id': drivingHandoffId,
      };

  // ---- Handoff (Phase 5 US3 / T098) ----
  /// Mirrors `app.handoff`. The shape matches data-model §1.6 and the
  /// freezed `Handoff` class; nested helper-policy + context-bundle
  /// maps are passed-through opaquely so tests can wire either real
  /// snapshots or fixture-built ones.
  static Map<String, dynamic> handoff({
    String? handoffId = 'handoff-1',
    String? draftId,
    String? createdAt,
    String? updatedAt,
    String operatorLabel = 'brett',
    String targetMasterAgentId = 'agent-1',
    String targetMasterLabel = 'claude-master-1',
    String projectId = 'proj-1',
    String projectLabel = 'agenttower',
    String mode = 'engineering_execution',
    String? priority,
    String? deadline,
    String assignmentState = 'submitted',
    List<Map<String, dynamic>>? selectedWorkItems,
    List<Map<String, dynamic>>? resolvedWorkItems,
    Map<String, dynamic>? primaryWorkItem,
    List<String> linkedFeatureIds = const <String>[],
    List<String> linkedChangeIds = const <String>[],
    Map<String, dynamic>? contextBundle,
    String helperPolicyId = 'baked-default',
    Map<String, dynamic>? helperPolicySnapshot,
    String generatedPromptText =
        '## Assignment\n\n- Target master: claude-master-1\n',
    String? operatorNotes,
    String? submittedAt,
    String? acceptedAt,
    String? completedAt,
    String? cancelledAt,
    String? supersededByHandoffId,
    String? supersedesHandoffId,
    Map<String, dynamic>? deliveryStatus,
    Map<String, dynamic>? failureContext,
  }) {
    final now = DateTime.now().toUtc().toIso8601String();
    return {
      if (handoffId != null) 'handoff_id': handoffId,
      if (draftId != null) 'draft_id': draftId,
      'created_at': createdAt ?? now,
      'updated_at': updatedAt ?? now,
      'operator_label': operatorLabel,
      'target_master_agent_id': targetMasterAgentId,
      'target_master_label': targetMasterLabel,
      'project_id': projectId,
      'project_label': projectLabel,
      'mode': mode,
      if (priority != null) 'priority': priority,
      if (deadline != null) 'deadline': deadline,
      'assignment_state': assignmentState,
      'selected_work_items': selectedWorkItems ?? const <Map<String, dynamic>>[],
      'resolved_work_items': resolvedWorkItems ??
          const [
            {'display_id': 'FEAT-12', 'kind': 'feature'},
          ],
      'primary_work_item': primaryWorkItem ??
          const {'display_id': 'FEAT-12', 'kind': 'feature'},
      'linked_feature_ids': linkedFeatureIds,
      'linked_change_ids': linkedChangeIds,
      'context_bundle': contextBundle ??
          {
            'repository_path': '/work/agenttower',
            'active_branch': 'main',
          },
      'helper_policy_id': helperPolicyId,
      'helper_policy_snapshot': helperPolicySnapshot ??
          helperPolicySnapshotResult(),
      'generated_prompt_text': generatedPromptText,
      if (operatorNotes != null) 'operator_notes': operatorNotes,
      if (submittedAt != null) 'submitted_at': submittedAt,
      if (acceptedAt != null) 'accepted_at': acceptedAt,
      if (completedAt != null) 'completed_at': completedAt,
      if (cancelledAt != null) 'cancelled_at': cancelledAt,
      if (supersededByHandoffId != null)
        'superseded_by_handoff_id': supersededByHandoffId,
      if (supersedesHandoffId != null)
        'supersedes_handoff_id': supersedesHandoffId,
      if (deliveryStatus != null) 'delivery_status': deliveryStatus,
      if (failureContext != null) 'failure_context': failureContext,
    };
  }

  /// Mirrors `HelperPolicySnapshot` (data-model §1.8 / Phase 5 T100).
  static Map<String, dynamic> helperPolicySnapshotResult({
    String policyId = 'baked-default',
    String defaultHelperCapability = 'shell',
    List<String> allowedHelperCapabilities = const <String>['shell'],
    String policySource = 'baked_default',
    String? snapshottedAt,
    String? operatorOverrideOfPolicyId,
    String? repoOverridePath,
  }) =>
      {
        'resolved_policy': {
          'policy_id': policyId,
          'allowed_helper_capabilities': allowedHelperCapabilities,
          'default_helper_capability': defaultHelperCapability,
          'policy_source': policySource,
        },
        'snapshotted_at':
            snapshottedAt ?? DateTime.now().toUtc().toIso8601String(),
        if (operatorOverrideOfPolicyId != null)
          'operator_override_of_policy_id': operatorOverrideOfPolicyId,
        if (repoOverridePath != null) 'repo_override_path': repoOverridePath,
      };

  // ---- Capability registry (Phase 4 US2 / T086) ----
  static Map<String, dynamic> capabilityRegistryResult({
    List<String> masterClass = const ['claude', 'codex', 'gemini'],
    List<String> slaveClass = const ['claude', 'codex', 'shell'],
  }) =>
      {
        'master_class': masterClass,
        'slave_class': slaveClass,
      };

  // ---- Paginated list / single-entity result wrappers ----
  /// Wraps a list of entity maps in the FEAT-011 `app.<entity>.list`
  /// success-result shape: `{rows, total, cursor_next, ordering}`. Use this
  /// when constructing fixtures so the wire envelope matches contract line
  /// 184.
  static Map<String, dynamic> listResult(
    List<Map<String, dynamic>> rows, {
    String? cursorNext,
    int? total,
    int? totalEstimate,
    String ordering = 'default',
  }) =>
      {
        'rows': rows,
        'total': total ?? (totalEstimate == null ? rows.length : null),
        'total_estimate': totalEstimate,
        'cursor_next': cursorNext,
        'ordering': ordering,
      };

  /// Wraps a single entity map in the FEAT-011 `result.row` envelope
  /// used by every `.detail` call and every mutation except `send_input`
  /// and `scan.*` (contract line 22).
  static Map<String, dynamic> rowResult(Map<String, dynamic> row) =>
      {'row': row};

  // ---- Preflight (FR-009 doctor + Settings) ----
  /// Builder for the `app.preflight` result envelope (T5 review fix).
  static Map<String, dynamic> preflightResult({
    bool ok = true,
    List<Map<String, dynamic>>? checks,
  }) =>
      {
        'ok': ok,
        'checks': checks ??
            const [
              {
                'name': 'daemon_socket',
                'status': 'ok',
                'reason': '',
                'hint': null,
              },
            ],
      };

  // ---- Readiness (FR-022 Health view) ----
  /// Builder for the `app.readiness` result envelope (T5 review fix).
  static Map<String, dynamic> readinessResult({
    String state = 'ready',
    List<Map<String, dynamic>>? subsystems,
    List<Map<String, dynamic>>? hints,
  }) =>
      {
        'state': state,
        'subsystems': subsystems ??
            const [
              {
                'name': 'docker',
                'status': 'ok',
                'reason': '',
                'hint': null,
              },
              {
                'name': 'tmux_discovery',
                'status': 'ok',
                'reason': '',
                'hint': null,
              },
              {
                'name': 'sqlite',
                'status': 'ok',
                'reason': '',
                'hint': null,
              },
              {
                'name': 'jsonl',
                'status': 'ok',
                'reason': '',
                'hint': null,
              },
              {
                'name': 'routing_worker',
                'status': 'ok',
                'reason': '',
                'hint': null,
              },
              {
                'name': 'log_attachment_workers',
                'status': 'ok',
                'reason': '',
                'hint': null,
              },
            ],
        'hints': hints ?? const [],
      };
}
