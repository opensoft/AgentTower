import '../domain/models/common_enums.dart';

/// Typed parser/serializer for workspace + sub-view deep-link paths.
/// T046 + review fix A1.
///
/// Routes are encoded as `/<workspace_wire>/<subview_id>`. Examples:
///   /agent_ops/dashboard
///   /project_specs/specs
///   /testing_demo/runs
///   /settings/connection
///
/// Unknown workspaces fall back to [Workspace.agentOps]; unknown sub-views
/// fall back to the first sub-view of the resolved workspace. Bare `/` or
/// `""` lands on `/agent_ops/dashboard`.
class RoutePath {
  const RoutePath({
    required this.workspace,
    required this.subViewId,
  });

  final Workspace workspace;
  final String subViewId;

  static const RoutePath home =
      RoutePath(workspace: Workspace.agentOps, subViewId: 'dashboard');

  static const Map<String, Workspace> _wireToWorkspace = {
    'agent_ops': Workspace.agentOps,
    'project_specs': Workspace.projectSpecs,
    'testing_demo': Workspace.testingDemo,
    'settings': Workspace.settings,
  };

  static String _wireFor(Workspace w) => switch (w) {
        Workspace.agentOps => 'agent_ops',
        Workspace.projectSpecs => 'project_specs',
        Workspace.testingDemo => 'testing_demo',
        Workspace.settings => 'settings',
      };

  /// Per-workspace sub-view ordering per Round-3 R-39 (fixed at MVP).
  static const Map<Workspace, List<String>> subViewsByWorkspace = {
    Workspace.agentOps: [
      'dashboard',
      'containers',
      'panes',
      'agents',
      'events',
      'queue',
      'routes',
      'health',
    ],
    Workspace.projectSpecs: [
      'projects',
      'current_work',
      'specs',
      'changes',
      'drift',
    ],
    Workspace.testingDemo: [
      'available_validation',
      'runs',
      'demo_readiness',
    ],
    Workspace.settings: [
      'display',
      'notifications',
      'connection',
      'privacy',
      'diagnostics',
    ],
  };

  static List<String> subViewsFor(Workspace w) => subViewsByWorkspace[w]!;

  /// Parses a string route into a [RoutePath]. Tolerant of:
  ///   - missing leading slash
  ///   - trailing slash
  ///   - unknown workspace (falls back to home)
  ///   - unknown subview within a known workspace (falls back to first)
  factory RoutePath.parse(String? raw) {
    final input = (raw ?? '/').trim();
    if (input.isEmpty || input == '/') return home;
    final segments = input
        .split('/')
        .where((s) => s.isNotEmpty)
        .toList(growable: false);
    if (segments.isEmpty) return home;
    final workspace = _wireToWorkspace[segments[0]] ?? Workspace.agentOps;
    final defaultSubView = subViewsFor(workspace).first;
    final candidateSubView = segments.length > 1 ? segments[1] : defaultSubView;
    final subView = subViewsFor(workspace).contains(candidateSubView)
        ? candidateSubView
        : defaultSubView;
    return RoutePath(workspace: workspace, subViewId: subView);
  }

  /// Serializes back to `/workspace/subview` form.
  String toRouteString() => '/${_wireFor(workspace)}/$subViewId';

  @override
  String toString() => 'RoutePath(${toRouteString()})';

  @override
  bool operator ==(Object other) =>
      other is RoutePath &&
      other.workspace == workspace &&
      other.subViewId == subViewId;

  @override
  int get hashCode => Object.hash(workspace, subViewId);
}
