import 'package:freezed_annotation/freezed_annotation.dart';

import 'common_enums.dart';

part 'adopted_agent.freezed.dart';
part 'adopted_agent.g.dart';

/// FEAT-011 `app.agent` mirror. T059 (Phase 3 US1) + data-model §1.2.
///
/// `agentId` is daemon-issued and identity-bearing. `label` is operator-
/// supplied via `app.agent.register_from_pane` / `app.agent.update` and
/// MAY change without invalidating the agent identity.
///
/// Sub-agent tree rendering rule (FR-015 + data-model §1.2): the Agents
/// view shows at most 2 visible levels of descendants; deeper levels
/// collapse behind `descendantsBeyondVisible` ("+N descendants"). Both
/// fields come from the daemon's `app.agent.list` projection.
@freezed
class AdoptedAgent with _$AdoptedAgent {
  const factory AdoptedAgent({
    required String agentId,
    required String label,
    required AgentRole role,
    required String capability,
    required String projectPath,
    required AgentState state,
    String? parentAgentId,
    int? descendantsBeyondVisible,
    required String containerId,
    required String paneId,
    LogAttachmentState? logAttachment,
    String? currentGoal,
    String? currentTask,
    DateTime? lastMeaningfulActivityAt,
    required DateTime asOf,
  }) = _AdoptedAgent;

  factory AdoptedAgent.fromJson(Map<String, dynamic> json) =>
      _$AdoptedAgentFromJson(json);
}
