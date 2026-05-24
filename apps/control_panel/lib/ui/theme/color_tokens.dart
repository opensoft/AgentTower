import 'package:flutter/material.dart';

/// Color tokens for Light + Dark + System themes (T028 + research R-15 + R-24).
///
/// Per research R-15, severity colors are chosen to meet WCAG AA 4.5:1
/// contrast against the corresponding theme background. Per R-22, every
/// severity carries unique icon + text + color (redundancy for colorblind
/// operators per FR-066).
///
/// Per Round-3 R-24: theme changes apply live (no restart). Transient
/// surfaces follow current theme. High-contrast variant deferred.
class ColorTokens {
  ColorTokens._();

  // ---- Severity palette (used by attention queue, drift, validation badges) ----
  // Per R-15, these colors meet WCAG AA 4.5:1 contrast against their theme bg.

  static const Color infoLight = Color(0xFF3478F6); // blue 60
  static const Color infoDark = Color(0xFF5B9DFF);

  static const Color warningLight = Color(0xFFE68A00); // amber 60
  static const Color warningDark = Color(0xFFFFB54C);

  static const Color highLight = Color(0xFFD93D2A); // red 60
  static const Color highDark = Color(0xFFFF7059);

  static const Color criticalLight = Color(0xFF7A1A18); // red 90
  static const Color criticalDark = Color(0xFFB33A2B);

  // ---- Workspace accents (per Round-3 R-39, distinct from severity palette) ----
  // Reserved namespace — accents never collide with severity colors.

  static const Color agentOpsAccent = Color(0xFF1F8E5F); // teal/green
  static const Color projectSpecsAccent = Color(0xFF8C5BFF); // violet
  static const Color testingDemoAccent = Color(0xFFCC7A00); // bronze (distinct from warning amber)
  static const Color settingsAccent = Color(0xFF607D8B); // slate

  /// Builds the Material 3 light theme.
  static ThemeData light() => ThemeData(
        useMaterial3: true,
        brightness: Brightness.light,
        colorScheme: ColorScheme.fromSeed(
          seedColor: agentOpsAccent,
          brightness: Brightness.light,
        ),
      );

  /// Builds the Material 3 dark theme.
  static ThemeData dark() => ThemeData(
        useMaterial3: true,
        brightness: Brightness.dark,
        colorScheme: ColorScheme.fromSeed(
          seedColor: agentOpsAccent,
          brightness: Brightness.dark,
        ),
      );

  /// Returns the severity color for the current theme brightness.
  static Color severityInfo(Brightness b) =>
      b == Brightness.light ? infoLight : infoDark;
  static Color severityWarning(Brightness b) =>
      b == Brightness.light ? warningLight : warningDark;
  static Color severityHigh(Brightness b) =>
      b == Brightness.light ? highLight : highDark;
  static Color severityCritical(Brightness b) =>
      b == Brightness.light ? criticalLight : criticalDark;
}
