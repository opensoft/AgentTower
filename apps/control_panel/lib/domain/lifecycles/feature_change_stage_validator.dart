import '../models/common_enums.dart';

/// Encodes the F7-b deferred-stage transition rule per data-model.md §1.5.
///
/// The `deferred` stage is non-terminal: a feature/change in `deferred` MAY
/// transition back to `definition` or `spec_ready` via an explicit un-defer
/// action. No other transitions from `deferred` are allowed. The
/// feature/change id is preserved across un-defer.
///
/// Other stage transitions (definition → spec_ready → engineering → ...)
/// are owned by the daemon and not validated here — this validator focuses
/// solely on the un-defer rule, which is the only transition the desktop
/// app may trigger as an operator action.
///
/// T043 (Phase 2 Foundational).
class FeatureChangeStageValidator {
  /// Returns `true` iff [to] is a legal next stage from [from] when the
  /// transition is operator-driven (un-defer is the only operator-triggerable
  /// stage transition at MVP).
  static bool isValidOperatorTransition(Stage from, Stage to) {
    if (from != Stage.deferred) return false;
    return to == Stage.definition || to == Stage.specReady;
  }

  /// Stages the app considers permanent for operator-facing rendering.
  /// `merged` is the only naturally-terminal stage; `deferred` is non-terminal
  /// per F7-b but signals "out of active flow" until un-deferred.
  static bool isOperatorTerminal(Stage s) => s == Stage.merged;
}
