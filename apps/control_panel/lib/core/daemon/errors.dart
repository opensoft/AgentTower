/// FEAT-011 closed-set error vocabulary (27 codes per FEAT-011 FR-034).
/// T012 (Phase 2 Foundational).
///
/// Two codes have per-surface UI treatment per `contracts/app-methods-consumed.md` §8:
/// - [appContractMajorUnsupported] → triggers FR-002 global banner +
///   per-surface contract-version-incompatible state + disabled mutations
/// - [hostOnly] → should never reach the desktop app (host-only by FR-061);
///   if observed, log + runtime-degraded indicator

enum AppContractErrorCode {
  // Bootstrap / version
  appContractMajorUnsupported('app_contract_major_unsupported'),
  sessionExpired('session_expired'),
  tooManySessions('too_many_sessions'),

  // Connection / framing
  malformedRequest('malformed_request'),
  payloadTooLarge('payload_too_large'),
  hostOnly('host_only'),

  // Method dispatch
  methodNotFound('method_not_found'),
  methodNotImplemented('method_not_implemented'),

  // Validation
  validationFailed('validation_failed'),
  notFound('not_found'),
  conflict('conflict'),

  // Auth / permission
  permissionDenied('permission_denied'),
  forbidden('forbidden'),

  // State guards
  staleObject('stale_object'),
  terminalStateGuard('terminal_state_guard'),
  preconditionFailed('precondition_failed'),

  // Pagination / cursor
  staleCursor('stale_cursor'),
  invalidLimit('invalid_limit'),

  // Subsystem availability
  subsystemUnavailable('subsystem_unavailable'),
  scanInProgress('scan_in_progress'),
  scanNotFound('scan_not_found'),
  scanTimeout('scan_timeout'),
  queueRejected('queue_rejected'),
  routeNotFound('route_not_found'),

  // Generic
  internalError('internal_error'),
  rateLimited('rate_limited'),
  unimplemented('unimplemented');

  const AppContractErrorCode(this.wireValue);
  final String wireValue;

  static AppContractErrorCode fromWire(String v) =>
      values.firstWhere(
        (e) => e.wireValue == v,
        orElse: () => AppContractErrorCode.internalError,
      );

  /// Per `contracts/app-methods-consumed.md` §8 — these codes
  /// drive surface-level UX state changes.
  bool get triggersGlobalBanner => this == appContractMajorUnsupported;
  bool get shouldNeverReachApp => this == hostOnly;
}

/// Parsed FEAT-011 error object.
class AppContractError implements Exception {
  const AppContractError({
    required this.code,
    required this.message,
    required this.details,
  });

  factory AppContractError.fromJson(Map<String, dynamic> json) {
    final codeStr = json['code'] as String? ?? 'internal_error';
    final message = json['message'] as String? ?? '';
    final details = (json['details'] as Map<String, dynamic>?) ?? const {};
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
