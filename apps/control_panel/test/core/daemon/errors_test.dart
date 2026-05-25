import 'package:agenttower_control_panel/core/daemon/errors.dart';
import 'package:flutter_test/flutter_test.dart';

/// Unit tests for [AppContractErrorCode] and [AppContractError].
/// FEAT-011 closed-set error vocabulary (27 codes at app_contract_version 1.0).
///
/// Source of truth: `lib/core/daemon/errors.dart` mirroring
/// `specs/011-app-backend-contract/contracts/error-codes.md`.
void main() {
  // Authoritative wire-string ↔ enum table mirroring errors.dart so any
  // future renumber/rename of the closed set lights up these tests.
  final wireTable = <String, AppContractErrorCode>{
    // Session lifecycle
    'app_session_required': AppContractErrorCode.appSessionRequired,
    'app_session_expired': AppContractErrorCode.appSessionExpired,
    'app_contract_major_unsupported':
        AppContractErrorCode.appContractMajorUnsupported,
    // Method dispatch
    'unknown_method': AppContractErrorCode.unknownMethod,
    // Wire framing
    'malformed_request': AppContractErrorCode.malformedRequest,
    'payload_too_large': AppContractErrorCode.payloadTooLarge,
    // Validation
    'validation_failed': AppContractErrorCode.validationFailed,
    'not_found': AppContractErrorCode.notFound,
    // Queue lifecycle
    'stale_object': AppContractErrorCode.staleObject,
    // Pane adopt
    'pane_already_registered': AppContractErrorCode.paneAlreadyRegistered,
    'pane_not_found': AppContractErrorCode.paneNotFound,
    // Entity-specific not-found
    'agent_not_found': AppContractErrorCode.agentNotFound,
    'route_not_found': AppContractErrorCode.routeNotFound,
    'queue_message_not_found': AppContractErrorCode.queueMessageNotFound,
    // Scans
    'scan_timeout': AppContractErrorCode.scanTimeout,
    'scan_not_found': AppContractErrorCode.scanNotFound,
    // Preflight / subsystem
    'daemon_unavailable': AppContractErrorCode.daemonUnavailable,
    'socket_missing': AppContractErrorCode.socketMissing,
    'socket_permission_denied': AppContractErrorCode.socketPermissionDenied,
    'docker_unavailable': AppContractErrorCode.dockerUnavailable,
    'tmux_unavailable': AppContractErrorCode.tmuxUnavailable,
    // Mutation guards
    'container_inactive': AppContractErrorCode.containerInactive,
    'log_attach_blocked': AppContractErrorCode.logAttachBlocked,
    'routing_disabled': AppContractErrorCode.routingDisabled,
    // Auth / peer
    'permission_denied': AppContractErrorCode.permissionDenied,
    'host_only': AppContractErrorCode.hostOnly,
    // Generic
    'internal_error': AppContractErrorCode.internalError,
  };

  group('AppContractErrorCode — closed-set cardinality', () {
    test('exactly 27 enum values at app_contract_version 1.0', () {
      expect(
        AppContractErrorCode.values.length,
        27,
        reason: 'FEAT-011 v1.0 closed set MUST have exactly 27 codes; '
            'adding/removing is a minor/major bump (FR-034)',
      );
    });

    test('wire-table contains all 27 codes (no enum drift vs test table)', () {
      expect(
        wireTable.length,
        AppContractErrorCode.values.length,
        reason: 'test table must enumerate every enum value',
      );
      for (final code in AppContractErrorCode.values) {
        expect(
          wireTable.values.contains(code),
          isTrue,
          reason: '$code missing from wire-table — update test or enum',
        );
      }
    });

    test('every wire string is unique', () {
      expect(
        wireTable.keys.toSet().length,
        wireTable.keys.length,
        reason: 'wire strings must be unique across the closed set',
      );
    });
  });

  group('AppContractErrorCode.fromWire — round trip', () {
    test('each wire string round-trips to the documented enum value', () {
      wireTable.forEach((wire, code) {
        expect(
          AppContractErrorCode.fromWire(wire),
          code,
          reason: 'wire "$wire" should map to $code',
        );
        expect(
          code.wireValue,
          wire,
          reason: 'enum $code should emit wire "$wire"',
        );
      });
    });
  });

  group('AppContractErrorCode.fromWire — unknown fallback', () {
    test('unknown code maps to internalError (FEAT-011 SC-009)', () {
      expect(
        AppContractErrorCode.fromWire('this_code_does_not_exist'),
        AppContractErrorCode.internalError,
      );
      expect(
        AppContractErrorCode.fromWire(''),
        AppContractErrorCode.internalError,
      );
      expect(
        AppContractErrorCode.fromWire('  app_session_required  '),
        AppContractErrorCode.internalError,
        reason: 'whitespace-padded codes are not normalized — strict match',
      );
      expect(
        AppContractErrorCode.fromWire('APP_SESSION_REQUIRED'),
        AppContractErrorCode.internalError,
        reason: 'case-sensitive — uppercase wire codes do not match',
      );
    });
  });

  group('AppContractErrorCode — surface-treatment flags', () {
    test('only appContractMajorUnsupported triggers the FR-002 global banner',
        () {
      for (final code in AppContractErrorCode.values) {
        expect(
          code.triggersGlobalBanner,
          code == AppContractErrorCode.appContractMajorUnsupported,
          reason:
              'triggersGlobalBanner must be true only for appContractMajorUnsupported (got $code)',
        );
      }
    });

    test('only hostOnly is flagged as should-never-reach-app (FR-061)', () {
      for (final code in AppContractErrorCode.values) {
        expect(
          code.shouldNeverReachApp,
          code == AppContractErrorCode.hostOnly,
          reason:
              'shouldNeverReachApp must be true only for hostOnly (got $code)',
        );
      }
    });
  });

  group('AppContractError.fromJson', () {
    test('parses fully-populated error payload', () {
      final err = AppContractError.fromJson({
        'code': 'validation_failed',
        'message': 'bad input',
        'details': {'field': 'agent_id'},
      });
      expect(err.code, AppContractErrorCode.validationFailed);
      expect(err.message, 'bad input');
      expect(err.details, {'field': 'agent_id'});
    });

    test('defaults missing code to internal_error', () {
      final err = AppContractError.fromJson(<String, dynamic>{
        'message': 'oops',
      });
      expect(err.code, AppContractErrorCode.internalError);
      expect(err.message, 'oops');
      expect(err.details, isEmpty);
    });

    test('defaults missing message to empty string', () {
      final err = AppContractError.fromJson(<String, dynamic>{
        'code': 'not_found',
      });
      expect(err.code, AppContractErrorCode.notFound);
      expect(err.message, '');
    });

    test('defaults missing details to empty map', () {
      final err = AppContractError.fromJson(<String, dynamic>{
        'code': 'not_found',
        'message': 'gone',
      });
      expect(err.details, isEmpty);
    });

    test('unknown wire code in JSON degrades to internalError', () {
      final err = AppContractError.fromJson(<String, dynamic>{
        'code': 'brand_new_code_v1_1',
        'message': 'future',
        'details': <String, dynamic>{},
      });
      expect(err.code, AppContractErrorCode.internalError);
    });

    test('toString includes the wire code + message', () {
      final err = AppContractError.fromJson({
        'code': 'permission_denied',
        'message': 'nope',
        'details': <String, dynamic>{},
      });
      final s = err.toString();
      expect(s, contains('permission_denied'));
      expect(s, contains('nope'));
    });

    test('AppContractError is an Exception', () {
      final err = AppContractError.fromJson({
        'code': 'internal_error',
        'message': 'oops',
        'details': <String, dynamic>{},
      });
      expect(err, isA<Exception>());
    });
  });
}
