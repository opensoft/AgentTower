import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/l10n/l10n_wiring.dart';
import 'features/shell/global_banner.dart';
import 'routing/router.dart';
import 'ui/theme/color_tokens.dart';

/// Top-level `MaterialApp` widget. T045 (Phase 2 Foundational).
///
/// Wires Material 3 theme (Light + Dark + System per R-15), i18n
/// localization delegates (R-08 + R-23), the workspace routing registry
/// (T046), and the FR-002 global banner overlay (T047).
///
/// The actual `AppLocalizations.delegate` import is conditional on
/// `flutter gen-l10n` having run (post-T009). The import line is commented
/// out until then; uncomment AND add `AppLocalizations.delegate` to the
/// delegates list when the codegen output exists.
class AgentTowerControlPanel extends ConsumerWidget {
  const AgentTowerControlPanel({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return MaterialApp(
      title: 'AgentTower Control Panel',
      theme: ColorTokens.light(),
      darkTheme: ColorTokens.dark(),
      themeMode: ThemeMode.system, // bound to Settings in T143
      localizationsDelegates: const [
        ...baseLocalizationDelegates,
        // AppLocalizations.delegate, // uncomment after flutter gen-l10n
      ],
      supportedLocales: supportedLocales,
      onGenerateRoute: AppRouter.onGenerateRoute,
      builder: (context, child) {
        // Inject the FR-002 banner above every route.
        return Column(
          children: [
            const GlobalBanner(),
            Expanded(child: child ?? const SizedBox.shrink()),
          ],
        );
      },
    );
  }
}
