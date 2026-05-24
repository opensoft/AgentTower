import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../domain/models/common_enums.dart';
import '../../routing/route_paths.dart';
import '../project_specs/module.dart' show registerProjectSpecsPaletteCommands;
import '../settings/module.dart' show registerSettingsPaletteCommands;
import '../registry.dart';
import 'global_banner.dart';
import 'project_switcher.dart';

/// Top-level chrome around the current workspace + sub-view. T047/T048 +
/// review fix A1 + L3.
///
/// Layout (per FR-006 + accessibility R-22):
///   ┌────────────────────────────────────────────────────────────┐
///   │ Global banner overlay (only visible on FR-002 incompat.)   │
///   ├──────────────┬─────────────────────────────────────────────┤
///   │ Workspace    │ Sub-view tab strip                          │
///   │ rail         ├─────────────────────────────────────────────┤
///   │ (4 entries)  │ Sub-view body — replaced by feature widgets │
///   │              │ in each US-phase task (T065+ US1, etc.)    │
///   └──────────────┴─────────────────────────────────────────────┘
///
/// The shell is route-driven: the `RoutePath` parsed in `onGenerateRoute`
/// selects the rail item and the tab strip's selected sub-view. Picking
/// a different workspace or sub-view pushes a new named route so deep
/// links + browser-style back/forward work uniformly.
class AppShell extends ConsumerWidget {
  const AppShell({super.key, required this.route});

  final RoutePath route;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final subViews = RoutePath.subViewsFor(route.workspace);
    final selectedSubViewIdx = subViews.indexOf(route.subViewId);

    // Swarm-review CR-5 + Phase-9 T144/T145: register palette commands.
    // Deferred to a microtask because Riverpod forbids state mutation
    // during a widget build. `register` is idempotent on `id`.
    Future<void>.microtask(() {
      if (!ref.context.mounted) return;
      registerProjectSpecsPaletteCommands(ref);
      registerSettingsPaletteCommands(ref);
    });

    return Scaffold(
      appBar: AppBar(
        title: Text(_workspaceLabel(route.workspace)),
        actions: const [
          ProjectSwitcher(),
          SizedBox(width: 8),
        ],
      ),
      body: Column(
        children: [
          const GlobalBanner(),
          Expanded(
            child: Row(
              children: [
                NavigationRail(
                  selectedIndex: route.workspace.index,
                  onDestinationSelected: (i) {
                    final next = Workspace.values[i];
                    Navigator.of(context).pushReplacementNamed(
                      RoutePath(
                        workspace: next,
                        subViewId: RoutePath.subViewsFor(next).first,
                      ).toRouteString(),
                    );
                  },
                  labelType: NavigationRailLabelType.all,
                  destinations: const [
                    NavigationRailDestination(
                      icon: Icon(Icons.dashboard_outlined),
                      selectedIcon: Icon(Icons.dashboard),
                      label: Text('Agent Ops'),
                    ),
                    NavigationRailDestination(
                      icon: Icon(Icons.folder_outlined),
                      selectedIcon: Icon(Icons.folder),
                      label: Text('Project + Specs'),
                    ),
                    NavigationRailDestination(
                      icon: Icon(Icons.science_outlined),
                      selectedIcon: Icon(Icons.science),
                      label: Text('Testing + Demo'),
                    ),
                    NavigationRailDestination(
                      icon: Icon(Icons.settings_outlined),
                      selectedIcon: Icon(Icons.settings),
                      label: Text('Settings'),
                    ),
                  ],
                ),
                const VerticalDivider(width: 1),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      _SubViewStrip(
                        subViews: subViews,
                        selectedIndex:
                            selectedSubViewIdx < 0 ? 0 : selectedSubViewIdx,
                        onSelected: (i) {
                          Navigator.of(context).pushReplacementNamed(
                            RoutePath(
                              workspace: route.workspace,
                              subViewId: subViews[i],
                            ).toRouteString(),
                          );
                        },
                      ),
                      const Divider(height: 1),
                      Expanded(
                        child: Builder(
                          builder: (ctx) {
                            // Each US-phase task registers its
                            // workspace+sub-view widget with the
                            // [WorkspaceRegistry]. If no widget is
                            // registered yet for `route`, fall back to
                            // the labelled placeholder so smoke tests +
                            // operators see what's pending.
                            final builder =
                                WorkspaceRegistry.builderFor(route);
                            return builder != null
                                ? builder(ctx)
                                : _SubViewPlaceholder(route: route);
                          },
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  static String _workspaceLabel(Workspace w) => switch (w) {
        Workspace.agentOps => 'Agent Operations',
        Workspace.projectSpecs => 'Project + Specs',
        Workspace.testingDemo => 'Testing + Demo',
        Workspace.settings => 'Settings',
      };

  /// Public hook for placeholder widgets — used by `_SubViewPlaceholder`
  /// and by feature widgets that want to title themselves consistently
  /// with the shell's AppBar.
  static String workspaceLabel(Workspace w) => _workspaceLabel(w);
}

/// Placeholder body shown until each US-phase task replaces it with the
/// real workspace widget. Per the test harness expectations, the
/// placeholder MUST render the current sub-view id verbatim so smoke
/// tests can assert against it without booting any feature module.
class _SubViewPlaceholder extends StatelessWidget {
  const _SubViewPlaceholder({required this.route});
  final RoutePath route;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Text(
          '${AppShell._workspaceLabel(route.workspace)} → ${route.subViewId}\n'
          '(Feature widget lands in its US-phase task.)',
          textAlign: TextAlign.center,
        ),
      ),
    );
  }
}

/// Horizontal sub-view strip rendered above the sub-view body. Each
/// segment is a tappable [FilterChip]; the selected one is highlighted
/// via the theme's primary container. We deliberately don't use [TabBar]
/// here because no `TabBarView` exists — the sub-view body is replaced
/// via `Navigator.pushReplacementNamed`, not by a swipable view, so a
/// `TabController` (and its vsync requirement) would be dead weight.
class _SubViewStrip extends StatelessWidget {
  const _SubViewStrip({
    required this.subViews,
    required this.selectedIndex,
    required this.onSelected,
  });

  final List<String> subViews;
  final int selectedIndex;
  final ValueChanged<int> onSelected;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Theme.of(context).colorScheme.surface,
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        child: Row(
          children: [
            for (var i = 0; i < subViews.length; i++) ...[
              ChoiceChip(
                label: Text(subViews[i]),
                selected: i == selectedIndex,
                onSelected: (_) => onSelected(i),
              ),
              if (i != subViews.length - 1) const SizedBox(width: 8),
            ],
          ],
        ),
      ),
    );
  }
}
