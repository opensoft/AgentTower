/// FEAT-011 closed-set error vocabulary (27 codes at app_contract_version 1.0).
/// T012 (Phase 2 Foundational).
///
/// Source of truth: `specs/011-app-backend-contract/contracts/error-codes.md`.
/// Adding a new code is an additive minor; removing/renaming a code is a
/// major bump (FR-034). This enum MUST match the closed set entry-for-entry.
///
/// Two codes have per-surface UI treatment per
/// `contracts/app-methods-consumed.md` §8:
/// - [appContractMajorUnsupported] → triggers FR-002 global banner +
///   per-surface contract-version-incompatible state + disabled mutations
/// - [hostOnly] → should never reach the desktop app (host-only by FR-061);
///   if observed, log + runtime-degraded indicator
///
/// Codes prefixed with a daemon subsystem (`docker_unavailable`,
/// `tmux_unavailable`) are surface-degradation hints, not failures of the
/// app itself — see FR-022 / FR-072 for the rendering rules.

enum AppContractErrorCode {
  // Session lifecycle
  appSessionRequired('app_session_required'),
  appSessionExpired('app_session_expired'),
  appContractMajorUnsupported('app_contract_major_unsupported'),

  // Method dispatch
  unknownMethod('unknown_method'),

  // Wire framing (FR-003a/b)
  malformedRequest('malformed_request'),
  payloadTooLarge('payload_too_large'),

  // Validation
  validationFailed('validation_failed'),
  notFound('not_found'),

  // Queue lifecycle (FEAT-009)
  staleObject('stale_object'),

  // Pane adopt
  paneAlreadyRegistered('pane_already_registered'),
  paneNotFound('pane_not_found'),

  // Entity-specific not-found
  agentNotFound('agent_not_found'),
  routeNotFound('route_not_found'),
  queueMessageNotFound('queue_message_not_found'),

  // Scans
  scanTimeout('scan_timeout'),
  scanNotFound('scan_not_found'),

  // Preflight / subsystem diagnostics
  daemonUnavailable('daemon_unavailable'),
  socketMissing('socket_missing'),
  socketPermissionDenied('socket_permission_denied'),
  dockerUnavailable('docker_unavailable'),
  tmuxUnavailable('tmux_unavailable'),

  // Mutation guards
  containerInactive('container_inactive'),
  logAttachBlocked('log_attach_blocked'),
  routingDisabled('routing_disabled'),

  // Auth / peer
  permissionDenied('permission_denied'),
  hostOnly('host_only'),

  // Generic
  internalError('internal_error');

  const AppContractErrorCode(this.wireValue);
  final String wireValue;

  /// Resolves a wire string to its enum variant. Unknown codes (added in a
  /// future minor) map to [internalError] so the app degrades gracefully
  /// per SC-009 instead of crashing.
  static AppContractErrorCode fromWire(String v) => values.firstWhere(
        (e) => e.wireValue == v,
        orElse: () => AppContractErrorCode.internalError,
      );

  /// Per `contracts/app-methods-consumed.md` §8 — these codes
  /// drive surface-level UX state changes.
  bool get triggersGlobalBanner => this == appContractMajorUnsupported;
  bool get shouldNeverReachApp => this == hostOnly;
}

/// Sentinel error completion for any in-flight `AppClient.*` future that
/// was waiting on a response from a [SocketClient] that was deliberately
/// torn down (e.g. by [DaemonSession.reBootstrap]). Distinguishable from
/// a generic [StateError] so callers can decide whether to surface a
/// "connection was reset, please retry" affordance vs. treat as a bug.
///
/// Per T174(a) pending-request semantics: any future returned by
/// `AppClient.*` that was in-flight at the moment of `reBootstrap()`
/// MUST complete with this error. The new session does NOT silently
/// retry the request — the caller's `idempotency_key` may or may not
/// be replayable, that's a caller decision.
class SocketDisconnectedError implements Exception {
  const SocketDisconnectedError([this.reason]);

  final String? reason;

  @override
  String toString() => reason == null
      ? 'SocketDisconnectedError: in-flight request aborted by session teardown'
      : 'SocketDisconnectedError: $reason';
}

/// Parsed FEAT-011 error object.
class AppContractError implements Exception {
  const AppContractError({
    required this.code,
    required this.message,
    required this.details,
  });

  factory AppContractError.fromJson(Map<String, dynamic> json) {
    final codeRaw = json['code'];
    final codeStr = codeRaw is String ? codeRaw : 'internal_error';
    final msgRaw = json['message'];
    final message = msgRaw is String ? msgRaw : '';
    final detailsRaw = json['details'];
    final details =
        detailsRaw is Map<String, dynamic> ? detailsRaw : const <String, dynamic>{};
    return AppContractError(
      code: AppContractErrorCode.fromWire(codeStr),
      message: message,
      details: details,
    );
  }

  final AppContractErrorCode code;
  final String message;
  final Map<String, dynamic> details;

  @override
  String toString() => 'AppContractError(${code.wireValue}): $message';
}
