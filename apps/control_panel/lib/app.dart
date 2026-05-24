import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/l10n/l10n_wiring.dart';
import 'domain/models/common_enums.dart' as enums;
import 'features/settings/providers.dart';
import 'routing/router.dart';
import 'ui/theme/color_tokens.dart';

/// Top-level `MaterialApp` widget. T045 (Phase 2 Foundational).
///
/// Wires Material 3 theme (Light + Dark + System per R-15), i18n
/// localization delegates (R-08 + R-23), and the workspace routing
/// registry (T046).
///
/// The FR-002 global banner is rendered inside [AppShell] instead of in a
/// `MaterialApp.builder` Column wrapper (review fix M-A1) — the previous
/// builder Column forced every route to live inside an extra Column,
/// which broke widgets that expected to fill the full canvas.
///
/// The actual `AppLocalizations.delegate` import is conditional on
/// `flutter gen-l10n` having run (post-T009). The import line is commented
/// out until then; uncomment AND add `AppLocalizations.delegate` to the
/// delegates list when the codegen output exists.
class AgentTowerControlPanel extends ConsumerWidget {
  const AgentTowerControlPanel({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Round-3 analyze U1: bind MaterialApp.themeMode to the live
    // Settings value so toggling theme in Settings applies
    // immediately. The wire-aligned domain `ThemeMode` maps 1:1
    // to Flutter's `ThemeMode`.
    final theme = ref.watch(settingsProvider.select((s) => s.theme));
    final materialThemeMode = switch (theme) {
      enums.ThemeMode.light => ThemeMode.light,
      enums.ThemeMode.dark => ThemeMode.dark,
      enums.ThemeMode.system => ThemeMode.system,
    };
    return MaterialApp(
      title: 'AgentTower Control Panel',
      theme: ColorTokens.light(),
      darkTheme: ColorTokens.dark(),
      themeMode: materialThemeMode,
      localizationsDelegates: const [
        ...baseLocalizationDelegates,
        // AppLocalizations.delegate, // uncomment after flutter gen-l10n
      ],
      supportedLocales: supportedLocales,
      initialRoute: AppRouter.initialRouteName,
      onGenerateRoute: AppRouter.onGenerateRoute,
    );
  }
}
