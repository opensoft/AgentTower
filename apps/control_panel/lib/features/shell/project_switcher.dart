import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/l10n/app_localizations.dart';

/// Project switcher — invoked by Ctrl+P (Linux/Windows) / Cmd+P (macOS)
/// per FR-007, plus a visible UI affordance.
///
/// T048 (Phase 2 Foundational). The project list itself loads in Phase 4
/// (US2 T082..T087); this widget owns the keyboard shortcut + modal scaffold.
class ProjectSwitcher extends StatelessWidget {
  const ProjectSwitcher({super.key});

  /// Single global shortcut per FR-007: Ctrl+P on Linux/Windows, Cmd+P on macOS.
  static const ShortcutActivator activator = SingleActivator(
    LogicalKeyboardKey.keyP,
    control: true, // wrapped by `meta` on macOS via PlatformMenuBar
  );

  static Future<void> show(BuildContext context) async {
    await showDialog<void>(
      context: context,
      barrierDismissible: true,
      builder: (dialogCtx) => Dialog(
        child: SizedBox(
          width: 480,
          height: 360,
          child: Center(
            child: Text(
              AppLocalizations.of(dialogCtx).projectSwitcherDialogPlaceholder,
              textAlign: TextAlign.center,
            ),
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return IconButton(
      tooltip: AppLocalizations.of(context).projectSwitcherTooltip,
      icon: const Icon(Icons.workspaces_outlined),
      onPressed: () => show(context),
    );
  }
}
