import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:logger/logger.dart';

import 'rotating_file_logger.dart';

/// Top-level uncaught-exception handler. T022 + research R-18.
///
/// Captures Flutter framework errors + zone errors and writes them to
/// the rotating log. No remote crash reporter (FR-074).
///
/// Wrap `runApp()` like:
///   `runWithErrorHandling(logger, () => runApp(MyApp()))`.
///
/// Security note: exception and stack-trace text is free-form, so it does
/// NOT match the JSON `"key":"value"` shape that
/// `RotatingFileLogger._scrubLine` redacts, and the keys emitted here
/// (`exception`/`stack`) are not on the structured-field denylist either.
/// An exception thrown while handling a daemon request envelope can embed
/// `app_session_token` / prompt bodies in `error.toString()`. To preserve
/// the logger's best-effort redaction guarantee (see
/// `rotating_file_logger.dart` lines 19-27), every free-form error/stack
/// string is passed through [_scrubErrorText] before it is logged.
void runWithErrorHandling(
  RotatingFileLogger logger,
  void Function() entrypoint,
) {
  FlutterError.onError = (FlutterErrorDetails details) {
    logger.log(Level.error, 'uncaught_flutter_error', {
      'exception': _scrubErrorText(details.exceptionAsString()),
      'library': details.library ?? '',
      'context': details.context?.toString() ?? '',
    });
    FlutterError.presentError(details);
  };
  PlatformDispatcher.instance.onError = (Object error, StackTrace stack) {
    logger.log(Level.error, 'uncaught_platform_error', {
      'exception': _scrubErrorText(error.toString()),
      'stack': _scrubErrorText(stack.toString()),
    });
    return true;
  };
  runZonedGuarded(
    entrypoint,
    (Object error, StackTrace stack) {
      logger.log(Level.error, 'uncaught_zone_error', {
        'exception': _scrubErrorText(error.toString()),
        'stack': _scrubErrorText(stack.toString()),
      });
    },
  );
}

/// Sensitive field names that can leak into free-form exception / stack
/// text when an error is thrown while handling a daemon request envelope.
/// Mirrors the structured denylist in `RotatingFileLogger` (the canonical
/// set lives there; this is a defense-in-depth copy because that set is
/// private and free-form text bypasses its JSON-shaped scrubber).
const List<String> _sensitiveErrorKeys = [
  'app_session_token',
  'prompt',
  'prompt_text',
  'operator_notes',
  'payload',
  'generated_prompt_text',
  'helper_policy_snapshot',
];

/// Pre-compiled patterns that match `<key>=value`, `<key>: value`, and
/// JSON `"<key>":"value"` shapes inside free-form text. Longer keys are
/// matched first so a substring key (e.g. `prompt`) does not shadow a more
/// specific one (e.g. `prompt_text`).
final List<RegExp> _errorTextRedactPatterns = () {
  final keys = [..._sensitiveErrorKeys]
    ..sort((a, b) => b.length.compareTo(a.length));
  return [
    for (final key in keys)
      RegExp(
        // group 1: key + separator (`=`, `:`, or JSON `":`), preserving
        // surrounding quote so we re-emit a well-formed token.
        r'("?' +
            RegExp.escape(key) +
            r'"?\s*[:=]\s*)' +
            // group 2: the value — a quoted JSON string, or an unquoted
            // run of non-whitespace, non-delimiter characters.
            r'("[^"\\]*(?:\\.[^"\\]*)*"|[^\s,&;}\)]+)',
        caseSensitive: false,
      ),
  ];
}();

/// Redacts sensitive values embedded in free-form exception / stack text.
/// Returns the input with any matched value replaced by `[REDACTED]`.
String _scrubErrorText(String text) {
  var out = text;
  for (final pat in _errorTextRedactPatterns) {
    out = out.replaceAllMapped(pat, (m) {
      final value = m.group(2)!;
      final replacement = value.startsWith('"') ? '"[REDACTED]"' : '[REDACTED]';
      return '${m.group(1)}$replacement';
    });
  }
  return out;
}
