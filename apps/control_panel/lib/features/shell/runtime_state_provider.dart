import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/daemon/contract_version.dart';
import '../../core/daemon/errors.dart';
import '../../core/daemon/session.dart';
import '../../core/providers.dart';
import '../../domain/models/common_enums.dart';

/// Riverpod provider for the five FR-004 runtime states. T049 (Phase 2 Foundational).
///
/// FR-004 enumerates: runtime-unreachable, contract-version-incompatible,
/// runtime-healthy-empty, runtime-healthy-populated, runtime-degraded.
///
/// Surfaces watch this provider to render the documented per-state UX
/// (empty-state copy, error-state copy, etc.).
///
/// Review finding A2: the previous `StateProvider` had no wiring — it was
/// declared but never updated, so the FR-002 global banner (which watches
/// it) could never light up. The Notifier below subscribes to the
/// [DaemonSession.events] stream so every bootstrap / failure / teardown
/// emitted by the session layer transitions the runtime state.
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

  RuntimeState copyWith({
    RuntimeStateKind? kind,
    String? daemonVersion,
    ContractCompat? contractCompat,
    Object? lastError,
  }) =>
      RuntimeState(
        kind: kind ?? this.kind,
        daemonVersion: daemonVersion ?? this.daemonVersion,
        contractCompat: contractCompat ?? this.contractCompat,
        lastError: lastError ?? this.lastError,
      );
}

/// Owner: app shell. Updates: driven entirely by [DaemonSession.events]
/// so individual feature widgets cannot mutate runtime state directly.
class RuntimeStateNotifier extends Notifier<RuntimeState> {
  StreamSubscription<SessionEvent>? _sub;

  @override
  RuntimeState build() {
    // Re-subscribe whenever the session provider rebuilds. Riverpod
    // disposes the previous Notifier (and our subscription with it).
    final session = ref.watch(daemonSessionProvider);
    _sub?.cancel();
    _sub = session.events.listen(_onEvent);
    ref.onDispose(() => _sub?.cancel());
    return RuntimeState.initial;
  }

  void _onEvent(SessionEvent event) {
    switch (event) {
      case SessionBootstrapped(:final daemonVersion, :final appContractVersion):
        final daemonV = ContractVersion.parse(appContractVersion);
        final compat = ContractCompat.compute(daemonV);
        state = state.copyWith(
          kind: compat.runtimeStateKind,
          daemonVersion: daemonVersion,
          contractCompat: compat,
        );
      case SessionFailed(:final error):
        // Map the FR-002 banner trigger explicitly: contract-major
        // unsupported flips us into contract-version-incompatible
        // regardless of socket health.
        if (error is AppContractError &&
            error.code == AppContractErrorCode.appContractMajorUnsupported) {
          state = state.copyWith(
            kind: RuntimeStateKind.contractVersionIncompatible,
            lastError: error,
          );
        } else {
          state = state.copyWith(
            kind: RuntimeStateKind.runtimeUnreachable,
            lastError: error,
          );
        }
      case SessionTornDown():
        state = state.copyWith(kind: RuntimeStateKind.runtimeUnreachable);
    }
  }
}

final runtimeStateProvider =
    NotifierProvider<RuntimeStateNotifier, RuntimeState>(
  RuntimeStateNotifier.new,
);
