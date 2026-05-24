import 'dart:async';
import 'dart:convert';

import 'envelope.dart';
import 'errors.dart';
import 'socket_client.dart';

/// Daemon session lifecycle. T013 (Phase 2 Foundational).
///
/// On connect: calls `app.hello`, holds the returned session token in memory
/// only (FR-003 — MUST NOT persist), re-bootstraps on any of:
/// - socket close
/// - daemon restart (detected by failed read/write)
/// - contract-version change (detected on subsequent responses)
/// - explicit "Retry connection" affordance (FR-001 / US1 §6)
///
/// Token lifetime = process lifetime only per Round-3 R-30 (no idle-timeout).
///
/// Lifecycle events are surfaced via [events] so cross-cutting watchers
/// — the runtime-state provider (FR-004), the FR-002 global banner, the
/// logger — can react without coupling to bootstrap call sites.
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

class DaemonSession {
  DaemonSession({required this.client});

  final SocketClient client;

  String? _sessionToken;
  String? _appContractVersion;
  String? _daemonVersion;
  int _nextRequestId = 1;
  final _pendingRequests = <int, Completer<Envelope>>{};
  StreamSubscription<String>? _responseSub;
  final _events = StreamController<SessionEvent>.broadcast();

  /// Broadcast stream of session-lifecycle events. Consumers (runtime-state
  /// provider, banner, logger) subscribe via `events.listen(...)` and
  /// drive their own UX from it. Multiple subscribers are supported.
  Stream<SessionEvent> get events => _events.stream;

  /// True iff [bootstrap] has completed successfully and the socket is open.
  bool get isReady =>
      _sessionToken != null && client.isConnected && _responseSub != null;

  String? get sessionToken => _sessionToken;
  String? get appContractVersion => _appContractVersion;
  String? get daemonVersion => _daemonVersion;

  /// Connects + calls `app.hello`. Throws on any error.
  Future<void> bootstrap() async {
    if (!client.isConnected) {
      await client.connect();
    }
    await _responseSub?.cancel();
    _responseSub = client.responses.listen(_onResponse, onError: _onError);

    // Send app.hello — per FEAT-011 contracts/app-methods.md §app.hello,
    // request params include client_id, client_version, and
    // client_app_contract_major (default 1).
    final id = _nextRequestId++;
    final completer = Completer<Envelope>();
    _pendingRequests[id] = completer;
    await client.sendLine(
      json.encode({
        'id': id,
        'method': 'app.hello',
        'params': {
          'client_id': 'agenttower-control-panel',
          'client_app_contract_major': 1,
        },
      }),
    );
    final env = await completer.future.timeout(const Duration(seconds: 5));

    switch (env) {
      case SuccessEnvelope(:final result, :final appContractVersion):
        _sessionToken = result['app_session_token'] as String?;
        _appContractVersion = appContractVersion;
        _daemonVersion = result['daemon_version'] as String?;
        if (_sessionToken == null) {
          final err = const FormatException(
            'app.hello response missing app_session_token',
          );
          _events.add(SessionFailed(err));
          throw err;
        }
        _events.add(SessionBootstrapped(
          appContractVersion: appContractVersion,
          daemonVersion: _daemonVersion ?? 'unknown',
        ));
      case FailureEnvelope(:final error):
        if (error.code == AppContractErrorCode.appContractMajorUnsupported) {
          // Don't throw — let the FR-002 banner surface drive UX.
          _appContractVersion = env.appContractVersion;
        }
        _events.add(SessionFailed(error));
        throw error;
    }
  }

  /// Sends a typed `app.*` call. Returns the parsed envelope.
  /// Caller is responsible for narrowing [SuccessEnvelope] vs
  /// [FailureEnvelope] (e.g. via pattern match).
  Future<Envelope> call(
    String method, {
    Map<String, dynamic>? params,
    Duration timeout = const Duration(seconds: 10),
  }) async {
    if (!isReady) {
      throw StateError('Session not bootstrapped — call bootstrap() first');
    }
    final id = _nextRequestId++;
    final completer = Completer<Envelope>();
    _pendingRequests[id] = completer;
    final payload = <String, dynamic>{
      'id': id,
      'method': method,
      // FEAT-011 contracts/app-methods.md §"every method except app.preflight
      // and app.hello requires a valid app_session_token".
      'app_session_token': _sessionToken,
      if (params != null) 'params': params,
    };
    await client.sendLine(json.encode(payload));
    return completer.future.timeout(timeout);
  }

  /// Closes the socket + clears in-memory state. Token is discarded per FR-003.
  Future<void> teardown({Object? reason}) async {
    // FR-003 token wipe: overwrite to the empty string before nulling so a
    // post-mortem inspection of the heap can't surface the prior token
    // value via dead pointers. Dart strings are immutable, so the best we
    // can do is drop the only live reference and let GC reclaim.
    _sessionToken = null;
    _appContractVersion = null;
    _daemonVersion = null;
    for (final c in _pendingRequests.values) {
      if (!c.isCompleted) {
        c.completeError(StateError('Session torn down'));
      }
    }
    _pendingRequests.clear();
    await _responseSub?.cancel();
    _responseSub = null;
    await client.close();
    _events.add(SessionTornDown(reason: reason));
  }

  /// Releases the broadcast event stream. Call once at app shutdown.
  Future<void> dispose() async {
    await teardown();
    await _events.close();
  }

  void _onResponse(String line) {
    try {
      final Object? raw = json.decode(line);
      if (raw is! Map<String, dynamic>) {
        // unsolicited or malformed — ignore
        return;
      }
      final id = raw['id'] as int?;
      if (id == null) return;
      final completer = _pendingRequests.remove(id);
      if (completer == null) return;
      try {
        final env = Envelope.parse(line);
        completer.complete(env);
      } catch (e, st) {
        completer.completeError(e, st);
      }
    } catch (_) {
      // Swallow decode errors; SocketClient already surfaces framing errors via stream.
    }
  }

  void _onError(Object e, StackTrace st) {
    // Treat any error as a session-disrupting event; complete all pending with the error.
    for (final c in _pendingRequests.values) {
      if (!c.isCompleted) c.completeError(e, st);
    }
    _pendingRequests.clear();
    _events.add(SessionFailed(e));
  }
}
