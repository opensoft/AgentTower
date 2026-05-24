import 'package:agenttower_control_panel/domain/models/common_enums.dart';
import 'package:agenttower_control_panel/features/registry.dart';
import 'package:agenttower_control_panel/routing/route_paths.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

/// Unit tests for [WorkspaceRegistry] — review fix H8 / test lane.
void main() {
  setUp(() {
    WorkspaceRegistry.resetForTesting();
  });

  test('builderFor returns null for unregistered (workspace, subView) pairs',
      () {
    expect(
      WorkspaceRegistry.builderFor(const RoutePath(
        workspace: Workspace.agentOps,
        subViewId: 'dashboard',
      )),
      isNull,
    );
  });

  test('builderFor returns the registered builder', () {
    final marker = Container();
    WorkspaceRegistry.register(
      Workspace.agentOps,
      'dashboard',
      (_) => marker,
    );
    final builder = WorkspaceRegistry.builderFor(const RoutePath(
      workspace: Workspace.agentOps,
      subViewId: 'dashboard',
    ));
    expect(builder, isNotNull);
    // Calling the builder produces the registered widget.
    final ctx = _StubBuildContext();
    expect(identical(builder!(ctx), marker), isTrue);
  });

  test('re-register on the same key replaces the prior builder', () {
    final first = Container();
    final second = Container();
    WorkspaceRegistry.register(Workspace.agentOps, 'dashboard', (_) => first);
    WorkspaceRegistry.register(
        Workspace.agentOps, 'dashboard', (_) => second);
    final ctx = _StubBuildContext();
    final result = WorkspaceRegistry.builderFor(const RoutePath(
      workspace: Workspace.agentOps,
      subViewId: 'dashboard',
    ))!(ctx);
    expect(identical(result, second), isTrue);
  });

  test('resetForTesting clears every registration', () {
    WorkspaceRegistry.register(
        Workspace.agentOps, 'dashboard', (_) => Container());
    WorkspaceRegistry.register(
        Workspace.projectSpecs, 'projects', (_) => Container());
    WorkspaceRegistry.resetForTesting();
    expect(
      WorkspaceRegistry.builderFor(const RoutePath(
        workspace: Workspace.agentOps,
        subViewId: 'dashboard',
      )),
      isNull,
    );
    expect(
      WorkspaceRegistry.builderFor(const RoutePath(
        workspace: Workspace.projectSpecs,
        subViewId: 'projects',
      )),
      isNull,
    );
  });

  test('registrations for different (workspace, subView) pairs do not collide',
      () {
    final dashWidget = Container();
    final panesWidget = Container();
    WorkspaceRegistry.register(
        Workspace.agentOps, 'dashboard', (_) => dashWidget);
    WorkspaceRegistry.register(
        Workspace.agentOps, 'panes', (_) => panesWidget);
    final ctx = _StubBuildContext();
    expect(
      identical(
        WorkspaceRegistry.builderFor(const RoutePath(
          workspace: Workspace.agentOps,
          subViewId: 'dashboard',
        ))!(ctx),
        dashWidget,
      ),
      isTrue,
    );
    expect(
      identical(
        WorkspaceRegistry.builderFor(const RoutePath(
          workspace: Workspace.agentOps,
          subViewId: 'panes',
        ))!(ctx),
        panesWidget,
      ),
      isTrue,
    );
  });
}

/// Minimal stub `BuildContext` because the registered builders in these
/// tests never actually call `Theme.of(context)` etc — they just return
/// a pre-constructed widget reference for identity comparison.
class _StubBuildContext extends Fake implements BuildContext {}
