import 'dart:async';

import 'envelope.dart';
import 'errors.dart';
import 'mutation_keys.dart';
import 'session.dart';

/// Typed wrappers around the FEAT-011 `app.*` methods consumed by the
/// FEAT-012 desktop app.
///
/// T014 (Phase 2 Foundational) — base wrappers for bootstrap surfaces.
/// T063 (Phase 3 US1) — US1 read surfaces (container/pane/agent/
///   log_attachment/event/queue/route + their `.list` / `.detail`).
/// T064 (Phase 3 US1) — US1 mutations (register_from_pane, agent.update,
///   log.attach/detach, send_input, queue.approve/delay/cancel,
///   route.add/remove/update, scan.containers/panes/status).
///
/// All wire field names / shapes are sourced from
/// `specs/011-app-backend-contract/contracts/app-methods.md` directly.
/// Per that contract (line 22): every `.detail` and every mutation
/// response (except `app.send_input` and the three `app.scan.*`
/// methods) wraps its single-entity payload under `result.row` — the
/// singular counterpart of `.list`'s `result.rows[]` array. This
/// client unwraps the `row` key for callers so consumers see a flat
/// entity map.
///
/// `app.preflight` is intentionally NOT exposed here: it does not require
/// a session token and must be callable BEFORE bootstrap (review fix
/// A4). Use [PreflightClient] from `preflight_client.dart` instead.
///
/// Mutation surfaces auto-stamp `idempotency_key` via [MutationKeys.fresh]
/// per Round-3 R-28 unless the caller passes one explicitly (the explicit
/// path is useful for "retry the same logical action" affordances —
/// FR-020 queue retry, FR-072 handoff retry, etc.).
class AppClient {
  AppClient({required this.session});

  final DaemonSession session;

  // ============================================================== Bootstrap

  /// `app.readiness` — per-subsystem readiness probe (FR-022).
  /// Returns raw result; Health view (T076) interprets fields.
  Future<Map<String, dynamic>> readiness() async {
    final env = await session.call('app.readiness');
    return _unwrapResult(env);
  }

  /// `app.dashboard` — Agent Operations Dashboard counts + recents (FR-012).
  /// Returns raw result; Dashboard view (T065) interprets fields.
  ///
  /// Per contract (`app-methods.md` §app.dashboard) the response shape is
  /// `{counts:{containers,panes,agents,log_attachments,events,queue,routes},
  ///   recent:{events,queue,routes}, hints:[]}` — no `recommended_next_action`
  /// field at v1.0. The FR-012 "recommended next action" tile is suppressed
  /// in the UI until the openspec/extend-app-dashboard-fields-for-feat012
  /// proposal lands and bumps the contract to 1.1.
  Future<Map<String, dynamic>> dashboard({int recentLimit = 10}) async {
    final env = await session.call(
      'app.dashboard',
      params: {'recent_limit': recentLimit},
    );
    return _unwrapResult(env);
  }

  // ============================================================ Read surfaces

  // -------- container

  Future<PagedResult> containerList({String? cursorNext, int? limit}) =>
      _list('app.container.list', cursorNext: cursorNext, limit: limit);

  Future<Map<String, dynamic>> containerDetail(String containerId) =>
      _detail('app.container.detail', {'container_id': containerId});

  // -------- pane

  Future<PagedResult> paneList({String? cursorNext, int? limit}) =>
      _list('app.pane.list', cursorNext: cursorNext, limit: limit);

  Future<Map<String, dynamic>> paneDetail(String paneId) =>
      _detail('app.pane.detail', {'pane_id': paneId});

  // -------- agent

  // Swarm-review H-E1: removed the `projectId` parameter. Per
  // app-methods.md line 203 the v1.0 agent-filter closed set is
  // {role, capability, container_id, log_attached} — `project_id`
  // is NOT an accepted filter, so the daemon would have rejected
  // it with `validation_failed.details.field == "project_id"`.
  // Project-scoped agent enumeration is a v1.x extension; gate it
  // behind a capability flag when it ships.
  Future<PagedResult> agentList({
    String? cursorNext,
    int? limit,
    String? role,
    String? capability,
    String? containerId,
    bool? logAttached,
  }) =>
      _list(
        'app.agent.list',
        cursorNext: cursorNext,
        limit: limit,
        extra: {
          if (role != null) 'role': role,
          if (capability != null) 'capability': capability,
          if (containerId != null) 'container_id': containerId,
          if (logAttached != null) 'log_attached': logAttached,
        },
      );

  Future<Map<String, dynamic>> agentDetail(String agentId) =>
      _detail('app.agent.detail', {'agent_id': agentId});

  // -------- log_attachment

  Future<PagedResult> logAttachmentList({String? cursorNext, int? limit}) =>
      _list('app.log_attachment.list', cursorNext: cursorNext, limit: limit);

  Future<Map<String, dynamic>> logAttachmentDetail(String attachmentId) =>
      _detail('app.log_attachment.detail', {
        'log_attachment_id': attachmentId,
      });

  // -------- event

  /// `app.event.list` — `event_id DESC` per contract (line 205). Events
  /// view (T072) calls with `cursorNext=null` to anchor at the head
  /// and uses `cursor_next` to scroll backwards in time.
  Future<PagedResult> eventList({
    String? cursorNext,
    int? limit,
    String? agentId,
  }) =>
      _list(
        'app.event.list',
        cursorNext: cursorNext,
        limit: limit,
        extra: {if (agentId != null) 'agent_id': agentId},
      );

  Future<Map<String, dynamic>> eventDetail(String eventId) =>
      _detail('app.event.detail', {'event_id': eventId});

  // -------- queue

  Future<PagedResult> queueList({String? cursorNext, int? limit}) =>
      _list('app.queue.list', cursorNext: cursorNext, limit: limit);

  /// `app.queue.detail` is keyed on `message_id` per contract line 225,
  /// not `queue_row_id` — those are the same logical id but the wire
  /// name is `message_id`.
  Future<Map<String, dynamic>> queueDetail(String messageId) =>
      _detail('app.queue.detail', {'message_id': messageId});

  // -------- route

  Future<PagedResult> routeList({String? cursorNext, int? limit}) =>
      _list('app.route.list', cursorNext: cursorNext, limit: limit);

  Future<Map<String, dynamic>> routeDetail(String routeId) =>
      _detail('app.route.detail', {'route_id': routeId});

  // -------- project (T085 — Phase 4 US2)
  //
  // Per contracts/app-methods-consumed.md §3, these methods are
  // anticipated v1.x additions to FEAT-011. If absent at runtime,
  // calls surface as FailureEnvelope and the Project-Specs surfaces
  // degrade to `contract-version-incompatible` per FR-002 / FR-004
  // (handled by the providers, not here — this layer stays neutral).

  Future<PagedResult> projectList({String? cursorNext, int? limit}) =>
      _list('app.project.list', cursorNext: cursorNext, limit: limit);

  Future<Map<String, dynamic>> projectDetail(String projectId) =>
      _detail('app.project.detail', {'project_id': projectId});

  /// `app.project.add` — explicit add-project (per Assumption: project
  /// registration model). Returns the new project row. The daemon
  /// canonicalizes the path; same path → same `projectId` (FR-026).
  Future<Map<String, dynamic>> projectAdd({
    required String repositoryPath,
    String? label,
    String? idempotencyKey,
  }) async {
    final env = await session.call(
      'app.project.add',
      params: {
        'repository_path': repositoryPath,
        if (label != null) 'label': label,
        'idempotency_key': idempotencyKey ?? MutationKeys.fresh(),
      },
    );
    return _unwrapRow(env);
  }

  /// `app.project.remove` — FR-077 removal. The daemon does NOT delete
  /// the underlying agents/handoffs/drift/runs; it only forgets the
  /// project registration so it falls off the Projects view (until
  /// re-inferred from an adopted agent's `project_path`). The app
  /// clears its own per-project UI persistence separately.
  Future<Map<String, dynamic>> projectRemove({
    required String projectId,
    String? idempotencyKey,
  }) async {
    final env = await session.call(
      'app.project.remove',
      params: {
        'project_id': projectId,
        'idempotency_key': idempotencyKey ?? MutationKeys.fresh(),
      },
    );
    return _unwrapRow(env);
  }

  // -------- feature_change (T085 — Phase 4 US2)

  Future<PagedResult> featureChangeList({
    String? cursorNext,
    int? limit,
    String? projectId,
  }) =>
      _list(
        'app.feature_change.list',
        cursorNext: cursorNext,
        limit: limit,
        extra: {if (projectId != null) 'project_id': projectId},
      );

  Future<Map<String, dynamic>> featureChangeDetail(String featureChangeId) =>
      _detail('app.feature_change.detail', {
        'feature_change_id': featureChangeId,
      });

  // -------- capability registry (T086 — Phase 4 US2)
  //
  // FR-071 master-class lookup. Returns the set of capabilities the
  // daemon treats as master-eligible. Cached client-side per session
  // (see master_qualification.dart).

  Future<Map<String, dynamic>> capabilityRegistry() async {
    final env = await session.call('app.capability.registry');
    return _unwrapResult(env);
  }

  // -------- handoff (T101 — Phase 5 US3)
  //
  // Per contracts/app-methods-consumed.md §4 these are anticipated v1.x
  // additions to FEAT-011. If absent at runtime, calls surface as
  // FailureEnvelope and the handoff surfaces degrade per FR-002.

  Future<PagedResult> handoffList({
    String? cursorNext,
    int? limit,
    String? projectId,
    String? targetMasterAgentId,
    String? featureChangeId,
    String? assignmentState,
    String? createdAfter,
    String? createdBefore,
  }) =>
      _list(
        'app.handoff.list',
        cursorNext: cursorNext,
        limit: limit,
        extra: {
          if (projectId != null) 'project_id': projectId,
          if (targetMasterAgentId != null)
            'target_master_agent_id': targetMasterAgentId,
          if (featureChangeId != null) 'feature_change_id': featureChangeId,
          if (assignmentState != null) 'assignment_state': assignmentState,
          if (createdAfter != null) 'created_after': createdAfter,
          if (createdBefore != null) 'created_before': createdBefore,
        },
      );

  Future<Map<String, dynamic>> handoffDetail(String handoffId) =>
      _detail('app.handoff.detail', {'handoff_id': handoffId});

  /// `app.handoff.preview` — FR-040 dry-run. Returns the rendered
  /// prompt + resolved work items without persisting anything. The
  /// preview surface (T107) uses this to satisfy SC-004 (preview
  /// resolved list matches submitted prompt byte-for-byte).
  Future<Map<String, dynamic>> handoffPreview({
    required Map<String, dynamic> draft,
  }) async {
    final env = await session.call(
      'app.handoff.preview',
      params: {'draft': draft},
    );
    return _unwrapResult(env);
  }

  /// `app.handoff.submit` — durable persist + queue-delivery initiation
  /// (FR-042 / FR-043). Returns the new Handoff row (post-id-assignment).
  /// On submission failure the daemon returns a FailureEnvelope; the
  /// caller is expected to attach the failure to the draft per FR-072(a).
  Future<Map<String, dynamic>> handoffSubmit({
    required Map<String, dynamic> draft,
    String? idempotencyKey,
  }) async {
    final env = await session.call(
      'app.handoff.submit',
      params: {
        'draft': draft,
        'idempotency_key': idempotencyKey ?? MutationKeys.fresh(),
      },
    );
    return _unwrapRow(env);
  }

  /// `app.handoff.cancel` — operator-initiated cancellation. Allowed
  /// from `submitted` / `accepted` / `active` / `waiting` / `blocked`
  /// per FR-044.
  Future<Map<String, dynamic>> handoffCancel({
    required String handoffId,
    String? reason,
    String? idempotencyKey,
  }) async {
    final env = await session.call(
      'app.handoff.cancel',
      params: {
        'handoff_id': handoffId,
        if (reason != null) 'reason': reason,
        'idempotency_key': idempotencyKey ?? MutationKeys.fresh(),
      },
    );
    return _unwrapRow(env);
  }

  /// `app.handoff.supersede` — FR-081. The prior handoff transitions
  /// to `superseded`; the daemon stamps `supersededByHandoffId` on the
  /// prior record and `supersedesHandoffId` on the new record. Returns
  /// the new handoff row.
  Future<Map<String, dynamic>> handoffSupersede({
    required String priorHandoffId,
    required Map<String, dynamic> newDraft,
    String? idempotencyKey,
  }) async {
    final env = await session.call(
      'app.handoff.supersede',
      params: {
        'prior_handoff_id': priorHandoffId,
        'new_draft': newDraft,
        'idempotency_key': idempotencyKey ?? MutationKeys.fresh(),
      },
    );
    return _unwrapRow(env);
  }

  /// `app.handoff.retry_delivery` — FR-072(b). Re-queues delivery for
  /// a handoff stuck in `submitted` with delivery-failure status.
  Future<Map<String, dynamic>> handoffRetryDelivery({
    required String handoffId,
    String? idempotencyKey,
  }) async {
    final env = await session.call(
      'app.handoff.retry_delivery',
      params: {
        'handoff_id': handoffId,
        'idempotency_key': idempotencyKey ?? MutationKeys.fresh(),
      },
    );
    return _unwrapRow(env);
  }

  // -------- drift (T114 — Phase 6 US4)

  Future<PagedResult> driftList({
    String? cursorNext,
    int? limit,
    String? projectId,
    String? status,
    String? severity,
  }) =>
      _list(
        'app.drift.list',
        cursorNext: cursorNext,
        limit: limit,
        extra: {
          if (projectId != null) 'project_id': projectId,
          if (status != null) 'status': status,
          if (severity != null) 'severity': severity,
        },
      );

  Future<Map<String, dynamic>> driftDetail(String findingId) =>
      _detail('app.drift.detail', {'finding_id': findingId});

  /// `app.drift.transition` — operator-driven lifecycle transition.
  /// The daemon enforces FR-034 legal transitions server-side; the
  /// client validates pre-flight via DriftStateValidator (T040) so
  /// an illegal click is rejected with an inline explanation rather
  /// than a round-trip error.
  Future<Map<String, dynamic>> driftTransition({
    required String findingId,
    required String toStatus,
    String? operatorNote,
    String? idempotencyKey,
  }) async {
    final env = await session.call(
      'app.drift.transition',
      params: {
        'finding_id': findingId,
        'to_status': toStatus,
        if (operatorNote != null) 'operator_note': operatorNote,
        'idempotency_key': idempotencyKey ?? MutationKeys.fresh(),
      },
    );
    return _unwrapRow(env);
  }

  // -------- validation (T123 — Phase 7 US5)
  //
  // Per FR-049 the app NEVER executes runners locally: trigger +
  // cancel go through the daemon, which owns the subprocess
  // lifecycle. List/detail/demo-readiness are read-only.

  Future<PagedResult> validationEntrypointList({
    String? cursorNext,
    int? limit,
    String? projectId,
    String? scopeKind,
    bool? enabled,
  }) =>
      _list(
        'app.validation.entrypoint.list',
        cursorNext: cursorNext,
        limit: limit,
        extra: {
          if (projectId != null) 'project_id': projectId,
          if (scopeKind != null) 'scope_kind': scopeKind,
          if (enabled != null) 'enabled': enabled,
        },
      );

  Future<Map<String, dynamic>> validationEntrypointDetail(
    String entrypointId,
  ) =>
      _detail(
        'app.validation.entrypoint.detail',
        {'entrypoint_id': entrypointId},
      );

  Future<PagedResult> validationRunList({
    String? cursorNext,
    int? limit,
    String? projectId,
    String? entrypointId,
    String? state,
    String? branch,
  }) =>
      _list(
        'app.validation.run.list',
        cursorNext: cursorNext,
        limit: limit,
        extra: {
          if (projectId != null) 'project_id': projectId,
          if (entrypointId != null) 'entrypoint_id': entrypointId,
          if (state != null) 'state': state,
          if (branch != null) 'branch': branch,
        },
      );

  Future<Map<String, dynamic>> validationRunDetail(String runId) =>
      _detail('app.validation.run.detail', {'run_id': runId});

  /// `app.validation.run.trigger` — FR-049. Returns the new run row
  /// (initially in `queued` state). SC-006 requires the daemon to
  /// transition to `running` within ≤ 2 s — that's the daemon's
  /// invariant, not the app's, but the UI polls the run-list to
  /// surface the transition.
  Future<Map<String, dynamic>> validationRunTrigger({
    required String entrypointId,
    required String targetKind,
    required String targetId,
    String? idempotencyKey,
  }) async {
    final env = await session.call(
      'app.validation.run.trigger',
      params: {
        'entrypoint_id': entrypointId,
        'target': {'kind': targetKind, 'id': targetId},
        'idempotency_key': idempotencyKey ?? MutationKeys.fresh(),
      },
    );
    return _unwrapRow(env);
  }

  /// `app.validation.run.cancel` — FR-049 cancel half. Legal only
  /// from `queued` / `running` per FR-048. Daemon enforces; the app
  /// pre-checks via ValidationRunStateValidator.
  Future<Map<String, dynamic>> validationRunCancel({
    required String runId,
    String? reason,
    String? idempotencyKey,
  }) async {
    final env = await session.call(
      'app.validation.run.cancel',
      params: {
        'run_id': runId,
        if (reason != null) 'reason': reason,
        'idempotency_key': idempotencyKey ?? MutationKeys.fresh(),
      },
    );
    return _unwrapRow(env);
  }

  Future<Map<String, dynamic>> demoReadinessDetail({
    required String projectId,
    required String branch,
  }) async {
    final env = await session.call(
      'app.demo_readiness.detail',
      params: {'project_id': projectId, 'branch': branch},
    );
    return _unwrapRow(env);
  }

  // -------- attention + notifications + operator history (T134 — Phase 8 US6)

  Future<PagedResult> attentionList({
    String? cursorNext,
    int? limit,
    String? projectId,
    String? severity,
    String? attentionClass,
  }) =>
      _list(
        'app.attention.list',
        cursorNext: cursorNext,
        limit: limit,
        extra: {
          if (projectId != null) 'project_id': projectId,
          if (severity != null) 'severity': severity,
          if (attentionClass != null) 'attention_class': attentionClass,
        },
      );

  Future<Map<String, dynamic>> attentionDetail(String attentionId) =>
      _detail('app.attention.detail', {'attention_id': attentionId});

  Future<PagedResult> notificationList({
    String? cursorNext,
    int? limit,
    String? projectId,
    String? severity,
    String? lifecycle,
  }) =>
      _list(
        'app.notification.list',
        cursorNext: cursorNext,
        limit: limit,
        extra: {
          if (projectId != null) 'project_id': projectId,
          if (severity != null) 'severity': severity,
          if (lifecycle != null) 'lifecycle': lifecycle,
        },
      );

  Future<PagedResult> notificationHistory({
    String? cursorNext,
    int? limit,
    String? projectId,
  }) =>
      _list(
        'app.notification.history',
        cursorNext: cursorNext,
        limit: limit,
        extra: {if (projectId != null) 'project_id': projectId},
      );

  Future<Map<String, dynamic>> notificationAcknowledge({
    required String notificationId,
    String? idempotencyKey,
  }) async {
    final env = await session.call(
      'app.notification.acknowledge',
      params: {
        'notification_id': notificationId,
        'idempotency_key': idempotencyKey ?? MutationKeys.fresh(),
      },
    );
    return _unwrapRow(env);
  }

  Future<PagedResult> operatorHistoryList({
    String? cursorNext,
    int? limit,
    String? parentAgentId,
  }) =>
      _list(
        'app.operator_history.list',
        cursorNext: cursorNext,
        limit: limit,
        extra: {if (parentAgentId != null) 'parent_agent_id': parentAgentId},
      );

  // -------- helper policies (T101 — Phase 5 US3, per FR-038a + R-19)

  /// `app.helper_policies.list` — enumerates available policies for
  /// the handoff-flow policy picker.
  Future<PagedResult> helperPolicyList({String? cursorNext, int? limit}) =>
      _list('app.helper_policies.list', cursorNext: cursorNext, limit: limit);

  /// `app.helper_policies.resolve` — returns the snapshot a handoff
  /// would embed if submitted now (with the optional operator
  /// override applied). Daemon-side resolution honors FR-038a sources
  /// (baked default → operator override → repo override).
  Future<Map<String, dynamic>> helperPolicyResolve({
    required String projectId,
    String? operatorOverrideOfPolicyId,
  }) async {
    final env = await session.call(
      'app.helper_policies.resolve',
      params: {
        'project_id': projectId,
        if (operatorOverrideOfPolicyId != null)
          'operator_override_of_policy_id': operatorOverrideOfPolicyId,
      },
    );
    return _unwrapResult(env);
  }

  // ================================================================ Mutations

  // -------- agent

  /// `app.agent.register_from_pane` — adopt-existing-pane (FR-016, FR-028a).
  /// All 6 pane-identity fields are required and MUST match the
  /// daemon's discovered-pane row byte-for-byte; any single-field
  /// mismatch returns `pane_not_found.details.mismatch_field`. On
  /// success the daemon returns the freshly-registered agent shape
  /// (already unwrapped from `row` by this client) usable by
  /// `AdoptedAgent.fromJson`.
  Future<Map<String, dynamic>> agentRegisterFromPane({
    required String paneId,
    required String containerId,
    required String tmuxSocket,
    required String sessionName,
    required int windowIndex,
    required int paneIndex,
    required String label,
    required String role,
    required String capability,
    String? projectPath,
    String? parentAgentId,
    bool attachLog = false,
    String? idempotencyKey,
  }) async {
    final env = await session.call(
      'app.agent.register_from_pane',
      params: {
        'container_id': containerId,
        'tmux_socket': tmuxSocket,
        'session_name': sessionName,
        'window_index': windowIndex,
        'pane_index': paneIndex,
        'pane_id': paneId,
        'role': role,
        'capability': capability,
        'label': label,
        if (projectPath != null) 'project_path': projectPath,
        if (parentAgentId != null) 'parent_agent_id': parentAgentId,
        'attach_log': attachLog,
        'idempotency_key': idempotencyKey ?? MutationKeys.fresh(),
      },
    );
    return _unwrapRow(env);
  }

  /// `app.agent.update` — update label/role/capability/project_path on
  /// an adopted agent (FR-015). Per FEAT-011 FR-030a this method
  /// NEVER returns `stale_object`.
  ///
  /// Field semantics per contract §app.agent.update:
  ///   - Absent fields → no change.
  ///   - Empty string on `project_path`/`label` → clears the field.
  ///   - Empty string on `role`/`capability` → `validation_failed`.
  Future<Map<String, dynamic>> agentUpdate({
    required String agentId,
    String? label,
    String? role,
    String? capability,
    String? projectPath,
    String? idempotencyKey,
  }) async {
    final env = await session.call(
      'app.agent.update',
      params: {
        'agent_id': agentId,
        if (label != null) 'label': label,
        if (role != null) 'role': role,
        if (capability != null) 'capability': capability,
        if (projectPath != null) 'project_path': projectPath,
        'idempotency_key': idempotencyKey ?? MutationKeys.fresh(),
      },
    );
    return _unwrapRow(env);
  }

  // -------- log attachment

  Future<Map<String, dynamic>> logAttach({
    required String agentId,
    String? idempotencyKey,
  }) async {
    final env = await session.call(
      'app.log.attach',
      params: {
        'agent_id': agentId,
        'idempotency_key': idempotencyKey ?? MutationKeys.fresh(),
      },
    );
    return _unwrapRow(env);
  }

  Future<Map<String, dynamic>> logDetach({
    required String agentId,
    String? idempotencyKey,
  }) async {
    final env = await session.call(
      'app.log.detach',
      params: {
        'agent_id': agentId,
        'idempotency_key': idempotencyKey ?? MutationKeys.fresh(),
      },
    );
    return _unwrapRow(env);
  }

  // -------- send_input

  /// `app.send_input` — Direct Send (FR-018). Per the contract `payload`
  /// is a structured JSON object that serializes to ≤ 16 KiB; the app
  /// wraps freeform operator prose under `{"text": "..."}` here. The
  /// daemon-side response is a FLAT result (no `row` wrap):
  /// `{message_id, state, deduplicated}`.
  Future<Map<String, dynamic>> sendInput({
    required String targetAgentId,
    required Map<String, dynamic> payload,
    String? idempotencyKey,
  }) async {
    if (payload.isEmpty) {
      throw ArgumentError.value(
        payload,
        'payload',
        'Direct Send requires a non-empty structured payload (FR-018)',
      );
    }
    final env = await session.call(
      'app.send_input',
      params: {
        'target_agent_id': targetAgentId,
        'payload': payload,
        'idempotency_key': idempotencyKey ?? MutationKeys.fresh(),
      },
    );
    return _unwrapResult(env);
  }

  // -------- queue mutations

  /// All three accept `{message_id}` (not `queue_row_id`). `delay`
  /// additionally takes `delay_ms` (not `delay_seconds`); `cancel`
  /// optionally takes `reason`. Returns the post-mutation row.
  Future<Map<String, dynamic>> queueApprove({
    required String messageId,
    String? idempotencyKey,
  }) async {
    final env = await session.call(
      'app.queue.approve',
      params: {
        'message_id': messageId,
        'idempotency_key': idempotencyKey ?? MutationKeys.fresh(),
      },
    );
    return _unwrapRow(env);
  }

  Future<Map<String, dynamic>> queueDelay({
    required String messageId,
    required Duration by,
    String? idempotencyKey,
  }) async {
    final env = await session.call(
      'app.queue.delay',
      params: {
        'message_id': messageId,
        'delay_ms': by.inMilliseconds,
        'idempotency_key': idempotencyKey ?? MutationKeys.fresh(),
      },
    );
    return _unwrapRow(env);
  }

  Future<Map<String, dynamic>> queueCancel({
    required String messageId,
    String? reason,
    String? idempotencyKey,
  }) async {
    final env = await session.call(
      'app.queue.cancel',
      params: {
        'message_id': messageId,
        if (reason != null) 'reason': reason,
        'idempotency_key': idempotencyKey ?? MutationKeys.fresh(),
      },
    );
    return _unwrapRow(env);
  }

  // -------- route mutations

  /// `app.route.add` takes a full FEAT-010 route definition: `source_scope`,
  /// `template`, `target`. The operator-facing prose surfaces in
  /// `add_route_flow.dart` collect these three strings directly.
  Future<Map<String, dynamic>> routeAdd({
    required String sourceScope,
    required String template,
    required String target,
    String? idempotencyKey,
  }) async {
    final env = await session.call(
      'app.route.add',
      params: {
        'source_scope': sourceScope,
        'template': template,
        'target': target,
        'idempotency_key': idempotencyKey ?? MutationKeys.fresh(),
      },
    );
    return _unwrapRow(env);
  }

  Future<Map<String, dynamic>> routeRemove({
    required String routeId,
    String? idempotencyKey,
  }) async {
    final env = await session.call(
      'app.route.remove',
      params: {
        'route_id': routeId,
        'idempotency_key': idempotencyKey ?? MutationKeys.fresh(),
      },
    );
    return _unwrapRow(env);
  }

  /// `app.route.update` accepts ONLY `{route_id, enabled}` at v1.0
  /// (FR-029, FR-032). Other fields are rejected with `validation_failed`.
  Future<Map<String, dynamic>> routeUpdate({
    required String routeId,
    required bool enabled,
    String? idempotencyKey,
  }) async {
    final env = await session.call(
      'app.route.update',
      params: {
        'route_id': routeId,
        'enabled': enabled,
        'idempotency_key': idempotencyKey ?? MutationKeys.fresh(),
      },
    );
    return _unwrapRow(env);
  }

  // -------- scans

  /// `app.scan.containers` — re-probe container set (FR-014). The
  /// contract accepts ONLY `{wait}` — no `container_id` filter at v1.0
  /// (review fix H7).
  Future<Map<String, dynamic>> scanContainers({
    bool wait = false,
    String? idempotencyKey,
  }) =>
      _scanKick(
        'app.scan.containers',
        wait: wait,
        idempotencyKey: idempotencyKey,
      );

  Future<Map<String, dynamic>> scanPanes({
    bool wait = false,
    String? idempotencyKey,
  }) =>
      _scanKick(
        'app.scan.panes',
        wait: wait,
        idempotencyKey: idempotencyKey,
      );

  /// `app.scan.status` returns a FLAT result (no `row` wrap):
  /// `{state, scan_kind, started_at, completed_at?, result?}`.
  Future<Map<String, dynamic>> scanStatus(String scanId) async {
    final env = await session.call(
      'app.scan.status',
      params: {'scan_id': scanId},
    );
    return _unwrapResult(env);
  }

  // ====================================================== Internal plumbing

  Future<PagedResult> _list(
    String method, {
    String? cursorNext,
    int? limit,
    String? orderBy,
    Map<String, dynamic>? extra,
  }) async {
    // Swarm-review CR-3: per FEAT-011 app-methods.md §list-request-shape
    // (line 169-177) filters MUST nest under `filters: {…}`. Previously
    // we splatted `extra` at the top level, which the daemon either
    // dropped silently or rejected as `validation_failed.details.field
    // == "<unknown>"`. The H-E2 add of `order_by` is plumbed here so
    // callers can opt into a non-default sort without a per-call patch.
    final env = await session.call(
      method,
      params: {
        if (cursorNext != null) 'cursor_next': cursorNext,
        if (limit != null) 'limit': limit,
        if (orderBy != null) 'order_by': orderBy,
        if (extra != null && extra.isNotEmpty) 'filters': extra,
      },
    );
    final raw = _unwrapResult(env);
    final rows = (raw['rows'] as List?) ?? const <dynamic>[];
    return PagedResult(
      items: rows.whereType<Map<String, dynamic>>().toList(growable: false),
      cursorNext: raw['cursor_next'] as String?,
      total: raw['total'] as int?,
      totalEstimate: raw['total_estimate'] as int?,
      ordering: raw['ordering'] as String?,
    );
  }

  Future<Map<String, dynamic>> _detail(
    String method,
    Map<String, dynamic> params,
  ) async {
    final env = await session.call(method, params: params);
    return _unwrapRow(env);
  }

  Future<Map<String, dynamic>> _scanKick(
    String method, {
    required bool wait,
    String? idempotencyKey,
  }) async {
    final env = await session.call(
      method,
      params: {
        'wait': wait,
        'idempotency_key': idempotencyKey ?? MutationKeys.fresh(),
      },
    );
    return _unwrapResult(env);
  }

  /// Unwraps a [SuccessEnvelope] to its flat `result` map. Used for
  /// `app.dashboard`, `app.readiness`, `app.send_input`, scan kick/status.
  static Map<String, dynamic> _unwrapResult(Envelope env) {
    return switch (env) {
      SuccessEnvelope(:final result) => result,
      FailureEnvelope(:final error) => throw error,
    };
  }

  /// Unwraps a [SuccessEnvelope] one extra level under `result.row`. Used
  /// for every `.detail` call and every mutation except `send_input` and
  /// `scan.*`.
  static Map<String, dynamic> _unwrapRow(Envelope env) {
    final result = _unwrapResult(env);
    final row = result['row'];
    if (row is! Map<String, dynamic>) {
      throw FormatException(
        'Expected `result.row` to be an object per app-methods.md line 22; '
        'got ${row.runtimeType}',
      );
    }
    return row;
  }
}

/// One page of a `*.list` call. Per contract (`app-methods.md` §app.<entity>.list):
///   - `cursor_next` is opaque, ≤ 512 chars, daemon-chosen encoding
///   - exactly one of `total` / `totalEstimate` is non-null per response
///   - `ordering` echoes the applied `order_by`
class PagedResult {
  const PagedResult({
    required this.items,
    required this.cursorNext,
    this.total,
    this.totalEstimate,
    this.ordering,
  });

  final List<Map<String, dynamic>> items;
  final String? cursorNext;
  final int? total;
  final int? totalEstimate;
  final String? ordering;

  bool get hasMore => cursorNext != null;
}
