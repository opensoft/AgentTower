import 'package:flutter/material.dart';

/// Focus and accessible-name helpers per FR-066 + Round-3 R-22.
///
/// R-22 enumerates the WCAG 2.1 AA-equivalent baseline:
///   1.3.1 Info & Relationships, 1.4.3 Contrast (Minimum), 2.1.1 Keyboard,
///   2.4.3 Focus Order, 2.4.7 Focus Visible, 4.1.2 Name/Role/Value.
///
/// Scope (per R-22): every interactive control, every status indicator,
/// every error message, every modal. Accessible-name patterns required
/// for every badge, every icon-only quick action, every severity color.
class A11y {
  A11y._();

  /// Standard accessible-name pattern for a badge: `<label>, severity <severity>`.
  /// Example: `"Drift, severity warning"`.
  static String badgeLabel({required String label, String? severity}) =>
      severity == null ? label : '$label, severity $severity';

  /// Standard accessible-name pattern for an icon-only quick action.
  /// Example: `"Adopt pane"` for an icon button on a pane row.
  static String iconActionLabel({
    required String action,
    String? targetDescription,
  }) =>
      targetDescription == null
          ? action
          : '$action $targetDescription';

  /// Wraps [child] with a `Semantics` widget enforcing focusability + label.
  /// Use for icon-only or color-only signals so screen readers get equivalent
  /// information.
  static Widget labeled({
    required String label,
    required Widget child,
    bool focusable = false,
    bool button = false,
  }) {
    return Semantics(
      label: label,
      focusable: focusable,
      button: button,
      container: true,
      child: child,
    );
  }

  /// Visible-focus decoration. Use on custom focusable widgets so 2.4.7
  /// Focus Visible is satisfied.
  static BoxDecoration focusRing(BuildContext context, {bool focused = false}) {
    if (!focused) return const BoxDecoration();
    return BoxDecoration(
      border: Border.all(
        color: Theme.of(context).colorScheme.primary,
        width: 2,
      ),
      borderRadius: BorderRadius.circular(4),
    );
  }
}
