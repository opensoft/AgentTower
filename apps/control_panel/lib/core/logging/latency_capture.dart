import 'package:logger/logger.dart';

import 'rotating_file_logger.dart';

/// Operator-action latency capture. T023 + research R-14.
///
/// Logs a single info-level entry for any operator action exceeding
/// **200 ms p95**. The 200 ms threshold is the perceptual boundary above
/// which an action "feels delayed".
///
/// Usage:
///   final result = await captureLatency(logger, 'app.send_input', () => session.call(...));
class LatencyCapture {
  LatencyCapture(this.logger);

  static const Duration threshold = Duration(milliseconds: 200);

  final RotatingFileLogger logger;

  /// Times [body]; logs if elapsed > [threshold]. Returns the body's result.
  Future<T> capture<T>(String actionName, Future<T> Function() body) async {
    final sw = Stopwatch()..start();
    try {
      return await body();
    } finally {
      sw.stop();
      if (sw.elapsed > threshold) {
        logger.log(Level.info, 'action_latency_above_threshold', {
          'action': actionName,
          'elapsed_ms': sw.elapsedMilliseconds,
          'threshold_ms': threshold.inMilliseconds,
        });
      }
    }
  }
}
