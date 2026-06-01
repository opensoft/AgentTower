import '../../domain/models/common_enums.dart';

/// Per-surface minimum required `app_contract_version` map (T015 + Round-3 R-27).
///
/// Each feature module declares the minimum `app_contract_version` its
/// surfaces require by calling [ContractRegistry.declare] (typically inside
/// the file that declares the surface's Riverpod providers). A
/// short-lived bootstrap step in `main.dart` seeds the well-known surfaces
/// for which provider files do not yet exist.
///
/// Per FR-002, surfaces whose minimum version is unmet by the running
/// daemon degrade to read-only with the documented
/// `contract-version-incompatible` state from FR-004. Mutations on those
/// surfaces are disabled with an inline explanation.
///
/// Per Round-3 R-27 this should ultimately become code-derived at build
/// time. Until then, the runtime registry below replaces the previous
/// central hand-rolled map (review finding A5) so adding a new surface
/// touches only its own file.

class ContractVersion {
  const ContractVersion(this.major, this.minor);

  factory ContractVersion.parse(String wireValue) {
    final parts = wireValue.split('.');
    if (parts.length != 2) {
      throw FormatException('Invalid app_contract_version: $wireValue');
    }
    final major = int.tryParse(parts[0]);
    final minor = int.tryParse(parts[1]);
    if (major == null || minor == null) {
      throw FormatException('Invalid app_contract_version: $wireValue');
    }
    return ContractVersion(major, minor);
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

/// Runtime registry of per-surface contract minimums. Feature modules
/// call [declare] at module load (`main.dart` seeds the MVP set below).
/// The Settings → Doctor surface (T026) reads [snapshot] to render the
/// FR-002 banner + per-surface degradation list.
class ContractRegistry {
  ContractRegistry._();

  /// Minimum app-wide contract version. Below this even bootstrap fails.
  static const ContractVersion appMinimum = ContractVersion(1, 0);

  static final Map<SurfaceId, ContractVersion> _declarations = {};

  /// Declares that [surface] requires at least [minimum] from the
  /// daemon. Idempotent on `surface`: a second `declare` with a lower
  /// minimum is ignored; a higher one wins. This guards against a
  /// late-loading module that declares an older version stomping a
  /// newer one already on file.
  static void declare(SurfaceId surface, ContractVersion minimum) {
    final existing = _declarations[surface];
    if (existing == null || _isHigher(minimum, existing)) {
      _declarations[surface] = minimum;
    }
  }

  /// Returns an unmodifiable view of the current declarations.
  static Map<SurfaceId, ContractVersion> snapshot() =>
      Map.unmodifiable(_declarations);

  /// Test-only: clears all declarations so each test starts from a clean slate.
  static void resetForTesting() => _declarations.clear();

  static bool _isHigher(ContractVersion a, ContractVersion b) =>
      a.major > b.major || (a.major == b.major && a.minor > b.minor);
}

/// Seeds the MVP per-surface declarations. Called once from `main.dart`
/// (and from test setup). Each US-phase task that introduces a new
/// surface should add a `ContractRegistry.declare(...)` line either here
/// or — preferably — in its own feature file at module load time.
void seedMvpContractDeclarations() {
  // Phase 3 (US1) MVP surfaces — all on v1.0.
  ContractRegistry.declare('agent_ops/dashboard', const ContractVersion(1, 0));
  ContractRegistry.declare('agent_ops/containers', const ContractVersion(1, 0));
  ContractRegistry.declare('agent_ops/panes', const ContractVersion(1, 0));
  ContractRegistry.declare('agent_ops/agents', const ContractVersion(1, 0));
  ContractRegistry.declare('agent_ops/events', const ContractVersion(1, 0));
  ContractRegistry.declare('agent_ops/queue', const ContractVersion(1, 0));
  ContractRegistry.declare('agent_ops/routes', const ContractVersion(1, 0));
  ContractRegistry.declare('agent_ops/health', const ContractVersion(1, 0));

  // Phase 4-8 surfaces — anticipated FEAT-011 v1.x bumps per
  // contracts/app-methods-consumed.md §3.
  ContractRegistry.declare(
      'project_specs/projects', const ContractVersion(1, 1));
  ContractRegistry.declare(
      'project_specs/current_work', const ContractVersion(1, 1));
  ContractRegistry.declare('project_specs/specs', const ContractVersion(1, 1));
  ContractRegistry.declare(
      'project_specs/changes', const ContractVersion(1, 1));
  ContractRegistry.declare('project_specs/drift', const ContractVersion(1, 1));
  ContractRegistry.declare(
      'project_specs/handoff', const ContractVersion(1, 1));
  ContractRegistry.declare(
      'testing_demo/available_validation', const ContractVersion(1, 1));
  ContractRegistry.declare('testing_demo/runs', const ContractVersion(1, 1));
  ContractRegistry.declare(
      'testing_demo/demo_readiness', const ContractVersion(1, 1));
}

/// Back-compat shim around the old `ContractCompatMap.appMinimum` /
/// `ContractCompatMap.perSurfaceMinimum` accessors. New code should
/// prefer [ContractRegistry] directly.
class ContractCompatMap {
  ContractCompatMap._();

  static ContractVersion get appMinimum => ContractRegistry.appMinimum;
  static Map<SurfaceId, ContractVersion> get perSurfaceMinimum =>
      ContractRegistry.snapshot();
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

  /// Contract-derived runtime classification per FR-004. Only resolves
  /// the contract-gated subset: `contractVersionIncompatible`,
  /// `runtimeDegraded`, or `runtimeHealthyPopulated`. The remaining
  /// FR-004 states — `runtimeUnreachable` (connection layer) and
  /// `runtimeHealthyEmpty` (data-presence layer) — are decided by the
  /// caller, not here.
  RuntimeStateKind get runtimeStateKind {
    if (majorIncompatible) {
      return RuntimeStateKind.contractVersionIncompatible;
    }
    if (unmetSurfaces.isNotEmpty) {
      return RuntimeStateKind.runtimeDegraded;
    }
    return RuntimeStateKind.runtimeHealthyPopulated;
  }

  /// Compute the compatibility report for a given daemon version against
  /// every currently-declared surface in [ContractRegistry].
  static ContractCompat compute(ContractVersion daemonVersion) {
    final unmet = <SurfaceId, ContractVersion>{};
    for (final entry in ContractRegistry.snapshot().entries) {
      if (!daemonVersion.satisfies(entry.value)) {
        unmet[entry.key] = entry.value;
      }
    }
    return ContractCompat(
      daemonVersion: daemonVersion,
      appMinimum: ContractRegistry.appMinimum,
      unmetSurfaces: unmet,
    );
  }
}
