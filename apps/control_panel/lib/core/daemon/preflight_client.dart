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

  /// Performs one `app.preflight` round-trip. Returns the raw `result`
  /// map on success, or throws [AppContractError] on failure (e.g.
  /// `daemon_unavailable`, `socket_missing`, `socket_permission_denied`,
  /// `host_only`). Caller (the Doctor surface) maps both success and
  /// closed-set failure codes to outcome rows.
  Future<Map<String, Object?>> probe({
    Duration timeout = const Duration(seconds: 2),
  }) async {
    final client = SocketClient(socketPath);
    final responses = StreamQueue<String>(client.responses);
    try {
      await client.connect();
      await client.sendLine(json.encode({
        'id': 1,
        'method': 'app.preflight',
      }));
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
        }
      },
      onDone: () {
        if (_pending != null && !_pending!.isCompleted) {
          _pending!.completeError(
            StateError('Stream closed before response arrived'),
          );
          _pending = null;
        }
      },
    );
  }

  late final StreamSubscription<T> _sub;
  final List<T> _queue = [];
  Completer<T>? _pending;

  Future<T> get next {
    if (_queue.isNotEmpty) {
      return Future.value(_queue.removeAt(0));
    }
    _pending = Completer<T>();
    return _pending!.future;
  }

  Future<void> cancel({bool immediate = false}) async {
    await _sub.cancel();
  }
}
