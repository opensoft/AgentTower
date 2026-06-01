import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/l10n/app_localizations.dart';
import '../../../core/persistence/sort_filter_state.dart';
import '../../../core/providers.dart';
import '../../../domain/models/adopted_agent.dart';
import '../../../domain/models/common_enums.dart';
import '../../../ui/widgets/list_controls.dart';
import '../providers.dart';
import 'direct_send.dart';
import 'edit_agent.dart';
import 'log_attach_affordance.dart';

/// Agent Operations → Agents. T069 (Phase 3 US1) + FR-015 + FR-030 +
/// FR-071.
///
/// Renders adopted agents grouped by parent (sub-agent tree, max 2
/// visible levels per data-model §1.2). Deeper levels collapse behind
/// `descendantsBeyondVisible` ("+N descendants").
///
/// Each row exposes:
///   - Direct Send (FR-018) → [DirectSendDialog]
///   - Log attach/detach (FR-017) → [LogAttachAffordance]
///
/// FR-078 (T180): persisted agent-state filter, global scope. Filtering
/// is applied per row; a matched child whose parent is filtered out is
/// still shown (the tree indent simply has no visible parent row).
class AgentsView extends ConsumerStatefulWidget {
  const AgentsView({super.key});

  @override
  ConsumerState<AgentsView> createState() => _AgentsViewState();
}

class _AgentsViewState extends ConsumerState<AgentsView> {
  static const _viewId = 'agent_ops/agents';
  AgentState? _filter;
  bool _loaded = false;

  @override
  Widget build(BuildContext context) {
    if (!_loaded) {
      _loaded = true;
      final p = ref.read(sortFilterRepositoryProvider).load(viewId: _viewId);
      _filter = filterValueFromWire(
          p.filters['state'], AgentState.values, (s) => s.wireValue);
    }
    final l10n = AppLocalizations.of(context);
    final agents = ref.watch(agentListProvider);
    return agents.when(
      data: (rows) {
        final filtered = _filter == null
            ? rows
            : rows.where((a) => a.state == _filter).toList(growable: false);
        return Column(
          children: [
            ListControlsBar(
              controls: [
                EnumFilterMenu<AgentState>(
                  tooltip: l10n.agentsFilterStateTooltip,
                  allLabel: l10n.agentsFilterAllStates,
                  value: _filter,
                  options: AgentState.values,
                  labelOf: (s) => s.wireValue,
                  onSelected: _onFilter,
                ),
              ],
            ),
            Expanded(
              child: rows.isEmpty
                  ? Center(
                      child: Padding(
                        padding: const EdgeInsets.all(32),
                        child: Text(
                          l10n.agentsEmptyMessage,
                          textAlign: TextAlign.center,
                        ),
                      ),
                    )
                  : RefreshIndicator(
                      onRefresh: () async => ref.invalidate(agentListProvider),
                      child: filtered.isEmpty
                          ? FilterNoMatch(
                              message: l10n.agentsFilterNoMatch)
                          : ListView.builder(
                              itemCount: filtered.length,
                              itemBuilder: (_, i) =>
                                  _AgentTile(agent: filtered[i]),
                            ),
                    ),
            ),
          ],
        );
      },
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(l10n.agentsLoadError(e.toString()),
                textAlign: TextAlign.center),
            const SizedBox(height: 12),
            OutlinedButton(
              onPressed: () => ref.invalidate(agentListProvider),
              child: Text(l10n.agentsRetry),
            ),
          ],
        ),
      ),
    );
  }

  void _onFilter(AgentState? v) {
    setState(() => _filter = v);
    ref.read(sortFilterRepositoryProvider).save(
          viewId: _viewId,
          value: ListSortFilterState(
            filters: {if (v != null) 'state': v.wireValue},
          ),
        );
  }
}

class _AgentTile extends StatelessWidget {
  const _AgentTile({required this.agent});

  final AdoptedAgent agent;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final indent = agent.parentAgentId != null ? 32.0 : 0.0;
    final descendants = agent.descendantsBeyondVisible ?? 0;
    return Padding(
      padding: EdgeInsets.only(left: indent),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Chip(label: Text(agent.role.wireValue)),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      agent.label,
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                  ),
                  Text(
                    agent.state.wireValue,
                    style: Theme.of(context).textTheme.labelSmall,
                  ),
                ],
              ),
              const SizedBox(height: 4),
              Text(
                '${agent.capability} · ${agent.projectPath}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
              if (agent.currentGoal != null) ...[
                const SizedBox(height: 8),
                Text(l10n.agentsGoal(agent.currentGoal!)),
              ],
              if (agent.currentTask != null)
                Text(l10n.agentsTask(agent.currentTask!)),
              const SizedBox(height: 8),
              Row(
                children: [
                  TextButton.icon(
                    icon: const Icon(Icons.send_outlined),
                    label: Text(l10n.agentsSend),
                    onPressed: () => DirectSendDialog.show(context, agent: agent),
                  ),
                  const SizedBox(width: 8),
                  LogAttachAffordance(agent: agent),
                  const SizedBox(width: 8),
                  TextButton.icon(
                    icon: const Icon(Icons.edit_outlined),
                    label: Text(l10n.agentsEdit),
                    onPressed: () => EditAgentDialog.show(context, agent: agent),
                  ),
                ],
              ),
              if (descendants > 0)
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text(l10n.agentsDescendants(descendants)),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
