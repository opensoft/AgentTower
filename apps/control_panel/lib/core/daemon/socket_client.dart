import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

/// Unix-socket client for the FEAT-011 daemon. T010 (Phase 2 Foundational).
///
/// Enforces FEAT-011 FR-003a per-line caps (1 MiB request / 8 MiB response)
/// and FR-003b framing strictness: UTF-8 only, `\n`-terminated, no `\r`,
/// no `\x00`, no trailing content after the newline.
///
/// Research R-04 (dart:io Socket + InternetAddressType.unix) is the
/// transport. Satisfies FR-001 + FR-060 (refuses any non-local target —
/// no host/port field is exposed anywhere in the client API).
class SocketClient {
  SocketClient(this._socketPath) {
    // Most platforms cap the Unix-socket file path at a small length
    // (Linux: 108, macOS / BSD: 104, Windows: 260 via AF_UNIX). A long
    // path silently truncates and connect() fails with an obscure
    // ENOENT. Surface the limit clearly instead so a misconfigured
    // Settings → connection path produces a useful error in the
    // FR-001 retry banner (review fix M-S2).
    final byteLen = utf8.encode(_socketPath).length;
    const maxSocketPathBytes = 104;
    if (byteLen > maxSocketPathBytes) {
      throw ArgumentError.value(
        _socketPath,
        'socketPath',
        'Unix socket path is $byteLen bytes; OS-level cap is '
            '$maxSocketPathBytes bytes on macOS/BSD and 108 on Linux. '
            'Pick a shorter path (e.g. under \$XDG_RUNTIME_DIR).',
      );
    }
  }

  static const int requestCapBytes = 1024 * 1024; // 1 MiB per FR-003a
  static const int responseCapBytes = 8 * 1024 * 1024; // 8 MiB per FR-003a

  final String _socketPath;

  /// Read-only view of the configured Unix socket path. Used by
  /// [DaemonSession.reBootstrap] (T174a) to construct a fresh
  /// [SocketClient] aimed at the same daemon socket without
  /// requiring the caller to re-thread the path through Settings.
  String get socketPath => _socketPath;

  Socket? _socket;
  StreamSubscription<List<int>>? _sub;
  final _lineBuffer = BytesBuilder();
  final _responses = StreamController<String>.broadcast();
  Completer<void>? _connectCompleter;

  /// Stream of decoded UTF-8 response lines (one JSON object per line).
  Stream<String> get responses => _responses.stream;

  bool get isConnected => _socket != null;

  /// Opens the Unix socket. Throws [SocketException] on connect failure.
  Future<void> connect() async {
    if (_socket != null) return;
    _connectCompleter = Completer<void>();
    try {
      _socket = await Socket.connect(
        InternetAddress(_socketPath, type: InternetAddressType.unix),
        0,
      );
      _sub = _socket!.listen(
        _onData,
        onError: _onError,
        onDone: _onDone,
        cancelOnError: false,
      );
      _connectCompleter!.complete();
    } catch (e, st) {
      _connectCompleter!.completeError(e, st);
      _socket = null;
      rethrow;
    }
  }

  /// Sends one request line. Enforces FR-003a 1 MiB cap and FR-003b framing.
  /// The provided [jsonLine] MUST NOT contain `\n`, `\r`, or `\x00`.
  Future<void> sendLine(String jsonLine) async {
    final socket = _socket;
    if (socket == null) {
      throw const SocketException('Not connected');
    }
    if (jsonLine.contains('\n') ||
        jsonLine.contains('\r') ||
        jsonLine.contains('\x00')) {
      // NB: never include `jsonLine` as the FormatException source — request
      // payloads carry the `app_session_token` and operator-notes/prompt
      // bodies, which FR-074 forbids leaking into logs/error strings
      // (swarm-review: token leak via FormatException.toString()).
      throw const FormatException(
        'Request payload contains forbidden control characters (FR-003b)',
      );
    }
    final bytes = utf8.encode(jsonLine);
    if (bytes.length > requestCapBytes) {
      throw FormatException(
        'Request exceeds FEAT-011 FR-003a 1 MiB per-line cap '
        '(${bytes.length} bytes)',
      );
    }
    // Single-write framing (review fix M-S1): emit `<json>\n` as one
    // contiguous buffer so the underlying TCP/Unix-socket layer never
    // observes a `<json>` chunk without its terminator. Two separate
    // `add()` calls were vulnerable to a partial flush leaving the
    // daemon waiting on a newline it would never receive.
    final framed = Uint8List(bytes.length + 1);
    framed.setRange(0, bytes.length, bytes);
    framed[bytes.length] = 0x0A;
    socket.add(framed);
    await socket.flush();
  }

  /// Cleanly closes the socket. Idempotent.
  Future<void> close() async {
    await _sub?.cancel();
    _sub = null;
    await _socket?.close();
    _socket = null;
  }

  // ---- internal ----

  void _onData(List<int> chunk) {
    _lineBuffer.add(chunk);
    _drainLines();
  }

  void _drainLines() {
    final buf = _lineBuffer.toBytes();
    if (buf.length > responseCapBytes) {
      // FR-003a cap exceeded for a single unterminated line.
      _responses.addError(
        FormatException(
          'Response exceeds FEAT-011 FR-003a 8 MiB per-line cap',
        ),
      );
      _resetBuffer();
      return;
    }

    int lineStart = 0;
    for (var i = 0; i < buf.length; i++) {
      final b = buf[i];
      if (b == 0x0D || b == 0x00) {
        // FR-003b: no \r or \x00 anywhere.
        _responses.addError(
          FormatException(
            'Response contains forbidden control byte 0x${b.toRadixString(16)} (FR-003b)',
          ),
        );
        _resetBuffer();
        return;
      }
      if (b == 0x0A) {
        final lineBytes = Uint8List.sublistView(buf, lineStart, i);
        try {
          final line = utf8.decode(lineBytes, allowMalformed: false);
          _responses.add(line);
        } catch (e) {
          _responses.addError(
            FormatException('Response is not valid UTF-8 (FR-003b)', lineBytes),
          );
        }
        lineStart = i + 1;
      }
    }
    if (lineStart > 0) {
      // Keep only the trailing partial line.
      final remainder = Uint8List.sublistView(buf, lineStart);
      _lineBuffer.clear();
      _lineBuffer.add(remainder);
    }
  }

  void _resetBuffer() {
    _lineBuffer.clear();
  }

  void _onError(Object error, StackTrace st) {
    _responses.addError(error, st);
  }

  void _onDone() {
    // Treat clean close as a signal for the session layer to re-bootstrap (FR-003).
    _responses.close();
    _socket = null;
  }
}
