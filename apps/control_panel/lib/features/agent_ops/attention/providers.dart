import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/json_utils.dart';
import '../../../core/providers.dart';
import '../../../domain/models/attention_item.dart';
import '../../../domain/models/operator_history_entry.dart';

/// Riverpod providers for attention queue + operator history. T135+
/// (Phase 8 US6).

class AttentionListQuery {
  const AttentionListQuery({
    this.projectId,
    this.severity,
    this.attentionClass,
  });

  final String? projectId;
  final String? severity;
  final String? attentionClass;

  @override
  bool operator ==(Object other) =>
      other is AttentionListQuery &&
      other.projectId == projectId &&
      other.severity == severity &&
      other.attentionClass == attentionClass;

  @override
  int get hashCode => Object.hash(projectId, severity, attentionClass);
}

final attentionListProvider = FutureProvider.autoDispose
    .family<List<AttentionItem>, AttentionListQuery>((ref, query) async {
  final page = await ref.watch(appClientProvider).attentionList(
        projectId: query.projectId,
        severity: query.severity,
        attentionClass: query.attentionClass,
      );
  final asOf = DateTime.now().toUtc();
  return page.items
      .map((m) => AttentionItem.fromJson(withAsOfDefault(m, asOf)))
      .toList(growable: false);
});

final operatorHistoryListProvider = FutureProvider.autoDispose
    .family<List<OperatorHistoryEntry>, String?>((ref, parentAgentId) async {
  final page = await ref
      .watch(appClientProvider)
      .operatorHistoryList(parentAgentId: parentAgentId);
  final asOf = DateTime.now().toUtc();
  return page.items
      .map((m) => OperatorHistoryEntry.fromJson(withAsOfDefault(m, asOf)))
      .toList(growable: false);
});
