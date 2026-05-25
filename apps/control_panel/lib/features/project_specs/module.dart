import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/daemon/contract_version.dart';
import '../../core/l10n/app_localizations.dart';
import '../../core/shortcuts/command_palette.dart';
import '../../domain/models/common_enums.dart';
import '../../routing/route_paths.dart';
import '../registry.dart';
import 'changes/changes_view.dart';
import 'current_work/current_work_view.dart';
import 'drift/drift_view.dart';
import 'projects/add_project.dart';
import 'projects/projects_view.dart';
import 'providers.dart' as project_providers;
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

/// Swarm-review CR-5 + FR-075: register Project + Specs primary
/// actions and sub-view jumps with the command palette so `Ctrl+K`
/// / `Cmd+K` surfaces them. Called from a `Consumer` mounted at the
/// `AppShell` level; idempotent on `id`, so re-registration is safe.
///
/// Per FR-075: "Every primary action surfaced in the app MUST be
/// reachable from a documented keyboard shortcut." The palette is
/// the documented home for actions that don't warrant a per-action
/// hotkey.
void registerProjectSpecsPaletteCommands(WidgetRef ref) {
  final notifier = ref.read(commandRegistryProvider.notifier);
  final l10n = AppLocalizations.of(ref.context);

  // ---- Sub-view jumps ----
  final entries = <(String, String)>[
    ('projects', l10n.paletteSubViewLabelProjects),
    ('current_work', l10n.paletteSubViewLabelCurrentWork),
    ('specs', l10n.paletteSubViewLabelSpecs),
    ('changes', l10n.paletteSubViewLabelChanges),
    ('drift', l10n.paletteSubViewLabelDrift),
  ];
  for (final entry in entries) {
    final (subView, label) = entry;
    notifier.register(PaletteCommand(
      id: 'project_specs.goto.$subView',
      label: l10n.paletteGoToPrefix(label),
      category: l10n.paletteCategoryNavigate,
      invoke: (context) async {
        await Navigator.of(context).pushNamed(
          RoutePath(
            workspace: Workspace.projectSpecs,
            subViewId: subView,
          ).toRouteString(),
        );
      },
    ));
  }

  // ---- Project mutations ----
  notifier.register(PaletteCommand(
    id: 'project_specs.add_project',
    label: l10n.paletteAddProject,
    category: l10n.paletteCategoryProject,
    invoke: (context) async {
      await showDialog<bool>(
        context: context,
        builder: (_) => const AddProjectDialog(),
      );
    },
  ));

  // ---- Handoff entry (current-work surface drives the rest) ----
  //
  // T175 (fixes T168): previously this command navigated to the
  // current_work sub-view — its name promised opening the handoff
  // flow but its behavior only routed somewhere the flow can be
  // launched FROM. Now it actually opens HandoffFlow via the shared
  // `openHandoffFlowForSelectedProject` helper, which resolves the
  // currently-selected project + driving master at invoke time and
  // degrades to a localized snackbar when either is missing.
  notifier.register(PaletteCommand(
    id: 'project_specs.open_handoff_flow',
    label: l10n.paletteOpenHandoffFlow,
    category: l10n.paletteCategoryHandoff,
    contextual: true,
    invoke: (context) async {
      // Read the selected project id at invoke-time (not registration-time)
      // so the command reflects the operator's current context.
      final selectedId =
          ref.read(project_providers.selectedProjectIdProvider);
      await openHandoffFlowForSelectedProject(context, ref, selectedId);
    },
  ));

  // ---- Drift entry ----
  notifier.register(PaletteCommand(
    id: 'project_specs.open_drift',
    label: l10n.paletteOpenDrift,
    category: l10n.paletteCategoryDrift,
    invoke: (context) async {
      await Navigator.of(context).pushNamed(
        const RoutePath(
          workspace: Workspace.projectSpecs,
          subViewId: 'drift',
        ).toRouteString(),
      );
    },
  ));
}
