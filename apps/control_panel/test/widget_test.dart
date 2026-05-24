import 'package:agenttower_control_panel/core/daemon/contract_version.dart';
import 'package:agenttower_control_panel/domain/models/common_enums.dart';
import 'package:flutter_test/flutter_test.dart';

/// Smoke test for the AgentTower Control Panel. Replaces the Flutter
/// `flutter create` scaffold default that referenced a non-existent
/// `MyApp` widget (review fix C10 / test lane).
///
/// Real widget tests for the 12 US1 surfaces land alongside Block D
/// hardening. This file's purpose is just to keep `flutter test` from
/// failing to compile.
void main() {
  test('seedMvpContractDeclarations registers every Phase 3 + 4-8 surface',
      () {
    ContractRegistry.resetForTesting();
    seedMvpContractDeclarations();
    final declared = ContractRegistry.snapshot();

    // Phase 3 (US1) surfaces — all on v1.0.
    for (final id in const [
      'agent_ops/dashboard',
      'agent_ops/containers',
      'agent_ops/panes',
      'agent_ops/agents',
      'agent_ops/events',
      'agent_ops/queue',
      'agent_ops/routes',
      'agent_ops/health',
    ]) {
      expect(declared[id], const ContractVersion(1, 0),
          reason: '$id should require contract version 1.0');
    }

    // Phase 4-8 surfaces — anticipated v1.1.
    for (final id in const [
      'project_specs/projects',
      'project_specs/handoff',
      'testing_demo/runs',
    ]) {
      expect(declared[id], const ContractVersion(1, 1),
          reason: '$id should require contract version 1.1');
    }
  });

  test('OnboardingMilestone wire values are stable across schema migrations',
      () {
    expect(OnboardingMilestone.daemonReachable.wireValue, 'daemon_reachable');
    expect(OnboardingMilestone.firstPaneAdoption.wireValue,
        'first_pane_adoption');
    expect(OnboardingMilestone.values.length, 8);
  });
}
