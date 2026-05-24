import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:logger/logger.dart';

import '../persistence/paths.dart';

/// Rotating JSON-lines local log file. T021 + Round-3 R-26.
///
/// - 5 files × 10 MiB rotation (research R-07)
/// - JSON-lines format, levels error+warn+info (debug toggleable in Settings)
/// - Redaction denylist for `app_session_token`, `prompt`/`prompt_text`,
///   `operator_notes` per R-26 + spec FR-074 / FR-079
/// - Timestamps: ISO-8601 wall-clock + monotonic-ns suffix
/// - Logs at `<app-data>/agenttower-control-panel/logs/control-panel.log.<N>`
/// - No upload, no telemetry (FR-074)
///
/// Security note (review S1): the key-based redaction in [_redact] only
/// catches structured fields. If a caller logs a whole envelope as a
/// string — e.g. `log(Level.error, 'bad envelope: $line')` — the
/// `app_session_token` value inside the stringified JSON sails past
/// `_redact`. To close this leak, every emitted line is run through
/// [_scrubLine] which redacts the values of the same denylist keys when
/// they appear inside a string. See also review M-SC1 (denylist narrowed
/// to the spec set; `session_token` removed in favor of the canonical
/// `app_session_token`).
class RotatingFileLogger {
  RotatingFileLogger({required this.paths, bool debugEnabled = false})
      : _debugEnabled = debugEnabled,
        _stopwatch = Stopwatch()..start();

  final AppPaths paths;
  final bool _debugEnabled;
  final Stopwatch _stopwatch;

  static const int _maxBytesPerFile = 10 * 1024 * 1024; // 10 MiB
  static const int _maxFiles = 5;

  /// The denylist documented in R-26 / FR-079, extended in Block E with
  /// `payload` — the actual wire field that carries Direct Send prompt
  /// bodies on `app.send_input` (see `app-methods.md` line 319). Without
  /// `payload` the redaction would miss any future log site that
  /// stringifies a `send_input` request envelope. Renaming the spec set
  /// remains a coordinated OpenSpec change; adding NEW field names that
  /// match the same intent (prompt body content) is local.
  static const Set<String> _redactedKeys = {
    'app_session_token',
    'prompt',
    'prompt_text',
    'operator_notes',
    'payload',
    // Swarm-review M-16: handoff submit envelope carries the rendered
    // prompt body verbatim. Redact defense-in-depth in case a future
    // log site stringifies the envelope.
    'generated_prompt_text',
    'helper_policy_snapshot',
  };

  /// Compiled regex set for the string-scrub pass. Pre-built once because
  /// `RegExp` construction is heavier than a per-call lookup.
  static final List<RegExp> _stringRedactPatterns = [
    for (final key in _redactedKeys)
      RegExp('("' + RegExp.escape(key) + r'"\s*:\s*)"[^"\\]*(?:\\.[^"\\]*)*"'),
  ];

  IOSink? _sink;
  int _bytesWritten = 0;
  Logger? _logger;
  Future<void> _writeChain = Future.value();

  /// Initializes the logger. Idempotent. Call before any [log] call.
  Future<void> initialize() async {
    if (_logger != null) return;
    await _openCurrentFile();
    _logger = Logger(
      level: _debugEnabled ? Level.debug : Level.info,
      printer: _JsonLinesPrinter(this),
      output: _SinkOutput(this),
    );
  }

  /// Logs at the named level. [fields] are merged into the JSON object;
  /// keys in the redaction denylist are replaced with `"[REDACTED]"`.
  /// The final emitted line is additionally scrubbed for stringified
  /// occurrences of the same keys (review fix S1).
  void log(Level level, String message, [Map<String, dynamic>? fields]) {
    final l = _logger;
    if (l == null) return;
    final redacted = _redact(fields ?? const {});
    final entry = {
      'msg': message,
      if (redacted.isNotEmpty) 'fields': redacted,
    };
    switch (level) {
      case Level.error:
        l.e(entry);
        break;
      case Level.warning:
        l.w(entry);
        break;
      case Level.info:
        l.i(entry);
        break;
      case Level.debug:
        if (_debugEnabled) l.d(entry);
        break;
      default:
        l.i(entry);
    }
  }

  /// Closes the current file sink, awaiting any pending writes first so
  /// FR-082 close-handler integration sees a flushed file.
  Future<void> close() async {
    await _writeChain;
    await _sink?.flush();
    await _sink?.close();
    _sink = null;
  }

  // ---- internal ----

  Map<String, dynamic> _redact(Map<String, dynamic> input) {
    final out = <String, dynamic>{};
    for (final entry in input.entries) {
      if (_redactedKeys.contains(entry.key)) {
        out[entry.key] = '[REDACTED]';
      } else if (entry.value is Map<String, dynamic>) {
        out[entry.key] = _redact(entry.value as Map<String, dynamic>);
      } else {
        out[entry.key] = entry.value;
      }
    }
    return out;
  }

  /// Second-line-of-defence: scrub stringified occurrences of any
  /// redacted key in the FULL emitted JSON-lines record. This is what
  /// catches `log('bad envelope: $line')` where the structured-field
  /// redaction never sees the secret.
  String _scrubLine(String line) {
    var out = line;
    for (final pat in _stringRedactPatterns) {
      out = out.replaceAllMapped(pat, (m) => '${m.group(1)}"[REDACTED]"');
    }
    return out;
  }

  Future<void> _openCurrentFile() async {
    final dir = paths.logsDir;
    final current =
        File('${dir.path}${Platform.pathSeparator}control-panel.log.0');
    if (current.existsSync()) {
      final stat = await current.stat();
      if (stat.size >= _maxBytesPerFile) {
        await _rotate();
      }
      _bytesWritten = (await current.stat()).size;
    } else {
      _bytesWritten = 0;
    }
    _sink = current.openWrite(mode: FileMode.append);
  }

  Future<void> _rotate() async {
    final dir = paths.logsDir;
    // Delete the oldest, shift the rest.
    for (var i = _maxFiles - 1; i >= 0; i--) {
      final f =
          File('${dir.path}${Platform.pathSeparator}control-panel.log.$i');
      if (!f.existsSync()) continue;
      if (i == _maxFiles - 1) {
        await f.delete();
      } else {
        final next = File(
            '${dir.path}${Platform.pathSeparator}control-panel.log.${i + 1}');
        await f.rename(next.path);
      }
    }
    _bytesWritten = 0;
  }

  /// Internal: write one JSON-lines record, rotating if cap exceeded.
  /// Writes are serialized through `_writeChain` so concurrent log calls
  /// don't interleave bytes inside a single line (review fix M-S4).
  Future<void> _writeRaw(String jsonLine) {
    return _writeChain = _writeChain.then((_) async {
      final scrubbed = _scrubLine(jsonLine);
      final bytes = utf8.encode('$scrubbed\n');
      if (_bytesWritten + bytes.length > _maxBytesPerFile) {
        await _sink?.flush();
        await _sink?.close();
        _sink = null;
        await _rotate();
        await _openCurrentFile();
      }
      _sink?.add(bytes);
      _bytesWritten += bytes.length;
    }).catchError((Object _) {
      // Swallow per-write failures so a failed rotation doesn't bring
      // down the whole future chain.
    });
  }

  String _currentTimestamp() {
    final wall = DateTime.now().toUtc().toIso8601String();
    final mono = _stopwatch.elapsed.inMicroseconds * 1000; // nanoseconds
    return '$wall|mono:$mono';
  }
}

/// JSON-lines printer that emits one record per log call.
class _JsonLinesPrinter extends LogPrinter {
  _JsonLinesPrinter(this.parent);
  final RotatingFileLogger parent;

  @override
  List<String> log(LogEvent event) {
    final record = <String, dynamic>{
      'ts': parent._currentTimestamp(),
      'level': event.level.name,
      'logger': 'control-panel',
      ...(event.message is Map<String, dynamic>
          ? event.message as Map<String, dynamic>
          : {'msg': event.message.toString()}),
    };
    if (event.error != null) record['error'] = event.error.toString();
    return [json.encode(record)];
  }
}

class _SinkOutput extends LogOutput {
  _SinkOutput(this.parent);
  final RotatingFileLogger parent;

  @override
  void output(OutputEvent event) {
    for (final line in event.lines) {
      // The actual write is serialized inside `_writeRaw` so we don't
      // need to `await` here. The returned future is chained internally;
      // a `close()` call awaits the chain before exiting.
      unawaited(parent._writeRaw(line));
    }
  }
}
