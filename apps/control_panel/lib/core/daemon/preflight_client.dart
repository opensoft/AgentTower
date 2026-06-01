import 'dart:async';
import 'dart:convert';

import 'envelope.dart';
import 'errors.dart';
import 'socket_client.dart';

/// Session-free `app.preflight` client. Carved out from [AppClient] per
/// review finding A4 so the Doctor / Settings preflight surface (T026 /
/// T143) can probe the daemon BEFORE `app.hello` succeeds — including
/// when the daemon is unreachable, the socket file is missing, or a
/// previous `app_contract_major_unsupported` failure blocked session
/// bootstrap.
///
/// Owns its own [SocketClient] so this code path is independent of the
/// long-lived [DaemonSession]. Each call connects, sends, waits, and
/// tears down.
class PreflightClient {
  PreflightClient({required this.socketPath});

  final String socketPath;

  /// Performs one `app.preflight` round-trip.
  ///
  /// When the daemon responds, returns the raw `result` map; its `code`
  /// field is one of `{ok, daemon_unavailable, socket_missing,
  /// socket_permission_denied}` per FEAT-011 FR-011 (these reachability
  /// states are reported inside a *success* envelope, not thrown). The
  /// caller (the Doctor surface) maps that `code` to an outcome row.
  ///
  /// Throws [AppContractError] only when the daemon returns an actual
  /// failure envelope. The following are propagated untranslated for the
  /// Doctor surface to catch and map to its own diagnostic rows:
  ///   * [SocketException] — daemon unreachable, or the socket file is
  ///     missing / not permitted (an OS-level connect failure, per the
  ///     authoritative contract; not synthesized into a closed-set code
  ///     here since `socket_permission_denied` is a daemon-side
  ///     peer-credential diagnostic).
  ///   * [TimeoutException] — daemon accepted the connection but did not
  ///     complete the round-trip within [timeout].
  ///   * [FormatException] — daemon returned a malformed line.
  ///
  /// [timeout] bounds the entire round-trip (connect, send/flush, and the
  /// response wait), not just the response wait.
  Future<Map<String, Object?>> probe({
    Duration timeout = const Duration(seconds: 2),
  }) async {
    final client = SocketClient(socketPath);
    final responses = StreamQueue<String>(client.responses);
    try {
      await client.connect().timeout(timeout);
      final request = json.encode({
        'id': 1,
        'method': 'app.preflight',
      });
      await client.sendLine(request).timeout(timeout);
      final line = await responses.next.timeout(timeout);
      final env = Envelope.parse(line);
      return switch (env) {
        SuccessEnvelope(:final result) => result,
        FailureEnvelope(:final error) => throw error,
      };
    } finally {
      await responses.cancel(immediate: true);
      await client.close();
    }
  }
}

/// Minimal pull-style stream consumer used by [PreflightClient].
///
/// `package:async`'s `StreamQueue` would also work, but the rest of the
/// daemon stack avoids that dependency to keep the dependency tree narrow
/// (the only consumer is this preflight one-shot).
class StreamQueue<T> {
  StreamQueue(Stream<T> source) {
    _sub = source.listen(
      (T item) {
        if (_pending != null && !_pending!.isCompleted) {
          _pending!.complete(item);
          _pending = null;
        } else {
          _queue.add(item);
        }
      },
      onError: (Object e, StackTrace st) {
        if (_pending != null && !_pending!.isCompleted) {
          _pending!.completeError(e, st);
          _pending = null;
        } else {
          // Latch the error so a later next() replays it instead of
          // hanging on a completer nothing will complete.
          _error ??= e;
          _errorStack ??= st;
        }
      },
      onDone: () {
        if (_pending != null && !_pending!.isCompleted) {
          _pending!.completeError(
            StateError('Stream closed before response arrived'),
          );
          _pending = null;
        } else {
          // Latch the terminal state so a later next() surfaces it
          // immediately instead of hanging until timeout.
          _isDone = true;
        }
      },
    );
  }

  late final StreamSubscription<T> _sub;
  final List<T> _queue = [];
  Completer<T>? _pending;
  bool _isDone = false;
  Object? _error;
  StackTrace? _errorStack;

  Future<T> get next {
    if (_queue.isNotEmpty) {
      return Future.value(_queue.removeAt(0));
    }
    if (_error != null) {
      final e = _error!;
      final st = _errorStack;
      _error = null;
      _errorStack = null;
      return Future.error(e, st);
    }
    if (_isDone) {
      return Future.error(
        StateError('Stream closed before response arrived'),
      );
    }
    _pending = Completer<T>();
    return _pending!.future;
  }

  Future<void> cancel({bool immediate = false}) async {
    await _sub.cancel();
  }
}
