import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';

/// Global keyboard shortcut bindings. T034.
///
/// Per FR-007: Ctrl+P (Linux/Windows) / Cmd+P (macOS) opens the project switcher.
/// Per FR-075: Ctrl+K (Linux/Windows) / Cmd+K (macOS) opens the command palette.
///
/// Platform-aware: on macOS we use Cmd (meta) instead of Ctrl.
class GlobalShortcuts {
  GlobalShortcuts._();

  /// Wraps [child] with a [Shortcuts] widget binding the two global activators
  /// to [OpenProjectSwitcherIntent] and [OpenCommandPaletteIntent].
  static Widget wrap({required Widget child}) {
    return Shortcuts(
      shortcuts: <ShortcutActivator, Intent>{
        // FR-007: project switcher
        const SingleActivator(LogicalKeyboardKey.keyP, control: true):
            const OpenProjectSwitcherIntent(),
        const SingleActivator(LogicalKeyboardKey.keyP, meta: true):
            const OpenProjectSwitcherIntent(),
        // FR-075: command palette
        const SingleActivator(LogicalKeyboardKey.keyK, control: true):
            const OpenCommandPaletteIntent(),
        const SingleActivator(LogicalKeyboardKey.keyK, meta: true):
            const OpenCommandPaletteIntent(),
      },
      child: child,
    );
  }
}

/// Intent dispatched when Ctrl/Cmd+P is pressed.
class OpenProjectSwitcherIntent extends Intent {
  const OpenProjectSwitcherIntent();
}

/// Intent dispatched when Ctrl/Cmd+K is pressed.
class OpenCommandPaletteIntent extends Intent {
  const OpenCommandPaletteIntent();
}
