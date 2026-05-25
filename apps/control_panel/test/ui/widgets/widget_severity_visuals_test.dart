import 'package:agenttower_control_panel/domain/models/common_enums.dart'
    hide ThemeMode;
import 'package:agenttower_control_panel/domain/severity.dart';
import 'package:agenttower_control_panel/ui/theme/color_tokens.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Widget tests for [SeverityVisuals] — the R-15 / R-22 redundant
/// "color + icon + text" envelope. T150 (Phase 9 cross-cutting tests).
///
/// Covers every [AttentionSeverity], [DriftSeverity], and
/// [NotificationSeverity] tier in both light and dark theme variants,
/// and asserts each tier emits:
///   - the expected icon symbol
///   - the expected background color (per [ColorTokens])
///   - the expected foreground (`onColor`) pairing
///   - a non-empty text label + semantic description (R-22 redundancy)
///
/// The R-22 triad is the load-bearing invariant: colorblind operators
/// must get the same signal from the icon AND the text label, with
/// color as a third reinforcing channel.
void main() {
  group('SeverityVisuals — Attention × light theme', () {
    for (final entry in _expectedTiers().entries) {
      final severity = entry.key;
      final spec = entry.value;
      testWidgets('attention.${severity.wireValue} (light) emits expected '
          'icon + colors + label', (tester) async {
        await _pumpUnderBrightness(tester, Brightness.light, (brightness) {
          final v = SeverityVisuals.forAttention(severity, brightness);
          expect(
            v.icon,
            spec.icon,
            reason: 'icon mismatch for ${severity.wireValue}',
          );
          expect(
            v.color,
            spec.lightColor,
            reason: 'background color mismatch for ${severity.wireValue}',
          );
          expect(
            v.onColor,
            spec.onColor,
            reason: 'foreground color mismatch for ${severity.wireValue}',
          );
          expect(v.label, spec.label);
          expect(v.semanticDescription, spec.semanticDescription);
          // R-22 redundancy: all three channels MUST be populated.
          expect(v.label, isNotEmpty);
          expect(v.semanticDescription, isNotEmpty);
        });
      });
    }
  });

  group('SeverityVisuals — Attention × dark theme', () {
    for (final entry in _expectedTiers().entries) {
      final severity = entry.key;
      final spec = entry.value;
      testWidgets('attention.${severity.wireValue} (dark) emits expected '
          'icon + colors + label', (tester) async {
        await _pumpUnderBrightness(tester, Brightness.dark, (brightness) {
          final v = SeverityVisuals.forAttention(severity, brightness);
          expect(v.icon, spec.icon);
          expect(
            v.color,
            spec.darkColor,
            reason: 'dark-bg color mismatch for ${severity.wireValue}',
          );
          expect(v.onColor, spec.onColor);
          expect(v.label, spec.label);
        });
      });
    }
  });

  group('SeverityVisuals — Drift parity with Attention palette', () {
    testWidgets('forDrift returns the same triad as forAttention for the '
        'matching tier (R-15 palette sharing)', (tester) async {
      await _pumpUnderBrightness(tester, Brightness.light, (brightness) {
        for (final pair in const <List<dynamic>>[
          [DriftSeverity.info, AttentionSeverity.info],
          [DriftSeverity.warning, AttentionSeverity.warning],
          [DriftSeverity.high, AttentionSeverity.high],
          [DriftSeverity.critical, AttentionSeverity.critical],
        ]) {
          final drift = SeverityVisuals.forDrift(
            pair[0] as DriftSeverity,
            brightness,
          );
          final attn = SeverityVisuals.forAttention(
            pair[1] as AttentionSeverity,
            brightness,
          );
          expect(drift.icon, attn.icon);
          expect(drift.color, attn.color);
          expect(drift.onColor, attn.onColor);
          expect(drift.label, attn.label);
        }
      });
    });
  });

  group('SeverityVisuals — Notification parity with Attention palette', () {
    testWidgets('forNotification returns the same triad as forAttention for '
        'the matching tier', (tester) async {
      await _pumpUnderBrightness(tester, Brightness.dark, (brightness) {
        for (final pair in const <List<dynamic>>[
          [NotificationSeverity.info, AttentionSeverity.info],
          [NotificationSeverity.warning, AttentionSeverity.warning],
          [NotificationSeverity.high, AttentionSeverity.high],
          [NotificationSeverity.critical, AttentionSeverity.critical],
        ]) {
          final note = SeverityVisuals.forNotification(
            pair[0] as NotificationSeverity,
            brightness,
          );
          final attn = SeverityVisuals.forAttention(
            pair[1] as AttentionSeverity,
            brightness,
          );
          expect(note.icon, attn.icon);
          expect(note.color, attn.color);
          expect(note.onColor, attn.onColor);
          expect(note.label, attn.label);
        }
      });
    });
  });

  group('SeverityVisuals — labels are distinct across tiers (R-22 '
      'colorblind-redundancy)', () {
    testWidgets('every tier label + icon is unique within the enum',
        (tester) async {
      await _pumpUnderBrightness(tester, Brightness.light, (brightness) {
        final labels = <String>{};
        final icons = <IconData>{};
        for (final s in AttentionSeverity.values) {
          final v = SeverityVisuals.forAttention(s, brightness);
          expect(
            labels.add(v.label),
            isTrue,
            reason: 'duplicate label across severity tiers: ${v.label}',
          );
          expect(
            icons.add(v.icon),
            isTrue,
            reason: 'duplicate icon across severity tiers: ${v.icon}',
          );
        }
      });
    });
  });
}

/// Pumps a tiny [MaterialApp] under [brightness] and runs [body] with
/// the resolved [Brightness] (taken from `MediaQuery.platformBrightnessOf`
/// once the widget tree has mounted). Body assertions run inside a
/// [Builder] so we are evaluating against the same `Theme.of(context)`
/// brightness an actual surface would see.
Future<void> _pumpUnderBrightness(
  WidgetTester tester,
  Brightness brightness,
  void Function(Brightness brightness) body,
) async {
  await tester.pumpWidget(
    MaterialApp(
      theme: ColorTokens.light(),
      darkTheme: ColorTokens.dark(),
      themeMode: brightness == Brightness.light
          ? ThemeMode.light
          : ThemeMode.dark,
      home: Builder(
        builder: (context) {
          // Resolve via Theme so we are exercising the same lookup an
          // actual surface chip would do.
          final resolved = Theme.of(context).brightness;
          body(resolved);
          return const SizedBox.shrink();
        },
      ),
    ),
  );
}

/// Static reference of the R-15 expected mappings. Mirrors
/// `lib/domain/severity.dart` + `lib/ui/theme/color_tokens.dart`; if the
/// production palette changes these constants must change in lockstep.
Map<AttentionSeverity, _ExpectedSpec> _expectedTiers() => {
      AttentionSeverity.info: const _ExpectedSpec(
        icon: Icons.info_outline,
        lightColor: ColorTokens.infoLight,
        darkColor: ColorTokens.infoDark,
        onColor: Colors.white,
        label: 'Info',
        semanticDescription: 'Informational',
      ),
      AttentionSeverity.warning: const _ExpectedSpec(
        icon: Icons.warning_amber_outlined,
        lightColor: ColorTokens.warningLight,
        darkColor: ColorTokens.warningDark,
        onColor: Colors.black,
        label: 'Warning',
        semanticDescription: 'Warning',
      ),
      AttentionSeverity.high: const _ExpectedSpec(
        icon: Icons.priority_high,
        lightColor: ColorTokens.highLight,
        darkColor: ColorTokens.highDark,
        onColor: Colors.white,
        label: 'High',
        semanticDescription: 'High severity',
      ),
      AttentionSeverity.critical: const _ExpectedSpec(
        icon: Icons.error,
        lightColor: ColorTokens.criticalLight,
        darkColor: ColorTokens.criticalDark,
        onColor: Colors.white,
        label: 'Critical',
        semanticDescription: 'Critical severity',
      ),
    };

class _ExpectedSpec {
  const _ExpectedSpec({
    required this.icon,
    required this.lightColor,
    required this.darkColor,
    required this.onColor,
    required this.label,
    required this.semanticDescription,
  });

  final IconData icon;
  final Color lightColor;
  final Color darkColor;
  final Color onColor;
  final String label;
  final String semanticDescription;
}
