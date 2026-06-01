import 'dart:async';
import 'dart:convert';

import 'envelope.dart';
import 'errors.dart';
import 'preflight_client.dart' show StreamQueue;
import 'socket_client.dart';

/// Daemon session lifecycle. T013 (Phase 2 Foundational).
///
/// **Transport model (FEAT-011 FR-008 / FR-026): one request per connection.**
/// The daemon reads one newline-delimited JSON line, dispatches, writes one
/// response line, and **closes the connection**. There is no persistent
/// socket, no response multiplexing, and **no correlation `id`** — the wire
/// envelope is exactly `{ok, app_contract_version, result|error}`. So each
/// round-trip ([bootstrap]'s `app.hello` and every [call]) opens its own
/// fresh [SocketClient], sends one line, reads exactly one line, and closes —
/// the same one-shot pattern [PreflightClient] uses.
///
/// `app.hello` issues an `app_session_token` (held in memory only — FR-003,
/// MUST NOT persist) which is replayed on each subsequent fresh-connection
/// `app.*` call (FR-008a). Token lifetime = process lifetime (Round-3 R-30).
///
/// Lifecycle events are surfaced via [events] so cross-cutting watchers — the
/// runtime-state provider (FR-004), the FR-002 banner, the logger — react
/// without coupling to call sites. A transport failure (connect/timeout/
/// framing) on `app.hello` OR any `call` emits [SessionFailed]; a normal
/// `FailureEnvelope` (the daemon answered with a closed-set error code) is a
/// *successful* round-trip and is returned, not treated as a session failure.
sealed class SessionEvent {
  const SessionEvent();
}

class SessionBootstrapped extends SessionEvent {
  const SessionBootstrapped({
    required this.appContractVersion,
    required this.daemonVersion,
  });
  final String appContractVersion;
  final String daemonVersion;
}

class SessionTornDown extends SessionEvent {
  const SessionTornDown({this.reason});
  final Object? reason;
}

class SessionFailed extends SessionEvent {
  const SessionFailed(this.error);
  final Object error;
}

/// Emitted by [DaemonSession.reBootstrap] (T174a) after the in-memory token
/// is discarded and a fresh `app.hello` round-trip completes. Dependent
/// providers (`runtimeStateProvider`, `dashboardProvider`, …) listen for
/// this to invalidate stale per-session state.
class SessionReBootstrapped extends SessionEvent {
  const SessionReBootstrapped({
    required this.appContractVersion,
    required this.daemonVersion,
  });
  final String appContractVersion;
  final String daemonVersion;
}

class DaemonSession {
  /// The [client] is used only for its [SocketClient.socketPath]; this session
  /// does NOT hold a persistent connection (one-request-per-connection model).
  /// A fresh [SocketClient] is opened for every round-trip.
  DaemonSession({required SocketClient client})
      : _socketPath = client.socketPath;

  final String _socketPath;

  String? _sessionToken;
  String? _appContractVersion;
  String? _daemonVersion;
  final _events = StreamController<SessionEvent>.broadcast();

  /// Broadcast stream of session-lifecycle events. Multiple subscribers OK.
  Stream<SessionEvent> get events => _events.stream;

  /// True once `app.hello` has succeeded and a token is held. There is no
  /// persistent socket to be "connected" — readiness is purely token state.
  bool get isReady => _sessionToken != null;

  String? get sessionToken => _sessionToken;
  String? get appContractVersion => _appContractVersion;
  String? get daemonVersion => _daemonVersion;

  /// The configured daemon socket path (used by tests / diagnostics).
  String get socketPath => _socketPath;

  /// One-request-per-connection round-trip (FR-008 / FR-026): open a fresh
  /// connection, send one line, read exactly one response line, close.
  /// Throws on transport failure (connect / timeout / framing); returns the
  /// parsed [Envelope] (success OR closed-set failure) otherwise.
  Future<Envelope> _roundTrip(
    Map<String, dynamic> request,
    Duration timeout,
  ) async {
    final client = SocketClient(_socketPath);
    final responses = StreamQueue<String>(client.responses);
    try {
      await client.connect();
      await client.sendLine(json.encode(request));
      final line = await responses.next.timeout(timeout);
      return Envelope.parse(line);
    } finally {
      await responses.cancel(immediate: true);
      await client.close();
    }
  }

  /// Performs the `app.hello` handshake and captures the session token.
  /// Per FEAT-011 contracts/app-methods.md §app.hello the request carries
  /// `client_id` + `client_app_contract_major`. Emits [SessionBootstrapped]
  /// on success; [SessionFailed] + throws on transport failure or a
  /// `FailureEnvelope`.
  Future<void> bootstrap() async {
    final Envelope env;
    try {
      env = await _roundTrip(
        {
          'method': 'app.hello',
          'params': {
            'client_id': 'agenttower-control-panel',
            'client_app_contract_major': 1,
          },
        },
        const Duration(seconds: 5),
      );
    } catch (e) {
      _events.add(SessionFailed(e));
      rethrow;
    }

    switch (env) {
      case SuccessEnvelope(:final result, :final appContractVersion):
        _sessionToken = result['app_session_token'] as String?;
        _appContractVersion = appContractVersion;
        _daemonVersion = result['daemon_version'] as String?;
        if (_sessionToken == null) {
          const err = FormatException(
            'app.hello response missing app_session_token',
          );
          _events.add(const SessionFailed(err));
          throw err;
        }
        _events.add(SessionBootstrapped(
          appContractVersion: appContractVersion,
          daemonVersion: _daemonVersion ?? 'unknown',
        ));
      case FailureEnvelope(:final error):
        if (error.code == AppContractErrorCode.appContractMajorUnsupported) {
          // Don't throw away the version — let the FR-002 banner drive UX.
          _appContractVersion = env.appContractVersion;
        }
        _events.add(SessionFailed(error));
        throw error;
    }
  }

  /// Sends a typed `app.*` call on its own fresh connection, replaying the
  /// session token (FR-008a). Returns the parsed envelope; the caller
  /// narrows [SuccessEnvelope] vs [FailureEnvelope]. A transport failure
  /// emits [SessionFailed] (so the runtime-state provider flips to
  /// unreachable, FR-004) and rethrows; a closed-set [FailureEnvelope] is
  /// returned normally (it is a successful round-trip).
  Future<Envelope> call(
    String method, {
    Map<String, dynamic>? params,
    Duration timeout = const Duration(seconds: 10),
  }) async {
    if (!isReady) {
      throw StateError('Session not bootstrapped — call bootstrap() first');
    }
    try {
      return await _roundTrip(
        {
          'method': method,
          // Every method except app.preflight / app.hello requires a valid
          // app_session_token (contracts/app-methods.md).
          'app_session_token': _sessionToken,
          if (params != null) 'params': params,
        },
        timeout,
      );
    } catch (e) {
      // Transport failure (connect/timeout/framing) — the daemon is
      // unreachable. Surface it so FR-004 runtime state flips.
      _events.add(SessionFailed(e));
      rethrow;
    }
  }

  /// "Retry connection" (T174a) — discard the in-memory token and re-issue
  /// `app.hello`, then emit [SessionReBootstrapped]. In the one-request-per-
  /// connection model there is no persistent socket to close and no in-flight
  /// request to abort (each round-trip is self-contained), so this reduces to
  /// a token wipe + a fresh handshake. Re-throws any [bootstrap] error.
  Future<void> reBootstrap() async {
    _sessionToken = null;
    _appContractVersion = null;
    _daemonVersion = null;
    // bootstrap() emits [SessionBootstrapped] internally — the runtime-state
    // provider keys off that to move from runtimeUnreachable back to healthy.
    await bootstrap();
    _events.add(
      SessionReBootstrapped(
        appContractVersion: _appContractVersion ?? 'unknown',
        daemonVersion: _daemonVersion ?? 'unknown',
      ),
    );
  }

  /// Discards in-memory session state (token per FR-003) and emits
  /// [SessionTornDown]. No socket to close in the one-shot model.
  Future<void> teardown({Object? reason}) async {
    _sessionToken = null;
    _appContractVersion = null;
    _daemonVersion = null;
    _events.add(SessionTornDown(reason: reason));
  }

  /// Releases the broadcast event stream. Call once at app shutdown.
  Future<void> dispose() async {
    await teardown();
    await _events.close();
  }
}
