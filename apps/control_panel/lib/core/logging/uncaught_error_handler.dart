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
void runWithErrorHandling(
  RotatingFileLogger logger,
  void Function() entrypoint,
) {
  FlutterError.onError = (FlutterErrorDetails details) {
    logger.log(Level.error, 'uncaught_flutter_error', {
      'exception': details.exceptionAsString(),
      'library': details.library ?? '',
      'context': details.context?.toString() ?? '',
    });
    FlutterError.presentError(details);
  };
  PlatformDispatcher.instance.onError = (Object error, StackTrace stack) {
    logger.log(Level.error, 'uncaught_platform_error', {
      'exception': error.toString(),
      'stack': stack.toString(),
    });
    return true;
  };
  runZonedGuarded(
    entrypoint,
    (Object error, StackTrace stack) {
      logger.log(Level.error, 'uncaught_zone_error', {
        'exception': error.toString(),
        'stack': stack.toString(),
      });
    },
  );
}
