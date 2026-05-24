import '../../domain/models/common_enums.dart';

/// Per-surface minimum required `app_contract_version` map (T015 + Round-3 R-27).
///
/// **Code-derived at build time**: each feature module declares the `app.*`
/// methods it consumes; a build-time tool (TODO: T027/T143 doctor surface
/// integration) computes this map by walking the call sites. For now, the
/// map is hand-rolled here as a placeholder. When the build-time codegen
/// lands, this file becomes generated output (`contract_compat_map.g.dart`).
///
/// Per FR-002, surfaces whose minimum version is unmet by the running daemon
/// degrade to read-only with the documented `contract-version-incompatible`
/// state from FR-004. Mutations on those surfaces are disabled with an
/// inline explanation.

class ContractVersion {
  const ContractVersion(this.major, this.minor);

  factory ContractVersion.parse(String wireValue) {
    final parts = wireValue.split('.');
    if (parts.length != 2) {
      throw FormatException('Invalid app_contract_version: $wireValue');
    }
    return ContractVersion(int.parse(parts[0]), int.parse(parts[1]));
  }

  final int major;
  final int minor;

  /// Compatibility per FR-002 — same major, daemon minor ≥ required minor.
  bool satisfies(ContractVersion required) =>
      major == required.major && minor >= required.minor;

  @override
  String toString() => '$major.$minor';

  @override
  bool operator ==(Object other) =>
      other is ContractVersion && other.major == major && other.minor == minor;

  @override
  int get hashCode => Object.hash(major, minor);
}

/// Surface identifier — corresponds to a feature module or sub-view that
/// gates on a contract version.
typedef SurfaceId = String;

/// Per-surface minimum required contract version. Hand-rolled at MVP; per
/// Round-3 R-27 this becomes code-derived at build time. The Settings →
/// Doctor surface (T026) renders this map.
class ContractCompatMap {
  static const ContractVersion appMinimum = ContractVersion(1, 0);

  /// Each surface declares its minimum required version. Surfaces NOT in this
  /// map default to [appMinimum] (1.0) — i.e. they work on any v1.x daemon.
  static const Map<SurfaceId, ContractVersion> perSurfaceMinimum = {
    // Phase 3 (US1) MVP surfaces — all on v1.0.
    'agent_ops/dashboard': ContractVersion(1, 0),
    'agent_ops/containers': ContractVersion(1, 0),
    'agent_ops/panes': ContractVersion(1, 0),
    'agent_ops/agents': ContractVersion(1, 0),
    'agent_ops/events': ContractVersion(1, 0),
    'agent_ops/queue': ContractVersion(1, 0),
    'agent_ops/routes': ContractVersion(1, 0),
    'agent_ops/health': ContractVersion(1, 0),

    // Phase 4-8 surfaces — anticipated FEAT-011 v1.x bumps per
    // contracts/app-methods-consumed.md §3.
    'project_specs/projects': ContractVersion(1, 1),
    'project_specs/current_work': ContractVersion(1, 1),
    'project_specs/specs': ContractVersion(1, 1),
    'project_specs/changes': ContractVersion(1, 1),
    'project_specs/drift': ContractVersion(1, 1),
    'project_specs/handoff': ContractVersion(1, 1),
    'testing_demo/available_validation': ContractVersion(1, 1),
    'testing_demo/runs': ContractVersion(1, 1),
    'testing_demo/demo_readiness': ContractVersion(1, 1),
  };
}

/// Result of comparing the daemon's contract version against the app's
/// per-surface requirements.
class ContractCompat {
  const ContractCompat({
    required this.daemonVersion,
    required this.appMinimum,
    required this.unmetSurfaces,
  });

  final ContractVersion daemonVersion;
  final ContractVersion appMinimum;

  /// SurfaceId → minimum-required-version for surfaces the daemon does NOT
  /// satisfy. Empty map = all green (the FR-002 banner is hidden).
  final Map<SurfaceId, ContractVersion> unmetSurfaces;

  bool get overallSatisfied =>
      daemonVersion.satisfies(appMinimum) && unmetSurfaces.isEmpty;

  bool get majorIncompatible => daemonVersion.major != appMinimum.major;

  /// Five-state runtime classification per FR-004.
  RuntimeStateKind get runtimeStateKind {
    if (majorIncompatible) {
      return RuntimeStateKind.contractVersionIncompatible;
    }
    if (unmetSurfaces.isNotEmpty) {
      return RuntimeStateKind.runtimeDegraded;
    }
    return RuntimeStateKind.runtimeHealthyPopulated;
  }

  /// Compute the compatibility report for a given daemon version.
  static ContractCompat compute(ContractVersion daemonVersion) {
    final unmet = <SurfaceId, ContractVersion>{};
    for (final entry in ContractCompatMap.perSurfaceMinimum.entries) {
      if (!daemonVersion.satisfies(entry.value)) {
        unmet[entry.key] = entry.value;
      }
    }
    return ContractCompat(
      daemonVersion: daemonVersion,
      appMinimum: ContractCompatMap.appMinimum,
      unmetSurfaces: unmet,
    );
  }
}
