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
  static Map<String, dynamic> pane({
    String paneId = 'p1',
    String containerId = 'bench-1',
    String tmuxSession = 'main',
    String tmuxWindow = '0',
    String tmuxPane = '0',
    PaneState state = PaneState.discoveredAndUnmanaged,
    String? registeredAgentId,
    String? lastSeenAt,
  }) =>
      {
        'pane_id': paneId,
        'container_id': containerId,
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

  // ---- Project ----
  static Map<String, dynamic> project({
    String projectId = 'proj-1',
    String label = 'agenttower',
    String repositoryPath = '/work/agenttower',
    String? activeFeatureChangeId,
    String? currentDrivingMasterAgentId,
    int unreadNotificationCount = 0,
  }) =>
      {
        'project_id': projectId,
        'label': label,
        'repository_path': repositoryPath,
        'repo_state': 'clean',
        'active_branch': '012-flutter-control-panel',
        if (activeFeatureChangeId != null)
          'active_feature_change_id': activeFeatureChangeId,
        if (currentDrivingMasterAgentId != null)
          'current_driving_master_agent_id': currentDrivingMasterAgentId,
        'validation_badge': 'unknown',
        'drift_badge': 'none',
        'attention_summary': {'count': 0, 'highest_severity': 'info'},
        'unread_notification_count': unreadNotificationCount,
        'last_activity_at': DateTime.now().toUtc().toIso8601String(),
      };

  // ---- Drift Signal ----
  static Map<String, dynamic> drift({
    String findingId = 'drift-1',
    DriftStatus status = DriftStatus.newFinding,
    DriftSeverity severity = DriftSeverity.warning,
    DriftSource source = DriftSource.staticCheck,
    DriftConfidence confidence = DriftConfidence.medium,
    String summary = 'Branch does not match intended feature/change',
    String recommendedAction = 'Switch to the intended branch or update the spec',
  }) =>
      {
        'finding_id': findingId,
        'status': status.wireValue,
        'severity': severity.wireValue,
        'source': source.wireValue,
        'confidence': confidence.wireValue,
        'age_started_at': DateTime.now().toUtc().toIso8601String(),
        'scope': {'type': 'feature', 'id': 'FEAT-012'},
        'summary': summary,
        'recommended_action': recommendedAction,
        'evidence': [],
      };

  // ---- Handoff ----
  static Map<String, dynamic> handoff({
    String? handoffId,
    String? draftId,
    String targetMasterAgentId = 'agent-1',
    String projectId = 'proj-1',
    HandoffMode mode = HandoffMode.engineeringExecution,
    AssignmentState state = AssignmentState.drafted,
  }) =>
      {
        if (handoffId != null) 'handoff_id': handoffId,
        if (draftId != null) 'draft_id': draftId,
        'created_at': DateTime.now().toUtc().toIso8601String(),
        'updated_at': DateTime.now().toUtc().toIso8601String(),
        'operator': 'test-operator',
        'target_master_agent_id': targetMasterAgentId,
        'project_id': projectId,
        'mode': mode.wireValue,
        'assignment_state': state.wireValue,
        'selected_work_items': [
          {'kind': 'feature', 'display_id': 'FEAT-012'}
        ],
        'resolved_work_items': [
          {'kind': 'feature', 'display_id': 'FEAT-012', 'exclusion': null}
        ],
        'primary_work_item': {'kind': 'feature', 'display_id': 'FEAT-012'},
        'helper_policy_id': 'baked-default-1',
      };

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
  /// Builder for the `app.queue` list/detail surface (T5 review fix).
  static Map<String, dynamic> queueRow({
    String messageId = 'q-1',
    String state = 'blocked',
    String fromAgentId = 'agent-1',
    String toAgentId = 'agent-2',
    String? routeId,
    String? reason,
    String? createdAt,
    String? lastTransitionAt,
    Map<String, dynamic>? payloadPreview,
  }) =>
      {
        'message_id': messageId,
        'state': state,
        'from_agent_id': fromAgentId,
        'to_agent_id': toAgentId,
        if (routeId != null) 'route_id': routeId,
        if (reason != null) 'reason': reason,
        'created_at': createdAt ?? DateTime.now().toUtc().toIso8601String(),
        'last_transition_at':
            lastTransitionAt ?? DateTime.now().toUtc().toIso8601String(),
        'payload_preview': payloadPreview ?? const {},
      };

  // ---- Route (FR-021 Routes view) ----
  /// Builder for the `app.route` list/detail surface (T5 review fix).
  static Map<String, dynamic> route({
    String routeId = 'route-1',
    String fromAgentId = 'agent-1',
    String toAgentId = 'agent-2',
    bool enabled = true,
    String? label,
    int matchedCount = 0,
    int skippedCount = 0,
    String? lastMatchedAt,
    String? lastSkippedAt,
    String? lastSkipReason,
  }) =>
      {
        'route_id': routeId,
        'from_agent_id': fromAgentId,
        'to_agent_id': toAgentId,
        'enabled': enabled,
        if (label != null) 'label': label,
        'matched_count': matchedCount,
        'skipped_count': skippedCount,
        if (lastMatchedAt != null) 'last_matched_at': lastMatchedAt,
        if (lastSkippedAt != null) 'last_skipped_at': lastSkippedAt,
        if (lastSkipReason != null) 'last_skip_reason': lastSkipReason,
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
  /// Builder for the `app.dashboard` result envelope (T5 review fix).
  static Map<String, dynamic> dashboardResult({
    int containersActive = 1,
    int containersInactive = 0,
    int containersDegradedScan = 0,
    Map<String, int>? panesByState,
    Map<String, int>? agentsByState,
    int blockedQueue = 0,
    int recentlySkippedRoutes = 0,
    List<Map<String, dynamic>>? recents,
    Map<String, dynamic>? recommendedNextAction,
    List<Map<String, dynamic>>? hints,
  }) =>
      {
        'counts': {
          'containers': {
            'active': containersActive,
            'inactive': containersInactive,
            'degraded_scan': containersDegradedScan,
          },
          'panes_by_state':
              panesByState ?? const {'discovered-and-unmanaged': 1},
          'registered_agents_by_state': agentsByState ?? const {},
          'blocked_queue': blockedQueue,
          'recently_skipped_routes': recentlySkippedRoutes,
        },
        'recents': recents ?? const [],
        'recommended_next_action': recommendedNextAction,
        'hints': hints ?? const [],
      };

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
