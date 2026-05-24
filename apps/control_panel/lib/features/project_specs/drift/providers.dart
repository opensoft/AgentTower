import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/providers.dart';
import '../../../domain/models/drift_signal.dart';

/// Riverpod providers for drift surfaces. T115/T116 (Phase 6 US4).

final driftListProvider = FutureProvider.autoDispose
    .family<List<DriftSignal>, DriftListQuery>((ref, query) async {
  final page = await ref.watch(appClientProvider).driftList(
        projectId: query.projectId,
        status: query.status,
        severity: query.severity,
      );
  final asOf = DateTime.now().toUtc();
  return page.items
      .map((m) => DriftSignal.fromJson(_withAsOf(m, asOf)))
      .toList(growable: false);
});

final driftDetailProvider =
    FutureProvider.autoDispose.family<DriftSignal, String>((ref, id) async {
  final raw = await ref.watch(appClientProvider).driftDetail(id);
  return DriftSignal.fromJson(_withAsOf(raw, DateTime.now().toUtc()));
});

class DriftListQuery {
  const DriftListQuery({this.projectId, this.status, this.severity});
  final String? projectId;
  final String? status;
  final String? severity;

  @override
  bool operator ==(Object other) =>
      other is DriftListQuery &&
      other.projectId == projectId &&
      other.status == status &&
      other.severity == severity;

  @override
  int get hashCode => Object.hash(projectId, status, severity);
}

Map<String, dynamic> _withAsOf(Map<String, dynamic> raw, DateTime asOf) {
  if (raw.containsKey('as_of')) return raw;
  return {...raw, 'as_of': asOf.toIso8601String()};
}
