// Hide Material's ThemeMode in case any helper here imports it
// indirectly — keeps the Workspace enum + our domain ThemeMode
// unambiguous.
import 'package:flutter/material.dart' hide ThemeMode;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/daemon/contract_version.dart';
import '../../core/shortcuts/command_palette.dart';
import '../../domain/models/common_enums.dart';
import '../../routing/route_paths.dart';
import '../registry.dart';
import 'settings_view.dart';

/// Settings workspace module. T143 + T144 + T145 (Phase 9).
///
/// Registers a single `SettingsView` widget for all five Settings
/// sub-views (`display`, `notifications`, `connection`, `privacy`,
/// `diagnostics`). The sub-view id is conveyed via the
/// `initialSection` parameter so future per-section deep links land
/// the operator on the right block.
void registerSettings() {
  ContractRegistry.declare('settings/display', const ContractVersion(1, 0));
  ContractRegistry.declare(
    'settings/notifications',
    const ContractVersion(1, 0),
  );
  ContractRegistry.declare(
    'settings/connection',
    const ContractVersion(1, 0),
  );
  ContractRegistry.declare('settings/privacy', const ContractVersion(1, 0));
  ContractRegistry.declare(
    'settings/diagnostics',
    const ContractVersion(1, 0),
  );

  for (final subView in const [
    'display',
    'notifications',
    'connection',
    'privacy',
    'diagnostics',
  ]) {
    WorkspaceRegistry.register(
      Workspace.settings,
      subView,
      (_) => SettingsView(initialSection: subView),
    );
  }
}

/// FR-075 + FR-009: palette commands for Doctor / Diagnostics / open
/// Settings. T144 + T145.
void registerSettingsPaletteCommands(WidgetRef ref) {
  final notifier = ref.read(commandRegistryProvider.notifier);

  notifier.register(PaletteCommand(
    id: 'settings.goto',
    label: 'Open Settings',
    category: 'Navigate',
    invoke: (context) async {
      await Navigator.of(context).pushNamed(
        const RoutePath(
          workspace: Workspace.settings,
          subViewId: 'display',
        ).toRouteString(),
      );
    },
  ));

  notifier.register(PaletteCommand(
    id: 'settings.run_doctor',
    label: 'Run doctor / preflight',
    category: 'Diagnostics',
    invoke: (context) async {
      // Route to Settings/diagnostics where the Doctor action lives.
      // Per FR-009 the doctor MUST be reachable from the palette;
      // surfacing it via the Settings page keeps a single source of
      // operator-visible doctor output.
      await Navigator.of(context).pushNamed(
        const RoutePath(
          workspace: Workspace.settings,
          subViewId: 'diagnostics',
        ).toRouteString(),
      );
    },
  ));

  notifier.register(PaletteCommand(
    id: 'settings.copy_diagnostics_bundle',
    label: 'Copy diagnostics bundle',
    category: 'Diagnostics',
    invoke: (context) async {
      await Navigator.of(context).pushNamed(
        const RoutePath(
          workspace: Workspace.settings,
          subViewId: 'diagnostics',
        ).toRouteString(),
      );
    },
  ));

  notifier.register(PaletteCommand(
    id: 'settings.open_log_folder',
    label: 'Open log folder',
    category: 'Diagnostics',
    invoke: (context) async {
      await Navigator.of(context).pushNamed(
        const RoutePath(
          workspace: Workspace.settings,
          subViewId: 'diagnostics',
        ).toRouteString(),
      );
    },
  ));
}
