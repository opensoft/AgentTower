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
class DaemonSession {
  DaemonSession({required this.client});

  final SocketClient client;

  String? _sessionToken;
  String? _appContractVersion;
  String? _daemonVersion;
  int _nextRequestId = 1;
  final _pendingRequests = <int, Completer<Envelope>>{};
  StreamSubscription<String>? _responseSub;

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
    _responseSub?.cancel();
    _responseSub = client.responses.listen(_onResponse, onError: _onError);

    // Send app.hello
    final id = _nextRequestId++;
    final completer = Completer<Envelope>();
    _pendingRequests[id] = completer;
    await client.sendLine(
      json.encode({
        'id': id,
        'method': 'app.hello',
        'params': {'client_name': 'agenttower-control-panel'},
      }),
    );
    final env = await completer.future.timeout(const Duration(seconds: 5));

    switch (env) {
      case SuccessEnvelope(:final result, :final appContractVersion):
        _sessionToken = result['session_token'] as String?;
        _appContractVersion = appContractVersion;
        _daemonVersion = result['daemon_version'] as String?;
        if (_sessionToken == null) {
          throw const FormatException('app.hello response missing session_token');
        }
      case FailureEnvelope(:final error):
        if (error.code == AppContractErrorCode.appContractMajorUnsupported) {
          // Don't throw — let the FR-002 banner surface drive UX.
          _appContractVersion = env.appContractVersion;
        }
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
      'session_token': _sessionToken,
      if (params != null) 'params': params,
    };
    await client.sendLine(json.encode(payload));
    return completer.future.timeout(timeout);
  }

  /// Closes the socket + clears in-memory state. Token is discarded per FR-003.
  Future<void> teardown() async {
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
  }

  void _onResponse(String line) {
    try {
      final raw = json.decode(line);
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
  }
}
