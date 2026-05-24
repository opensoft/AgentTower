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
    return _unwrap(env);
  }

  /// `app.dashboard` — Agent Operations Dashboard counts + recents (FR-012).
  /// Returns raw result; Dashboard view (T065) interprets fields.
  Future<Map<String, dynamic>> dashboard({int recentLimit = 10}) async {
    final env = await session.call(
      'app.dashboard',
      params: {'recent_limit': recentLimit},
    );
    return _unwrap(env);
  }

  // ============================================================ Read surfaces

  // -------- container

  Future<PagedResult> containerList({String? cursor, int? limit}) =>
      _list('app.container.list', cursor: cursor, limit: limit);

  Future<Map<String, dynamic>> containerDetail(String containerId) =>
      _detail('app.container.detail', {'container_id': containerId});

  // -------- pane

  Future<PagedResult> paneList({String? cursor, int? limit}) =>
      _list('app.pane.list', cursor: cursor, limit: limit);

  Future<Map<String, dynamic>> paneDetail(String paneId) =>
      _detail('app.pane.detail', {'pane_id': paneId});

  // -------- agent

  Future<PagedResult> agentList({
    String? cursor,
    int? limit,
    String? projectId,
  }) =>
      _list(
        'app.agent.list',
        cursor: cursor,
        limit: limit,
        extra: {if (projectId != null) 'project_id': projectId},
      );

  Future<Map<String, dynamic>> agentDetail(String agentId) =>
      _detail('app.agent.detail', {'agent_id': agentId});

  // -------- log_attachment

  Future<PagedResult> logAttachmentList({String? cursor, int? limit}) =>
      _list('app.log_attachment.list', cursor: cursor, limit: limit);

  Future<Map<String, dynamic>> logAttachmentDetail(String attachmentId) =>
      _detail('app.log_attachment.detail', {
        'log_attachment_id': attachmentId,
      });

  // -------- event

  /// `app.event.list` — observed-at descending per FR-019. Pagination via
  /// cursor; Events view (T072) calls with `cursor=null` to anchor at
  /// the head and uses `next_cursor` to scroll backwards in time.
  Future<PagedResult> eventList({
    String? cursor,
    int? limit,
    String? agentId,
  }) =>
      _list(
        'app.event.list',
        cursor: cursor,
        limit: limit,
        extra: {if (agentId != null) 'agent_id': agentId},
      );

  Future<Map<String, dynamic>> eventDetail(String eventId) =>
      _detail('app.event.detail', {'event_id': eventId});

  // -------- queue

  Future<PagedResult> queueList({String? cursor, int? limit}) =>
      _list('app.queue.list', cursor: cursor, limit: limit);

  Future<Map<String, dynamic>> queueDetail(String queueRowId) =>
      _detail('app.queue.detail', {'queue_row_id': queueRowId});

  // -------- route

  Future<PagedResult> routeList({String? cursor, int? limit}) =>
      _list('app.route.list', cursor: cursor, limit: limit);

  Future<Map<String, dynamic>> routeDetail(String routeId) =>
      _detail('app.route.detail', {'route_id': routeId});

  // ================================================================ Mutations

  // -------- agent

  /// `app.agent.register_from_pane` — adopt-existing-pane (FR-016). On
  /// success the daemon returns the freshly-registered agent shape
  /// usable by [AdoptedAgent.fromJson].
  Future<Map<String, dynamic>> agentRegisterFromPane({
    required String paneId,
    required String label,
    required String role,
    required String capability,
    required String projectPath,
    bool attachLogNow = true,
    String? idempotencyKey,
  }) async {
    final env = await session.call(
      'app.agent.register_from_pane',
      params: {
        'pane_id': paneId,
        'label': label,
        'role': role,
        'capability': capability,
        'project_path': projectPath,
        'attach_log_now': attachLogNow,
        'idempotency_key': idempotencyKey ?? MutationKeys.fresh(),
      },
    );
    return _unwrap(env);
  }

  /// `app.agent.update` — update label/role/capability/project_path on
  /// an adopted agent (FR-015). Per FEAT-011 FR-030a this method
  /// NEVER returns `stale_object`.
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
    return _unwrap(env);
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
    return _unwrap(env);
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
    return _unwrap(env);
  }

  // -------- send_input

  /// `app.send_input` — Direct Send (FR-018). Per FEAT-011 FR-031a the
  /// `idempotency_key` is optional but the FEAT-012 app always sends
  /// one so retries of the same logical send aren't double-delivered.
  Future<Map<String, dynamic>> sendInput({
    required String targetAgentId,
    required String payload,
    String? routeHint,
    String? idempotencyKey,
  }) async {
    if (payload.isEmpty) {
      throw ArgumentError.value(payload, 'payload', 'Direct Send requires a non-empty payload (FR-018)');
    }
    final env = await session.call(
      'app.send_input',
      params: {
        'target_agent_id': targetAgentId,
        'payload': payload,
        if (routeHint != null) 'route_hint': routeHint,
        'idempotency_key': idempotencyKey ?? MutationKeys.fresh(),
      },
    );
    return _unwrap(env);
  }

  // -------- queue mutations

  Future<Map<String, dynamic>> queueApprove({
    required String queueRowId,
    String? idempotencyKey,
  }) =>
      _queueAction('app.queue.approve', queueRowId, idempotencyKey);

  Future<Map<String, dynamic>> queueDelay({
    required String queueRowId,
    required Duration by,
    String? idempotencyKey,
  }) async {
    final env = await session.call(
      'app.queue.delay',
      params: {
        'queue_row_id': queueRowId,
        'delay_seconds': by.inSeconds,
        'idempotency_key': idempotencyKey ?? MutationKeys.fresh(),
      },
    );
    return _unwrap(env);
  }

  Future<Map<String, dynamic>> queueCancel({
    required String queueRowId,
    String? idempotencyKey,
  }) =>
      _queueAction('app.queue.cancel', queueRowId, idempotencyKey);

  // -------- route mutations

  Future<Map<String, dynamic>> routeAdd({
    required String sourceScope,
    required String eventClass,
    required String targetRule,
    required String masterRule,
    bool enabled = true,
    String? idempotencyKey,
  }) async {
    final env = await session.call(
      'app.route.add',
      params: {
        'source_scope': sourceScope,
        'event_class': eventClass,
        'target_rule': targetRule,
        'master_rule': masterRule,
        'enabled': enabled,
        'idempotency_key': idempotencyKey ?? MutationKeys.fresh(),
      },
    );
    return _unwrap(env);
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
    return _unwrap(env);
  }

  Future<Map<String, dynamic>> routeUpdate({
    required String routeId,
    bool? enabled,
    String? idempotencyKey,
  }) async {
    final env = await session.call(
      'app.route.update',
      params: {
        'route_id': routeId,
        if (enabled != null) 'enabled': enabled,
        'idempotency_key': idempotencyKey ?? MutationKeys.fresh(),
      },
    );
    return _unwrap(env);
  }

  // -------- scans

  /// `app.scan.containers` — re-probe container state (FR-014). On
  /// success returns the daemon's scan-id so the Panes view can poll
  /// [scanStatus].
  Future<Map<String, dynamic>> scanContainers({
    bool wait = false,
    Duration? waitTimeout,
    String? idempotencyKey,
  }) =>
      _scanKick(
        'app.scan.containers',
        wait: wait,
        waitTimeout: waitTimeout,
        idempotencyKey: idempotencyKey,
      );

  Future<Map<String, dynamic>> scanPanes({
    String? containerId,
    bool wait = false,
    Duration? waitTimeout,
    String? idempotencyKey,
  }) async {
    final env = await session.call(
      'app.scan.panes',
      params: {
        if (containerId != null) 'container_id': containerId,
        'wait': wait,
        if (waitTimeout != null) 'wait_timeout_seconds': waitTimeout.inSeconds,
        'idempotency_key': idempotencyKey ?? MutationKeys.fresh(),
      },
    );
    return _unwrap(env);
  }

  Future<Map<String, dynamic>> scanStatus(String scanId) =>
      _detail('app.scan.status', {'scan_id': scanId});

  // ====================================================== Internal plumbing

  Future<PagedResult> _list(
    String method, {
    String? cursor,
    int? limit,
    Map<String, dynamic>? extra,
  }) async {
    final env = await session.call(
      method,
      params: {
        if (cursor != null) 'cursor': cursor,
        if (limit != null) 'limit': limit,
        ...?extra,
      },
    );
    final raw = _unwrap(env);
    final items = (raw['items'] as List?) ?? const [];
    return PagedResult(
      items: items
          .whereType<Map<String, dynamic>>()
          .toList(growable: false),
      nextCursor: raw['next_cursor'] as String?,
    );
  }

  Future<Map<String, dynamic>> _detail(
    String method,
    Map<String, dynamic> params,
  ) async {
    final env = await session.call(method, params: params);
    return _unwrap(env);
  }

  Future<Map<String, dynamic>> _queueAction(
    String method,
    String queueRowId,
    String? idempotencyKey,
  ) async {
    final env = await session.call(
      method,
      params: {
        'queue_row_id': queueRowId,
        'idempotency_key': idempotencyKey ?? MutationKeys.fresh(),
      },
    );
    return _unwrap(env);
  }

  Future<Map<String, dynamic>> _scanKick(
    String method, {
    required bool wait,
    Duration? waitTimeout,
    String? idempotencyKey,
  }) async {
    final env = await session.call(
      method,
      params: {
        'wait': wait,
        if (waitTimeout != null) 'wait_timeout_seconds': waitTimeout.inSeconds,
        'idempotency_key': idempotencyKey ?? MutationKeys.fresh(),
      },
    );
    return _unwrap(env);
  }

  /// Unwraps a [SuccessEnvelope] to its result. Throws [AppContractError]
  /// on [FailureEnvelope]. Caller may catch the error to drive surface-level
  /// degradation (FR-002, FR-072).
  static Map<String, dynamic> _unwrap(Envelope env) {
    return switch (env) {
      SuccessEnvelope(:final result) => result,
      FailureEnvelope(:final error) => throw error,
    };
  }
}

/// One page of a `*.list` call: items + opaque cursor for the next page.
/// Per FEAT-011 FR-020a the daemon caps page size at 50; the app never
/// asks for more.
class PagedResult {
  const PagedResult({required this.items, required this.nextCursor});

  final List<Map<String, dynamic>> items;
  final String? nextCursor;

  bool get hasMore => nextCursor != null;
}
