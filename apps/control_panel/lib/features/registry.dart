import 'package:flutter/material.dart';

import '../domain/models/common_enums.dart';
import '../routing/route_paths.dart';

/// Workspace + sub-view widget registry. T065+ (Phase 3 US1) — the
/// `AppShell` looks up `(workspace, subViewId)` here to find the
/// real widget for the current route. Feature modules register their
/// widgets via [WorkspaceRegistry.register] at module load.
///
/// Why a registry instead of a giant switch in `AppShell`:
///   - keeps `AppShell` agnostic of which US-phase tasks have landed
///   - lets a future feature flag swap out a widget without touching
///     the shell
///   - makes "which sub-views have actual widgets vs. placeholders"
///     trivially auditable: anything not in the map renders the
///     placeholder.
class WorkspaceRegistry {
  WorkspaceRegistry._();

  static final Map<_Key, WidgetBuilder> _builders = {};

  /// Registers the widget builder for the given workspace + sub-view.
  /// Idempotent on the (workspace, subViewId) pair — re-registering
  /// replaces the previous builder.
  static void register(
    Workspace workspace,
    String subViewId,
    WidgetBuilder builder,
  ) {
    _builders[_Key(workspace, subViewId)] = builder;
  }

  /// Returns the registered builder for [route] if any, else `null`.
  /// `AppShell` falls back to its placeholder when this returns null.
  static WidgetBuilder? builderFor(RoutePath route) =>
      _builders[_Key(route.workspace, route.subViewId)];

  /// Test-only: clears all registrations.
  static void resetForTesting() => _builders.clear();
}

class _Key {
  const _Key(this.workspace, this.subViewId);
  final Workspace workspace;
  final String subViewId;

  @override
  bool operator ==(Object other) =>
      other is _Key &&
      other.workspace == workspace &&
      other.subViewId == subViewId;

  @override
  int get hashCode => Object.hash(workspace, subViewId);
}
