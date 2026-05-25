import 'dart:convert';

import 'package:agenttower_control_panel/core/daemon/envelope.dart';
import 'package:agenttower_control_panel/core/daemon/errors.dart';
import 'package:flutter_test/flutter_test.dart';

/// Unit tests for [Envelope.parse]. FEAT-011 FR-033 envelope shapes
/// (success / failure) plus FR-003a/b malformed-input handling.
///
/// Success: { "ok": true,  "app_contract_version": "1.0", "result": {...} }
/// Failure: { "ok": false, "app_contract_version": "1.0",
///            "error":  { "code": "&lt;closed-set&gt;", "message": "...",
///                        "details": {...} } }
void main() {
  group('Envelope.parse — well-formed', () {
    test('success envelope with empty result', () {
      final raw = jsonEncode({
        'ok': true,
        'app_contract_version': '1.0',
        'result': <String, dynamic>{},
      });
      final env = Envelope.parse(raw);
      expect(env, isA<SuccessEnvelope>());
      final s = env as SuccessEnvelope;
      expect(s.appContractVersion, '1.0');
      expect(s.result, isEmpty);
    });

    test('success envelope with populated result preserves nested types', () {
      final raw = jsonEncode({
        'ok': true,
        'app_contract_version': '1.0',
        'result': {
          'row': {'id': 'pane-1', 'state': 'discovered-and-registered'},
          'count': 7,
        },
      });
      final env = Envelope.parse(raw) as SuccessEnvelope;
      expect(env.appContractVersion, '1.0');
      expect(env.result['count'], 7);
      expect(
        (env.result['row'] as Map)['state'],
        'discovered-and-registered',
      );
    });

    test('failure envelope parses code/message/details', () {
      final raw = jsonEncode({
        'ok': false,
        'app_contract_version': '1.0',
        'error': {
          'code': 'validation_failed',
          'message': 'bad input',
          'details': {'field': 'agent_id'},
        },
      });
      final env = Envelope.parse(raw);
      expect(env, isA<FailureEnvelope>());
      final f = env as FailureEnvelope;
      expect(f.appContractVersion, '1.0');
      expect(f.error.code, AppContractErrorCode.validationFailed);
      expect(f.error.message, 'bad input');
      expect(f.error.details, {'field': 'agent_id'});
    });

    test('failure envelope tolerates missing details by defaulting to {}', () {
      // Per errors.dart line 99 — `details` falls back to const {} if absent.
      final raw = jsonEncode({
        'ok': false,
        'app_contract_version': '1.0',
        'error': {'code': 'not_found', 'message': 'gone'},
      });
      final env = Envelope.parse(raw) as FailureEnvelope;
      expect(env.error.details, isEmpty);
      expect(env.error.code, AppContractErrorCode.notFound);
    });

    test('failure envelope with unknown wire code falls back to internalError',
        () {
      // FEAT-011 SC-009 / errors.dart line 79: unknown codes degrade
      // gracefully to internalError so the app does not crash.
      final raw = jsonEncode({
        'ok': false,
        'app_contract_version': '1.0',
        'error': {
          'code': 'totally_made_up_code_that_should_never_ship',
          'message': 'huh?',
          'details': <String, dynamic>{},
        },
      });
      final env = Envelope.parse(raw) as FailureEnvelope;
      expect(env.error.code, AppContractErrorCode.internalError);
    });
  });

  group('Envelope.parse — malformed JSON', () {
    test('truncated JSON throws FormatException', () {
      expect(
        () => Envelope.parse('{"ok": true, "app_contract_versi'),
        throwsFormatException,
      );
    });

    test('non-JSON garbage throws FormatException', () {
      expect(
        () => Envelope.parse('this is not json at all'),
        throwsFormatException,
      );
    });

    test('empty string throws FormatException', () {
      expect(() => Envelope.parse(''), throwsFormatException);
    });

    test('JSON array (not an object) throws FormatException with our message',
        () {
      expect(
        () => Envelope.parse('[1, 2, 3]'),
        throwsA(isA<FormatException>().having(
          (e) => e.message,
          'message',
          contains('not a JSON object'),
        )),
      );
    });

    test('JSON scalar (not an object) throws FormatException', () {
      expect(() => Envelope.parse('42'), throwsFormatException);
      expect(() => Envelope.parse('"a string"'), throwsFormatException);
      expect(() => Envelope.parse('true'), throwsFormatException);
      expect(() => Envelope.parse('null'), throwsFormatException);
    });
  });

  group('Envelope.parse — missing keys', () {
    test('missing "ok" throws FormatException', () {
      final raw = jsonEncode({
        'app_contract_version': '1.0',
        'result': <String, dynamic>{},
      });
      expect(
        () => Envelope.parse(raw),
        throwsA(isA<FormatException>().having(
          (e) => e.message,
          'message',
          contains('"ok"'),
        )),
      );
    });

    test('missing "app_contract_version" throws FormatException', () {
      final raw = jsonEncode({
        'ok': true,
        'result': <String, dynamic>{},
      });
      expect(
        () => Envelope.parse(raw),
        throwsA(isA<FormatException>().having(
          (e) => e.message,
          'message',
          contains('app_contract_version'),
        )),
      );
    });

    test('success envelope missing "result" throws FormatException', () {
      final raw = jsonEncode({
        'ok': true,
        'app_contract_version': '1.0',
      });
      expect(
        () => Envelope.parse(raw),
        throwsA(isA<FormatException>().having(
          (e) => e.message,
          'message',
          contains('result'),
        )),
      );
    });

    test('failure envelope missing "error" throws FormatException', () {
      final raw = jsonEncode({
        'ok': false,
        'app_contract_version': '1.0',
      });
      expect(
        () => Envelope.parse(raw),
        throwsA(isA<FormatException>().having(
          (e) => e.message,
          'message',
          contains('error'),
        )),
      );
    });
  });

  group('Envelope.parse — mismatched types', () {
    test('"ok" as string is rejected', () {
      final raw = jsonEncode({
        'ok': 'true',
        'app_contract_version': '1.0',
        'result': <String, dynamic>{},
      });
      expect(() => Envelope.parse(raw), throwsFormatException);
    });

    test('"ok" as int is rejected', () {
      final raw = jsonEncode({
        'ok': 1,
        'app_contract_version': '1.0',
        'result': <String, dynamic>{},
      });
      expect(() => Envelope.parse(raw), throwsFormatException);
    });

    test('"app_contract_version" as number is rejected', () {
      final raw = jsonEncode({
        'ok': true,
        'app_contract_version': 1,
        'result': <String, dynamic>{},
      });
      expect(() => Envelope.parse(raw), throwsFormatException);
    });

    test('"result" as array is rejected on success envelope', () {
      final raw = jsonEncode({
        'ok': true,
        'app_contract_version': '1.0',
        'result': [1, 2, 3],
      });
      expect(() => Envelope.parse(raw), throwsFormatException);
    });

    test('"error" as string is rejected on failure envelope', () {
      final raw = jsonEncode({
        'ok': false,
        'app_contract_version': '1.0',
        'error': 'bad',
      });
      expect(() => Envelope.parse(raw), throwsFormatException);
    });
  });

  group('Envelope.parse — oversized lines', () {
    // FR-003a/b — payload size is enforced upstream of the parser (the
    // socket framer rejects > N MB lines). The parser itself MUST still
    // parse very large but well-formed JSON without throwing, so a
    // legitimate large payload (e.g. a 1MB list page) is not lost.
    test('parses a 1MB well-formed success envelope without throwing', () {
      final bigString = 'x' * (1024 * 1024); // 1 MiB
      final raw = jsonEncode({
        'ok': true,
        'app_contract_version': '1.0',
        'result': {'blob': bigString},
      });
      final env = Envelope.parse(raw) as SuccessEnvelope;
      expect((env.result['blob'] as String).length, bigString.length);
    });

    test(
        'oversized payload that is NOT valid JSON still throws FormatException',
        () {
      // Truncated 1MB string — invalid JSON should fail loudly even when
      // big, not silently produce a bogus envelope.
      final raw = '{"ok": true, "app_contract_version": "1.0", "result": '
          '${'x' * (1024 * 1024)}'; // missing closing braces + quotes
      expect(() => Envelope.parse(raw), throwsFormatException);
    });
  });
}
