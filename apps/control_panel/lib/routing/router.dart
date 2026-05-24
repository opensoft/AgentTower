import 'package:flutter/material.dart';

import '../domain/models/common_enums.dart';

/// Workspace + sub-view routing registry. T046 (Phase 2 Foundational).
///
/// Top-level routes for the four workspaces per FR-006:
///   agent_ops, project_specs, testing_demo, settings
///
/// Sub-view ordering per Round-3 R-39 is FIXED at MVP (no operator-reorder).
/// Each workspace's sub-views are appended in FR-011 / FR-023 / FR-046 order.
///
/// At MVP this uses simple [Navigator] routes; if future complexity warrants,
/// swap in `go_router`.
class AppRouter {
  AppRouter._();

  /// Workspace → ordered list of sub-view ids (per FR-011, FR-023, FR-046).
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

  /// Default sub-view for each workspace (the first entry).
  static String defaultSubView(Workspace w) => subViewsByWorkspace[w]!.first;

  /// Placeholder route generator. Each workspace's actual feature widgets
  /// land in their respective US-phase tasks (T065+ US1, T087+ US2, etc.).
  static Route<dynamic>? onGenerateRoute(RouteSettings settings) {
    return MaterialPageRoute(
      settings: settings,
      builder: (_) => Scaffold(
        appBar: AppBar(title: Text('Route: ${settings.name ?? "/"}')),
        body: Center(
          child: Text(
            'Workspace + sub-view widgets land in Phase 3+ (US1..US6 tasks).',
            textAlign: TextAlign.center,
          ),
        ),
      ),
    );
  }
}
