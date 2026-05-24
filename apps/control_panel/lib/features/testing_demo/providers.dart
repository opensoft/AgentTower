import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/json_utils.dart';
import '../../core/providers.dart';
import '../../domain/models/demo_readiness_summary.dart';
import '../../domain/models/validation_entrypoint.dart';
import '../../domain/models/validation_run.dart';

/// Riverpod providers for the Testing & Demo workspace. T124+
/// (Phase 7 US5).

class EntrypointListQuery {
  const EntrypointListQuery({this.projectId, this.scopeKind, this.enabled});
  final String? projectId;
  final String? scopeKind;
  final bool? enabled;

  @override
  bool operator ==(Object other) =>
      other is EntrypointListQuery &&
      other.projectId == projectId &&
      other.scopeKind == scopeKind &&
      other.enabled == enabled;

  @override
  int get hashCode => Object.hash(projectId, scopeKind, enabled);
}

final validationEntrypointListProvider = FutureProvider.autoDispose
    .family<List<ValidationEntrypoint>, EntrypointListQuery>(
        (ref, query) async {
  final page = await ref.watch(appClientProvider).validationEntrypointList(
        projectId: query.projectId,
        scopeKind: query.scopeKind,
        enabled: query.enabled,
      );
  final asOf = DateTime.now().toUtc();
  return page.items
      .map((m) => ValidationEntrypoint.fromJson(withAsOfDefault(m, asOf)))
      .toList(growable: false);
});

class RunListQuery {
  const RunListQuery({
    this.projectId,
    this.entrypointId,
    this.state,
    this.branch,
  });
  final String? projectId;
  final String? entrypointId;
  final String? state;
  final String? branch;

  @override
  bool operator ==(Object other) =>
      other is RunListQuery &&
      other.projectId == projectId &&
      other.entrypointId == entrypointId &&
      other.state == state &&
      other.branch == branch;

  @override
  int get hashCode =>
      Object.hash(projectId, entrypointId, state, branch);
}

final validationRunListProvider = FutureProvider.autoDispose
    .family<List<ValidationRun>, RunListQuery>((ref, query) async {
  final page = await ref.watch(appClientProvider).validationRunList(
        projectId: query.projectId,
        entrypointId: query.entrypointId,
        state: query.state,
        branch: query.branch,
      );
  final asOf = DateTime.now().toUtc();
  return page.items
      .map((m) => ValidationRun.fromJson(withAsOfDefault(m, asOf)))
      .toList(growable: false);
});

final validationRunDetailProvider =
    FutureProvider.autoDispose.family<ValidationRun, String>((ref, runId) async {
  final raw = await ref.watch(appClientProvider).validationRunDetail(runId);
  return ValidationRun.fromJson(withAsOfDefault(raw, DateTime.now().toUtc()));
});

class DemoReadinessQuery {
  const DemoReadinessQuery({required this.projectId, required this.branch});
  final String projectId;
  final String branch;

  @override
  bool operator ==(Object other) =>
      other is DemoReadinessQuery &&
      other.projectId == projectId &&
      other.branch == branch;

  @override
  int get hashCode => Object.hash(projectId, branch);
}

final demoReadinessProvider = FutureProvider.autoDispose
    .family<DemoReadinessSummary, DemoReadinessQuery>((ref, query) async {
  final raw = await ref.watch(appClientProvider).demoReadinessDetail(
        projectId: query.projectId,
        branch: query.branch,
      );
  return DemoReadinessSummary.fromJson(
    withAsOfDefault(raw, DateTime.now().toUtc()),
  );
});
