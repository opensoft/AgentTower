import 'package:flutter_test/flutter_test.dart';

/// Pump the widget tree at 100 ms intervals until [check] returns true or
/// [timeout] elapses. Returns `true` on success, `false` on timeout.
///
/// Use when the caller wants to inspect the timeout result itself (e.g.
/// to differentiate the "expected outage transition observed" vs "outage
/// never transitioned" cases without raising a test failure mid-check).
///
/// Polyfill: `WidgetTester.pumpUntil` does NOT exist on Flutter 3.27.0
/// (added in a later release). T173(d) — consolidates the inline
/// polyfills that T162 (`integration_test/runtime_states.dart`) and
/// T170 (`integration_test/us4_drift.dart`) each carried separately.
Future<bool> pumpUntilTrue(
  WidgetTester tester,
  Future<bool> Function() check,
  Duration timeout,
) async {
  final deadline = DateTime.now().add(timeout);
  while (DateTime.now().isBefore(deadline)) {
    await tester.pump(const Duration(milliseconds: 100));
    if (await check()) return true;
  }
  return false;
}

/// Pump the widget tree at 100 ms intervals until [check] returns true or
/// [timeout] elapses, in which case the test fails with [failureMessage].
///
/// Use when the caller is asserting a condition becomes true within a
/// wall-clock budget and a timeout is a test failure (SC-005-style).
///
/// Same polyfill rationale as [pumpUntilTrue] — see its docstring.
Future<void> pumpUntilOrFail(
  WidgetTester tester,
  bool Function() check,
  Duration timeout, {
  required String failureMessage,
}) async {
  final deadline = DateTime.now().add(timeout);
  while (DateTime.now().isBefore(deadline)) {
    await tester.pump(const Duration(milliseconds: 100));
    if (check()) return;
  }
  fail(failureMessage);
}
