import 'dart:convert';

import 'errors.dart';

/// FEAT-011 response-envelope parser. T011 (Phase 2 Foundational).
///
/// FEAT-011 FR-033 envelope shapes:
///   success: { "ok": true,  "app_contract_version": "1.0", "result": {...} }
///   failure: { "ok": false, "app_contract_version": "1.0",
///              "error": { "code": "<closed-set>", "message": "...", "details": {...} } }
///
/// `details` is always an object (may be empty `{}`).
sealed class Envelope {
  const Envelope({required this.appContractVersion});
  final String appContractVersion;

  static Envelope parse(String jsonLine) => fromDecoded(json.decode(jsonLine));

  /// Builds an [Envelope] from an already-decoded JSON value, avoiding a
  /// redundant `json.decode` when the caller has already parsed the line
  /// (e.g. the response dispatcher that decodes once to extract the
  /// correlation `id`). [parse] delegates here.
  static Envelope fromDecoded(Object? raw) {
    if (raw is! Map<String, dynamic>) {
      throw const FormatException('Envelope is not a JSON object');
    }
    final ok = raw['ok'];
    final acv = raw['app_contract_version'];
    if (ok is! bool) {
      throw const FormatException('Envelope missing or non-bool "ok"');
    }
    if (acv is! String) {
      throw const FormatException(
        'Envelope missing or non-string "app_contract_version"',
      );
    }
    // FR-033 fixes the documented "<major>.<minor>" shape (e.g. "1.0"). Validate
    // it here, at the envelope boundary, so a malformed value surfaces as a
    // FormatException alongside other envelope-shape failures rather than as an
    // uncaught throw later in ContractVersion.parse inside an event listener.
    final parts = acv.split('.');
    if (parts.length != 2 ||
        int.tryParse(parts[0]) == null ||
        int.tryParse(parts[1]) == null) {
      throw const FormatException(
        'Envelope "app_contract_version" is not "<major>.<minor>"',
      );
    }
    if (ok) {
      final result = raw['result'];
      if (result is! Map<String, dynamic>) {
        throw const FormatException('Success envelope missing "result" object');
      }
      return SuccessEnvelope(appContractVersion: acv, result: result);
    } else {
      final err = raw['error'];
      if (err is! Map<String, dynamic>) {
        throw const FormatException('Failure envelope missing "error" object');
      }
      return FailureEnvelope(
        appContractVersion: acv,
        error: AppContractError.fromJson(err),
      );
    }
  }
}

class SuccessEnvelope extends Envelope {
  const SuccessEnvelope({
    required super.appContractVersion,
    required this.result,
  });
  final Map<String, dynamic> result;
}

class FailureEnvelope extends Envelope {
  const FailureEnvelope({
    required super.appContractVersion,
    required this.error,
  });
  final AppContractError error;
}
