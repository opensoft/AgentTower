import '../models/common_enums.dart';

/// Encodes FR-044 handoff assignment-state lifecycle per data-model.md §1.6.
///
/// Allowed transitions:
/// - `drafted → submitted → accepted → active`
/// - From `active`: → `waiting`, `blocked`, `completed`, `cancelled`
/// - `waiting` and `blocked` may return to `active`
/// - `submitted` and `accepted` may transition directly to `cancelled` or `superseded`
/// - `completed`, `cancelled`, `superseded` are terminal
///
/// Operator-driven transitions and daemon-driven transitions are both permitted;
/// daemon is authoritative on conflicts (encoded outside this validator).
///
/// T041 (Phase 2 Foundational).
class HandoffStateValidator {
  /// Returns `true` iff [to] is a legal next state from [from].
  static bool isValidTransition(AssignmentState from, AssignmentState to) {
    if (from == to) return true;
    if (from.isTerminal) return false;

    // Cancellation + supersede are accessible from drafted/submitted/accepted/active/waiting/blocked.
    if (to == AssignmentState.cancelled || to == AssignmentState.superseded) {
      return !from.isTerminal;
    }

    switch (from) {
      case AssignmentState.drafted:
        return to == AssignmentState.submitted;
      case AssignmentState.submitted:
        return to == AssignmentState.accepted;
      case AssignmentState.accepted:
        return to == AssignmentState.active;
      case AssignmentState.active:
        return to == AssignmentState.waiting ||
            to == AssignmentState.blocked ||
            to == AssignmentState.completed;
      case AssignmentState.waiting:
      case AssignmentState.blocked:
        return to == AssignmentState.active;
      case AssignmentState.completed:
      case AssignmentState.cancelled:
      case AssignmentState.superseded:
        return false; // terminal — already short-circuited above
    }
  }

  static bool isTerminal(AssignmentState s) => s.isTerminal;
}
