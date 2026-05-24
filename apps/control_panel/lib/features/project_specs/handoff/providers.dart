import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/providers.dart';
import '../../../core/json_utils.dart';
import '../../../domain/models/handoff.dart';

/// Riverpod providers for handoff list + detail surfaces. T110 / T111
/// (Phase 5 US3).

final handoffListProvider = FutureProvider.autoDispose
    .family<List<Handoff>, HandoffListQuery>((ref, query) async {
  final page = await ref.watch(appClientProvider).handoffList(
        projectId: query.projectId,
        targetMasterAgentId: query.targetMasterAgentId,
        featureChangeId: query.featureChangeId,
        assignmentState: query.assignmentState,
        createdAfter: query.createdAfter,
        createdBefore: query.createdBefore,
      );
  final asOf = DateTime.now().toUtc();
  return page.items
      .map((m) => Handoff.fromJson(withAsOfDefault(m, asOf)))
      .toList(growable: false);
});

final handoffDetailProvider =
    FutureProvider.autoDispose.family<Handoff, String>((ref, handoffId) async {
  final raw = await ref.watch(appClientProvider).handoffDetail(handoffId);
  return Handoff.fromJson(withAsOfDefault(raw, DateTime.now().toUtc()));
});

class HandoffListQuery {
  const HandoffListQuery({
    this.projectId,
    this.targetMasterAgentId,
    this.featureChangeId,
    this.assignmentState,
    this.createdAfter,
    this.createdBefore,
  });

  final String? projectId;
  final String? targetMasterAgentId;
  final String? featureChangeId;
  final String? assignmentState;
  final String? createdAfter;
  final String? createdBefore;

  @override
  bool operator ==(Object other) =>
      other is HandoffListQuery &&
      other.projectId == projectId &&
      other.targetMasterAgentId == targetMasterAgentId &&
      other.featureChangeId == featureChangeId &&
      other.assignmentState == assignmentState &&
      other.createdAfter == createdAfter &&
      other.createdBefore == createdBefore;

  @override
  int get hashCode => Object.hash(
        projectId,
        targetMasterAgentId,
        featureChangeId,
        assignmentState,
        createdAfter,
        createdBefore,
      );
}
