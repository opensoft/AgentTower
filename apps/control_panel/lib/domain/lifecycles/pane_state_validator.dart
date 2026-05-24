import '../models/common_enums.dart';

/// Encodes FR-014 pane state transition matrix per data-model.md §1.4.
///
/// Allowed transitions:
/// - `discovered_and_unmanaged` ↔ `discovered_and_registered` (adoption / de-adoption)
/// - Any state may transition to `inactive_or_stale` on pane disappearance,
///   and may return to its prior state on rediscovery
/// - Any state may transition to `discovery_degraded` on probe failure,
///   and back on recovery
/// - There are NO terminal pane states
///
/// T039 (Phase 2 Foundational).
class PaneStateValidator {
  /// Returns `true` iff [to] is a legal next state from [from].
  static bool isValidTransition(PaneState from, PaneState to) {
    if (from == to) return true; // no-op transitions are always valid.

    // Inactive/stale and discovery-degraded can transition from any state and
    // back to any state — they're orthogonal to the adoption status.
    if (to == PaneState.inactiveOrStale ||
        to == PaneState.discoveryDegraded ||
        from == PaneState.inactiveOrStale ||
        from == PaneState.discoveryDegraded) {
      return true;
    }

    // Adoption / de-adoption swap.
    return (from == PaneState.discoveredAndUnmanaged &&
            to == PaneState.discoveredAndRegistered) ||
        (from == PaneState.discoveredAndRegistered &&
            to == PaneState.discoveredAndUnmanaged);
  }

  /// Always returns `false` — no terminal pane states per FR-014.
  static bool isTerminal(PaneState s) => false;
}
