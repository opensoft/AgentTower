import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/l10n/app_localizations.dart';
import 'core/l10n/l10n_wiring.dart';
import 'domain/models/common_enums.dart' as enums;
import 'features/notifications/os_native_dispatch_watcher.dart';
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
/// `flutter gen-l10n` has run (post-T009): the generated
/// `core/l10n/app_localizations.dart` exists on disk, so the
/// `AppLocalizations.delegate` import (line 4) is active and the delegate
/// is wired into [localizationsDelegates] below.
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
    // T171 — keep the FR-058 OS-native-dispatch watcher alive for the
    // app's lifetime. The provider is side-effect-only (`Provider<void>`)
    // and uses `ref.listen` internally to forward newly-arrived
    // `incoming` notifications to the dispatcher.
    ref.watch(osNativeDispatchWatcherProvider);
    return MaterialApp(
      title: 'AgentTower Control Panel',
      theme: ColorTokens.light(),
      darkTheme: ColorTokens.dark(),
      themeMode: materialThemeMode,
      localizationsDelegates: const [
        ...baseLocalizationDelegates,
        AppLocalizations.delegate,
      ],
      supportedLocales: supportedLocales,
      // Wire a single-route initial generator so exactly one shell is
      // created. The default generator splits `initialRoute` on slashes
      // and pushes one route per accumulating prefix, which (because
      // `RoutePath.parse` is tolerant) builds a 3-deep stack of duplicate
      // `AppShell` pages.
      onGenerateInitialRoutes: (initial) =>
          [AppRouter.onGenerateRoute(RouteSettings(name: initial))],
      initialRoute: AppRouter.initialRouteName,
      onGenerateRoute: AppRouter.onGenerateRoute,
    );
  }
}
