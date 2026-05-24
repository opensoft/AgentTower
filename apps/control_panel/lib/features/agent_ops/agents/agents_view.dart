import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../domain/models/adopted_agent.dart';
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
class AgentsView extends ConsumerWidget {
  const AgentsView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final agents = ref.watch(agentListProvider);
    return agents.when(
      data: (rows) => rows.isEmpty
          ? const Center(
              child: Padding(
                padding: EdgeInsets.all(32),
                child: Text(
                  'No adopted agents yet.\n\n'
                  'Adopt a pane from the Panes view to see it appear here as a registered agent.',
                  textAlign: TextAlign.center,
                ),
              ),
            )
          : RefreshIndicator(
              onRefresh: () async => ref.invalidate(agentListProvider),
              child: ListView.builder(
                itemCount: rows.length,
                itemBuilder: (_, i) => _AgentTile(agent: rows[i]),
              ),
            ),
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('Could not load agents: $e', textAlign: TextAlign.center),
            const SizedBox(height: 12),
            OutlinedButton(
              onPressed: () => ref.invalidate(agentListProvider),
              child: const Text('Retry'),
            ),
          ],
        ),
      ),
    );
  }
}

class _AgentTile extends StatelessWidget {
  const _AgentTile({required this.agent});

  final AdoptedAgent agent;

  @override
  Widget build(BuildContext context) {
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
                Text('Goal: ${agent.currentGoal}'),
              ],
              if (agent.currentTask != null) Text('Task: ${agent.currentTask}'),
              const SizedBox(height: 8),
              Row(
                children: [
                  TextButton.icon(
                    icon: const Icon(Icons.send_outlined),
                    label: const Text('Send'),
                    onPressed: () => DirectSendDialog.show(context, agent: agent),
                  ),
                  const SizedBox(width: 8),
                  LogAttachAffordance(agent: agent),
                  const SizedBox(width: 8),
                  TextButton.icon(
                    icon: const Icon(Icons.edit_outlined),
                    label: const Text('Edit'),
                    onPressed: () => EditAgentDialog.show(context, agent: agent),
                  ),
                ],
              ),
              if (descendants > 0)
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text('+$descendants descendants'),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
