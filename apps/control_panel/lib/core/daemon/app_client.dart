import 'dart:async';

import 'envelope.dart';
import 'errors.dart';
import 'session.dart';

/// Typed wrappers around the bootstrap-level FEAT-011 `app.*` methods.
/// T014 (Phase 2 Foundational).
///
/// Per-story method wrappers (app.container.list, app.agent.register_from_pane,
/// app.handoff.submit, etc.) land in their respective US phase tasks
/// (T063-T064 US1, T085 US2, T101 US3, T114 US4, T123 US5, T134 US6).
///
/// All write surfaces auto-generate an `idempotency_key` (uuid v4) per
/// Round-3 R-28; helpers for that live in `mutation_keys.dart` (T028
/// dependency, added when first US-phase mutation lands).
///
/// `app.preflight` is intentionally NOT exposed here: it does not require
/// a session token and must be callable BEFORE bootstrap (see review
/// finding A4). Use [PreflightClient] from `preflight_client.dart`
/// instead; the Doctor surface (T026/T143) consumes it directly via
/// `preflightClientProvider`.
class AppClient {
  AppClient({required this.session});

  final DaemonSession session;

  /// `app.readiness` — per-subsystem readiness probe (FR-022).
  /// Returns raw result; Health view (T076) interprets fields.
  Future<Map<String, dynamic>> readiness() async {
    final env = await session.call('app.readiness');
    return _unwrap(env);
  }

  /// `app.dashboard` — Agent Operations Dashboard counts + recents (FR-012).
  /// Returns raw result; Dashboard view (T065) interprets fields.
  Future<Map<String, dynamic>> dashboard() async {
    final env = await session.call('app.dashboard');
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
