import 'package:flutter/material.dart';

import '../ui/theme/color_tokens.dart';
import 'models/common_enums.dart';

/// R-15 severity-palette helper. Swarm-review CR-8.
///
/// Centralizes the {color, icon, label, semantic description} tuple
/// for every severity value across [DriftSeverity], [AttentionSeverity],
/// and [NotificationSeverity] — they share the same R-15 palette per
/// the research note.
///
/// **Why a helper**: previously `drift_view._severityColor` / `_severityIcon`
/// and `project_card._DriftChip` / `_AttentionChip` each invented their
/// own mapping using generic `Theme.colorScheme.error/tertiary/secondary/
/// primary` slots — those don't match R-15 and don't guarantee WCAG-AA
/// contrast over `surfaceContainerHighest`. R-22 also requires the
/// "color + icon + text label" triad so colorblind operators get the
/// same information. This helper produces all three from one place.
class SeverityVisuals {
  const SeverityVisuals._({
    required this.color,
    required this.onColor,
    required this.icon,
    required this.label,
    required this.semanticDescription,
  });

  /// Background color suitable for chips / avatars. Honors light/dark
  /// theme variants per R-15.
  final Color color;

  /// Foreground color (text/icon) paired with [color] to satisfy
  /// WCAG-AA contrast.
  final Color onColor;

  /// Distinct icon per severity (R-22 redundancy with [color] +
  /// [label]).
  final IconData icon;

  /// Short text label rendered alongside the icon (R-22 redundancy).
  /// Capitalized so it reads as UI copy, not a wire enum value.
  final String label;

  /// Longer description for screen-readers / tooltips.
  final String semanticDescription;

  static SeverityVisuals forDrift(DriftSeverity s, Brightness brightness) {
    return switch (s) {
      DriftSeverity.info => _info(brightness),
      DriftSeverity.warning => _warning(brightness),
      DriftSeverity.high => _high(brightness),
      DriftSeverity.critical => _critical(brightness),
    };
  }

  static SeverityVisuals forAttention(
    AttentionSeverity s,
    Brightness brightness,
  ) {
    return switch (s) {
      AttentionSeverity.info => _info(brightness),
      AttentionSeverity.warning => _warning(brightness),
      AttentionSeverity.high => _high(brightness),
      AttentionSeverity.critical => _critical(brightness),
    };
  }

  static SeverityVisuals forNotification(
    NotificationSeverity s,
    Brightness brightness,
  ) {
    return switch (s) {
      NotificationSeverity.info => _info(brightness),
      NotificationSeverity.warning => _warning(brightness),
      NotificationSeverity.high => _high(brightness),
      NotificationSeverity.critical => _critical(brightness),
    };
  }

  // R-15 palette tokens come from ColorTokens.severity*. Foregrounds
  // are picked for AA contrast over each background variant.

  static SeverityVisuals _info(Brightness b) => SeverityVisuals._(
        color: ColorTokens.severityInfo(b),
        onColor: Colors.white,
        icon: Icons.info_outline,
        label: 'Info',
        semanticDescription: 'Informational',
      );

  static SeverityVisuals _warning(Brightness b) => SeverityVisuals._(
        color: ColorTokens.severityWarning(b),
        onColor: Colors.black,
        icon: Icons.warning_amber_outlined,
        label: 'Warning',
        semanticDescription: 'Warning',
      );

  static SeverityVisuals _high(Brightness b) => SeverityVisuals._(
        color: ColorTokens.severityHigh(b),
        onColor: Colors.white,
        icon: Icons.priority_high,
        label: 'High',
        semanticDescription: 'High severity',
      );

  static SeverityVisuals _critical(Brightness b) => SeverityVisuals._(
        color: ColorTokens.severityCritical(b),
        onColor: Colors.white,
        icon: Icons.error,
        label: 'Critical',
        semanticDescription: 'Critical severity',
      );
}
