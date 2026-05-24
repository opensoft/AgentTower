import '../models/common_enums.dart';

/// Encodes FR-048 validation run lifecycle per data-model.md §1.11.
///
/// Allowed transitions:
/// - `queued → running → completed`
/// - From `queued` or `running` → `cancelled`
/// - From `queued` only → `failed_to_start`
/// - `completed`, `cancelled`, `failed_to_start` are terminal
///
/// The `result` field is only meaningful in terminal states; non-terminal
/// states MUST carry `null` result. [isResultMeaningful] encodes that rule.
///
/// T042 (Phase 2 Foundational).
class ValidationRunStateValidator {
  static bool isValidTransition(RunState from, RunState to) {
    if (from == to) return true;
    if (from.isTerminal) return false;

    if (to == RunState.cancelled) {
      return from == RunState.queued || from == RunState.running;
    }
    if (to == RunState.failedToStart) {
      return from == RunState.queued;
    }

    switch (from) {
      case RunState.queued:
        return to == RunState.running;
      case RunState.running:
        return to == RunState.completed;
      case RunState.completed:
      case RunState.cancelled:
      case RunState.failedToStart:
        return false; // terminal
    }
  }

  static bool isTerminal(RunState s) => s.isTerminal;

  /// Returns `true` iff the result field MAY carry a non-null value in [state].
  /// Non-terminal states MUST have null result per FR-048.
  static bool isResultMeaningful(RunState state) => state.isTerminal;
}
