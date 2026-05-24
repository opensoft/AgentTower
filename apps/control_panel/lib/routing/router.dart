import 'package:flutter/material.dart';

import '../domain/models/common_enums.dart';
import '../features/shell/app_shell.dart';
import 'route_paths.dart';

/// Workspace + sub-view routing. T046 + review fix A1.
///
/// MVP uses [Navigator.onGenerateRoute] with a single shell route. Route
/// names follow [RoutePath]'s `/workspace/subview` scheme so deep links
/// (e.g. launched from a browser-handled `agenttower://` URI in a future
/// version) resolve consistently. The shell parses the name once, builds
/// [AppShell] with the resolved [RoutePath], and lets the workspace
/// surface render itself.
///
/// Why named routes instead of `go_router`: at MVP the route surface is
/// tiny (4 workspaces × ≤ 8 sub-views), no nested navigation is needed,
/// and we'd rather not pay the dependency-graph cost of go_router until
/// per-pane deep links land in a post-MVP iteration.
class AppRouter {
  AppRouter._();

  /// Workspace → ordered list of sub-view ids — kept here as a back-compat
  /// re-export so older imports of `AppRouter.subViewsByWorkspace` still
  /// compile while callers migrate to [RoutePath.subViewsFor].
  static const Map<Workspace, List<String>> subViewsByWorkspace =
      RoutePath.subViewsByWorkspace;

  /// Default sub-view for each workspace (the first entry).
  static String defaultSubView(Workspace w) =>
      RoutePath.subViewsFor(w).first;

  /// `Navigator.onGenerateRoute` entry point. Parses the requested route
  /// name into a [RoutePath] and renders [AppShell] with it.
  static Route<dynamic> onGenerateRoute(RouteSettings settings) {
    final route = RoutePath.parse(settings.name);
    return MaterialPageRoute<void>(
      settings: RouteSettings(
        name: route.toRouteString(),
        arguments: settings.arguments,
      ),
      builder: (_) => AppShell(route: route),
    );
  }

  /// Initial route used by `MaterialApp.onGenerateInitialRoutes` (and by
  /// the deep-link handler when it lands).
  static String get initialRouteName => RoutePath.home.toRouteString();
}
