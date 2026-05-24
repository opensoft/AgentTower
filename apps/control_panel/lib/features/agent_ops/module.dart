import '../../core/daemon/contract_version.dart';
import '../../domain/models/common_enums.dart';
import '../registry.dart';
import 'agents/agents_view.dart';
import 'containers/containers_view.dart';
import 'dashboard/dashboard_view.dart';
import 'events/events_view.dart';
import 'health/health_view.dart';
import 'panes/panes_view.dart';
import 'queue/queue_view.dart';
import 'routes/routes_view.dart';

/// Agent Operations workspace module. T065-T076 (Phase 3 US1).
///
/// Bootstrap function called once from `main.dart` after the
/// ProviderScope is built. Registers every US1 sub-view widget with
/// the [WorkspaceRegistry] and declares each surface's minimum
/// `app_contract_version` with the [ContractRegistry] (no-ops if the
/// MVP seed already wrote the same value).
///
/// US-phase tasks in Phase 4-8 add their own modules with the same
/// shape (`project_specs/module.dart`, `testing_demo/module.dart`,
/// `settings/module.dart`).
void registerAgentOps() {
  // Per-surface contract minimums (Round-3 R-27).
  ContractRegistry.declare('agent_ops/dashboard', const ContractVersion(1, 0));
  ContractRegistry.declare('agent_ops/containers', const ContractVersion(1, 0));
  ContractRegistry.declare('agent_ops/panes', const ContractVersion(1, 0));
  ContractRegistry.declare('agent_ops/agents', const ContractVersion(1, 0));
  ContractRegistry.declare('agent_ops/events', const ContractVersion(1, 0));
  ContractRegistry.declare('agent_ops/queue', const ContractVersion(1, 0));
  ContractRegistry.declare('agent_ops/routes', const ContractVersion(1, 0));
  ContractRegistry.declare('agent_ops/health', const ContractVersion(1, 0));

  // Widget builders.
  WorkspaceRegistry.register(
    Workspace.agentOps,
    'dashboard',
    (_) => const DashboardView(),
  );
  WorkspaceRegistry.register(
    Workspace.agentOps,
    'containers',
    (_) => const ContainersView(),
  );
  WorkspaceRegistry.register(
    Workspace.agentOps,
    'panes',
    (_) => const PanesView(),
  );
  WorkspaceRegistry.register(
    Workspace.agentOps,
    'agents',
    (_) => const AgentsView(),
  );
  WorkspaceRegistry.register(
    Workspace.agentOps,
    'events',
    (_) => const EventsView(),
  );
  WorkspaceRegistry.register(
    Workspace.agentOps,
    'queue',
    (_) => const QueueView(),
  );
  WorkspaceRegistry.register(
    Workspace.agentOps,
    'routes',
    (_) => const RoutesView(),
  );
  WorkspaceRegistry.register(
    Workspace.agentOps,
    'health',
    (_) => const HealthView(),
  );
}
