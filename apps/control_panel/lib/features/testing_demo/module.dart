import '../../core/daemon/contract_version.dart';
import '../../domain/models/common_enums.dart';
import '../registry.dart';
import 'available_validation/available_validation_view.dart';
import 'demo_readiness/demo_readiness_view.dart';
import 'runs/runs_view.dart';

/// Testing & Demo workspace module. T124-T129 (Phase 7 US5).
///
/// Registers the three FR-046 sub-views in their canonical order:
/// Available Validation, Runs, Demo Readiness.
void registerTestingDemo() {
  ContractRegistry.declare(
    'testing_demo/available_validation',
    const ContractVersion(1, 0),
  );
  ContractRegistry.declare(
    'testing_demo/runs',
    const ContractVersion(1, 0),
  );
  ContractRegistry.declare(
    'testing_demo/demo_readiness',
    const ContractVersion(1, 0),
  );

  WorkspaceRegistry.register(
    Workspace.testingDemo,
    'available_validation',
    (_) => const AvailableValidationView(),
  );
  WorkspaceRegistry.register(
    Workspace.testingDemo,
    'runs',
    (_) => const RunsView(),
  );
  WorkspaceRegistry.register(
    Workspace.testingDemo,
    'demo_readiness',
    (_) => const DemoReadinessView(),
  );
}
