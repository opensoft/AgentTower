import 'package:agenttower_control_panel/core/daemon/contract_version.dart';
import 'package:agenttower_control_panel/domain/models/common_enums.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

/// FR-004 five-state runtime distinction. T055 (Phase 3 US1) +
/// review fix C11/C12 (rewrite of the prior placeholder test).
///
/// The earlier draft of this file tried to inject `SessionFailed`
/// events into a `Stream.value(...).listen(_)` orphan stream and read
/// `daemonSessionProvider` without overriding it — neither actually
/// fed the [RuntimeStateNotifier], and the assertion was tautological
/// because `RuntimeState.initial.kind == runtimeUnreachable`.
///
/// This rewrite drops the placeholder integration test and keeps only
/// the meaningful unit-level assertion on [ContractCompat.compute] —
/// the function that drives the FR-004 mapping from a daemon
/// `app_contract_version` to a [RuntimeStateKind]. End-to-end coverage
/// of the SC-010 budgets (2 s outage → empty state, 5 s restore) is
/// tracked separately in `tasks.md` and `flutter-testing-plan.md`
/// because it requires real socket lifecycle wiring + a wall-clock
/// timer harness that exceeds the scope of this single test file.
void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    ContractRegistry.resetForTesting();
    seedMvpContractDeclarations();
  });

  test('ContractCompat.compute classifies the documented FR-004 mappings',
      () {
    // Healthy: daemon at 1.1 satisfies every declared minimum (Phase 3
    // surfaces require 1.0; Phase 4+ require 1.1 in the MVP seed).
    final healthy = ContractCompat.compute(const ContractVersion(1, 1));
    expect(healthy.overallSatisfied, isTrue);
    expect(healthy.runtimeStateKind,
        RuntimeStateKind.runtimeHealthyPopulated);

    // Degraded: daemon at 1.0 satisfies Phase 3 but not the Phase 4+
    // declarations from the MVP seed.
    final degraded = ContractCompat.compute(const ContractVersion(1, 0));
    expect(degraded.unmetSurfaces, isNotEmpty);
    expect(degraded.runtimeStateKind, RuntimeStateKind.runtimeDegraded);

    // Incompatible: daemon at 2.0 fails the major check entirely.
    final incompat = ContractCompat.compute(const ContractVersion(2, 0));
    expect(incompat.majorIncompatible, isTrue);
    expect(incompat.runtimeStateKind,
        RuntimeStateKind.contractVersionIncompatible);
  });

  test('seedMvpContractDeclarations is idempotent on re-seed', () {
    final first = ContractRegistry.snapshot();
    seedMvpContractDeclarations(); // second call
    final second = ContractRegistry.snapshot();
    expect(second.length, first.length);
    expect(second, equals(first));
  });

  test('ContractRegistry.declare honors the higher-version-wins rule', () {
    ContractRegistry.declare('agent_ops/test', const ContractVersion(1, 0));
    ContractRegistry.declare('agent_ops/test', const ContractVersion(1, 1));
    ContractRegistry.declare('agent_ops/test', const ContractVersion(1, 0));
    expect(ContractRegistry.snapshot()['agent_ops/test'],
        const ContractVersion(1, 1));
  });
}
