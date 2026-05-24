import '../../core/daemon/contract_version.dart';
import '../../domain/models/common_enums.dart';
import '../registry.dart';
import 'changes/changes_view.dart';
import 'current_work/current_work_view.dart';
import 'drift/drift_view.dart';
import 'projects/projects_view.dart';
import 'specs/specs_view.dart';

/// Project + Specs workspace module. T087-T094 (Phase 4 US2).
///
/// Bootstrap function called once from `main.dart` (alongside
/// [registerAgentOps]). Registers every Project + Specs sub-view
/// widget with the [WorkspaceRegistry] and declares each surface's
/// minimum `app_contract_version` with the [ContractRegistry].
///
/// The "drift" sub-view registration lands in Phase 6 (US4); leaving
/// it unregistered here keeps the placeholder rendered for that
/// surface until the drift work is implemented.
void registerProjectSpecs() {
  // Per-surface contract minimums (Round-3 R-27). FEAT-011 v1.0 does
  // not yet expose `app.project.*` / `app.feature_change.*`; once
  // those land in a v1.x bump, raise these minimums to (1, x). For
  // MVP we leave the declared minimum at (1, 0) so the surfaces
  // render against today's daemon and degrade per FR-002 if the
  // methods are absent.
  ContractRegistry.declare(
    'project_specs/projects',
    const ContractVersion(1, 0),
  );
  ContractRegistry.declare(
    'project_specs/current_work',
    const ContractVersion(1, 0),
  );
  ContractRegistry.declare(
    'project_specs/specs',
    const ContractVersion(1, 0),
  );
  ContractRegistry.declare(
    'project_specs/changes',
    const ContractVersion(1, 0),
  );
  ContractRegistry.declare(
    'project_specs/drift',
    const ContractVersion(1, 0),
  );

  WorkspaceRegistry.register(
    Workspace.projectSpecs,
    'projects',
    (_) => const ProjectsView(),
  );
  WorkspaceRegistry.register(
    Workspace.projectSpecs,
    'current_work',
    (_) => const CurrentWorkView(),
  );
  WorkspaceRegistry.register(
    Workspace.projectSpecs,
    'specs',
    (_) => const SpecsView(),
  );
  WorkspaceRegistry.register(
    Workspace.projectSpecs,
    'changes',
    (_) => const ChangesView(),
  );
  WorkspaceRegistry.register(
    Workspace.projectSpecs,
    'drift',
    (_) => const DriftView(),
  );
}
