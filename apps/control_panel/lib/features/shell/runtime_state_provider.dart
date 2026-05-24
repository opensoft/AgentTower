import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/daemon/contract_version.dart';
import '../../domain/models/common_enums.dart';

/// Riverpod provider for the five FR-004 runtime states. T049 (Phase 2 Foundational).
///
/// FR-004 enumerates: runtime-unreachable, contract-version-incompatible,
/// runtime-healthy-empty, runtime-healthy-populated, runtime-degraded.
///
/// Surfaces watch this provider to render the documented per-state UX
/// (empty-state copy, error-state copy, etc.).
class RuntimeState {
  const RuntimeState({
    required this.kind,
    this.daemonVersion,
    this.contractCompat,
    this.lastError,
  });

  final RuntimeStateKind kind;
  final String? daemonVersion;
  final ContractCompat? contractCompat;
  final Object? lastError;

  /// Initial state on app launch (pre-bootstrap).
  static const RuntimeState initial =
      RuntimeState(kind: RuntimeStateKind.runtimeUnreachable);
}

/// Owner: app shell. Mutations: only by the session/bootstrap layer.
final runtimeStateProvider = StateProvider<RuntimeState>(
  (ref) => RuntimeState.initial,
);
