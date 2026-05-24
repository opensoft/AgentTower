/// FR-070 "compatible app launch" check. T019 (Phase 2 Foundational).
///
/// Persisted UX state is restored on launch ONLY when:
///   1. Same app major version as the previous run, AND
///   2. Same `app_contract_version` major as the previous run.
///
/// On mismatch: persisted UX state is dropped + operator lands on
/// onboarding (if not previously completed) or Dashboard.
class LaunchCompatibility {
  const LaunchCompatibility({
    required this.currentAppMajor,
    required this.currentContractMajor,
  });

  final int currentAppMajor;
  final int currentContractMajor;

  /// Returns `true` iff the persisted launch metadata matches the current
  /// process's expectations.
  bool isCompatible({
    required int persistedAppMajor,
    required int persistedContractMajor,
  }) =>
      persistedAppMajor == currentAppMajor &&
      persistedContractMajor == currentContractMajor;
}
