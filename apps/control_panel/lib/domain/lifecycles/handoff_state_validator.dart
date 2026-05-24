import '../models/common_enums.dart';

/// Encodes FR-044 handoff assignment-state lifecycle per data-model.md §1.6.
///
/// Allowed transitions (per spec — see `data-model.md` §1.6 + FR-044/FR-081):
/// - `drafted → submitted`
/// - `submitted → accepted | cancelled | superseded`
/// - `accepted → active | cancelled | superseded`
/// - `active   → waiting | blocked | completed | cancelled | superseded`
/// - `waiting` and `blocked` return to `active` only
/// - `completed`, `cancelled`, `superseded` are terminal
///
/// `drafted`, `waiting`, and `blocked` MAY NOT short-circuit straight to
/// `cancelled` or `superseded`: a draft is discarded client-side without a
/// state transition, and `waiting`/`blocked` must first return to `active`
/// before terminating. The earlier "cancel from any non-terminal state"
/// rule was over-permissive and is corrected here per review finding SC1.
///
/// Operator-driven transitions and daemon-driven transitions are both
/// permitted; daemon is authoritative on conflicts (encoded outside this
/// validator).
///
/// T041 (Phase 2 Foundational).
class HandoffStateValidator {
  /// Returns `true` iff [to] is a legal next state from [from].
  static bool isValidTransition(AssignmentState from, AssignmentState to) {
    if (from == to) return true;
    if (from.isTerminal) return false;

    switch (from) {
      case AssignmentState.drafted:
        return to == AssignmentState.submitted;
      case AssignmentState.submitted:
        return to == AssignmentState.accepted ||
            to == AssignmentState.cancelled ||
            to == AssignmentState.superseded;
      case AssignmentState.accepted:
        return to == AssignmentState.active ||
            to == AssignmentState.cancelled ||
            to == AssignmentState.superseded;
      case AssignmentState.active:
        return to == AssignmentState.waiting ||
            to == AssignmentState.blocked ||
            to == AssignmentState.completed ||
            to == AssignmentState.cancelled ||
            to == AssignmentState.superseded;
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
