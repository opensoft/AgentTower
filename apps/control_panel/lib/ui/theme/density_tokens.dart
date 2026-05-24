/// Density tokens — Comfortable + Compact (T029 + research R-24).
///
/// Per Round-3 R-24, Compact density MUST guarantee ≥ 44 px touch targets
/// to remain WCAG-compatible per FR-066. Both densities apply live (no
/// app restart on toggle).
class DensityTokens {
  DensityTokens._();

  // ---- Touch target floors (FR-066 a11y constraint) ----
  static const double minTouchTargetPx = 44;

  // ---- Comfortable density ----
  static const double comfortableRowHeight = 56;
  static const double comfortableButtonHeight = 48;
  static const double comfortablePaddingV = 16;
  static const double comfortablePaddingH = 24;
  static const double comfortableIconSize = 24;

  // ---- Compact density ----
  // Note: rowHeight + buttonHeight remain >= 44 per FR-066.
  static const double compactRowHeight = 44;
  static const double compactButtonHeight = 44;
  static const double compactPaddingV = 8;
  static const double compactPaddingH = 16;
  static const double compactIconSize = 20;
}
