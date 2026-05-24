import '../models/common_enums.dart';

/// Encodes FR-034 drift signal lifecycle per data-model.md §1.9.
///
/// Allowed transitions:
/// - `new → review_needed → confirmed → repair_planned → resolved` canonical forward path
/// - Any non-terminal state may transition to `accepted_as_built` or `dismissed`
/// - `resolved`, `accepted_as_built`, `dismissed` are terminal
/// - Transitions may NOT skip forward states except into the terminal pair
///
/// T040 (Phase 2 Foundational).
class DriftStateValidator {
  /// Returns `true` iff [to] is a legal next state from [from].
  static bool isValidTransition(DriftStatus from, DriftStatus to) {
    if (from == to) return true;

    // Terminal states accept no outgoing transitions.
    if (from.isTerminal) return false;

    // From any non-terminal state, the two non-resolved terminal exits are allowed.
    if (to == DriftStatus.acceptedAsBuilt || to == DriftStatus.dismissed) {
      return true;
    }

    // Forward path: only the next sequential state is allowed.
    const forwardPath = [
      DriftStatus.newFinding,
      DriftStatus.reviewNeeded,
      DriftStatus.confirmed,
      DriftStatus.repairPlanned,
      DriftStatus.resolved,
    ];
    final fromIdx = forwardPath.indexOf(from);
    final toIdx = forwardPath.indexOf(to);
    return fromIdx >= 0 && toIdx == fromIdx + 1;
  }

  static bool isTerminal(DriftStatus s) => s.isTerminal;
}
